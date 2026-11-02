"""Round 5: 4D-STEM detectors, diffraction cal, report export, session tiles."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.report import export_report, export_report_html, export_report_pdf, export_report_pptx
from openvelox.io.synthetic import make_four_d, write_synthetic_emd
from openvelox.processing.stem4d import (
    apply_diffraction_cal,
    center_of_mass_dpc,
    detector_cartoon,
    electron_wavelength_m,
    q_per_px_inv_angstrom,
    radius_to_pixels,
    virtual_abf,
    virtual_adf,
    virtual_bf,
)
from openvelox.ui.session import load_session, save_session


def test_virtual_abf_and_detectors() -> None:
    cube = make_four_d(scan=8, qsize=20, seed=4)
    bf = virtual_bf(cube, radius=4)
    adf = virtual_adf(cube, inner=5, outer=9)
    abf = virtual_abf(cube, inner=2, outer=3.5)
    assert bf.shape == adf.shape == abf.shape == (8, 8)
    assert float(abf.sum()) > 0
    assert float(bf.sum()) > float(abf.sum())
    cart = detector_cartoon(48, bf_r=4, adf_in=5, adf_out=10, abf_in=2, abf_out=3.5)
    assert cart.shape == (48, 48, 3)
    assert cart.max() > 0


def test_diffraction_calibration() -> None:
    lam = electron_wavelength_m(200_000)
    assert 2.0e-12 < lam < 3.0e-12
    assert electron_wavelength_m(0) == 0.0
    qpp = q_per_px_inv_angstrom(camera_length_m=0.20, detector_pixel_m=14e-6, wavelength_m=lam)
    assert qpp > 0
    assert radius_to_pixels(10, "px") == 10
    mrad_px = radius_to_pixels(10.0, "mrad", camera_length_m=0.2, detector_pixel_m=14e-6)
    assert mrad_px == pytest.approx(10e-3 * 0.2 / 14e-6)
    q_px = radius_to_pixels(0.05, "A-1", q_per_px=0.01)
    assert q_px == pytest.approx(5.0)
    vx = np.array([[1.0, 0.0], [0.0, 1.0]])
    vy = np.array([[0.0, 1.0], [0.0, 0.0]])
    rx, ry = apply_diffraction_cal(vx, vy, rotation_deg=90.0, q_per_px=2.0)
    np.testing.assert_allclose(rx, -2.0 * vy, atol=1e-9)
    np.testing.assert_allclose(ry, 2.0 * vx, atol=1e-9)
    cube = make_four_d(scan=6, qsize=16, seed=1)
    cx, cy = center_of_mass_dpc(cube)
    calx, caly = apply_diffraction_cal(cx, cy, rotation_deg=15.0)
    assert calx.shape == cx.shape


def test_report_pdf_html_pptx(tmp_path: Path) -> None:
    image = np.linspace(0, 1, 24 * 32).reshape(24, 32)
    model = {
        "title": "OpenVelox report",
        "subtitle": "unit test",
        "metadata": ["HAADF  200 kV"],
        "images": [("HAADF", image)],
        "spectrum": (np.linspace(0, 10, 64), np.linspace(1, 8, 64)),
        "quant": [{"element": "Au", "atomic_percent": 40.0, "weight_percent": 80.0, "intensity": 12.0, "k_factor": 2.7}],
    }
    pdf = export_report_pdf(tmp_path / "r.pdf", model)
    html = export_report_html(tmp_path / "r.html", model)
    pptx = export_report_pptx(tmp_path / "r.pptx", model)
    assert pdf.is_file() and pdf.stat().st_size > 0
    text = html.read_text(encoding="utf-8")
    assert "HAADF" in text and "Au" in text
    with zipfile.ZipFile(pptx) as zf:
        names = zf.namelist()
    assert "[Content_Types].xml" in names
    assert any(n.startswith("ppt/slides/slide") for n in names)
    odd = export_report(tmp_path / "fallback.csv", model)
    assert odd.suffix == ".pdf" and odd.is_file()


def test_session_version_and_tiles(tmp_path: Path) -> None:
    emd = write_synthetic_emd(tmp_path / "s.emd")
    sess = tmp_path / "s.openvelox.json"
    save_session(
        sess,
        {
            "files": [str(emd)],
            "language": "en",
            "k_factors": {"Au": 2.1},
            "layout": "1x2",
            "tiles": [{"name": "HAADF", "kind": "image"}, {"name": "BF", "kind": "image"}],
            "diffraction": {"q_per_px": 0.02, "rotation_deg": 12, "unit": "px"},
        },
    )
    data = load_session(sess)
    assert data["version"] == 3
    assert data["layout"] == "1x2"
    assert data["diffraction"]["rotation_deg"] == 12


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from openvelox.theme import STYLESHEET, apply_pyqtgraph

    apply_pyqtgraph()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    app.setStyleSheet(STYLESHEET)
    return app


def test_gui_4d_report_session_toolbar(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QToolBar

    from openvelox.i18n import Translator
    from openvelox.models import DatasetKind
    from openvelox.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "report.pdf"), "")),
    )
    win = MainWindow(Translator("en"))
    bars = win.findChildren(QToolBar)
    assert bars
    assert all(bar.objectName() for bar in bars)
    win.open_sample()
    assert win.props.tabText(3) == "FFT"
    four = next(ds for ds in win.browser.all_datasets() if ds.kind is DatasetKind.FOUR_D)
    win.open_dataset(four)
    win.props.abf_in.setValue(1.5)
    win.props.abf_out.setValue(3.0)
    win._on_process("virtual_abf", win.props.stem_params())
    win._on_process("com", win.props.stem_params())
    win._on_process("virtual_bf", {"radius": 4, "unit": "px"})
    win.invoke_action("export_report")
    assert (tmp_path / "report.pdf").is_file()
    win.apply_layout("1x2")
    payload = win.session_payload()
    assert payload["layout"] == "1x2"
    sess = tmp_path / "ws.openvelox.json"
    save_session(sess, payload)
    win.load_session_file(sess)
    assert win._layout_key == "1x2"
    win.close()
