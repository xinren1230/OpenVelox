"""Round 4: EDS peak ID, backgrounds, Cliff–Lorimer, maps, line scans, ROI spectra."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.synthetic import make_spectrum_image
from openvelox.processing.eds import (
    cliff_lorimer,
    color_overlay,
    energy_axis,
    identify_peaks,
    integrate_windows,
    line_scan,
    line_scan_element_profile,
    linear_background,
    make_element_maps,
    spectrum_background,
    sum_spectrum,
    velox_background,
)
from openvelox.processing.xray_lines import atomic_mass


def _peak_spectrum() -> tuple[np.ndarray, np.ndarray]:
    energy = np.linspace(0.05, 20.0, 2000)
    bg = 22.0 * np.exp(-energy / 6.5) + 3.0
    spec = bg.copy()
    for e0, amp in ((1.740, 180.0), (8.047, 220.0), (8.904, 45.0), (9.713, 200.0), (11.442, 65.0)):
        spec += amp * np.exp(-((energy - e0) ** 2) / (2 * 0.06**2))
    return energy, spec


def test_spectrum_background_models() -> None:
    energy, spec = _peak_spectrum()
    peak = int(np.argmin(np.abs(energy - 9.713)))
    for method in ("linear", "snip", "velox"):
        bg = spectrum_background(spec, energy, method=method)
        assert bg.shape == spec.shape
        assert bg[peak] < spec[peak] * 0.55
        assert bg.min() >= -1e-9
    lin = linear_background(spec, energy)
    vel = velox_background(spec, energy)
    assert vel[peak] < spec[peak]
    assert lin.std() < spec.std()
    empty = spectrum_background(np.zeros(0), np.zeros(0), method="snip")
    assert empty.size == 0


def test_identify_labels_and_family_deconvolution() -> None:
    energy, spec = _peak_spectrum()
    peaks = identify_peaks(energy, spec, tolerance=0.12, max_peaks=14)
    labels = {str(p.get("label")) for p in peaks if p.get("symbol")}
    symbols = {p["symbol"] for p in peaks if p.get("symbol")}
    assert {"Si", "Cu", "Au"} <= symbols
    assert any("Cu" in lab and "Ka" in lab for lab in labels)
    cu_kb = [p for p in peaks if p.get("symbol") == "Cu" and p.get("line") == "Kb"]
    assert cu_kb
    assert cu_kb[0].get("family") is True
    raw = identify_peaks(energy, spec, tolerance=0.12, deconvolve=False)
    assert raw


def test_cliff_lorimer_weight_and_atomic() -> None:
    rows = cliff_lorimer({"Au": 100, "Si": 80, "Cu": 20}, k_factors={"Au": 2.7, "Si": 1.0, "Cu": 1.4})
    assert abs(sum(float(r["atomic_percent"]) for r in rows) - 100) < 1e-6
    assert abs(sum(float(r["weight_percent"]) for r in rows) - 100) < 1e-6
    au = next(r for r in rows if r["element"] == "Au")
    si = next(r for r in rows if r["element"] == "Si")
    # Heavier Au must have a higher wt.% share than its at.% share.
    assert au["weight_percent"] > au["atomic_percent"]
    assert si["atomic_percent"] > si["weight_percent"]
    assert atomic_mass("Au") > 190


def test_maps_overlay_and_line_scan_path() -> None:
    si, meta = make_spectrum_image(size=16, n_channels=512, e_scale=0.04, seed=2)
    energy = energy_axis(si.shape[-1], meta["energy_scale_kev"], meta["energy_offset_kev"])
    maps = make_element_maps(si, energy, ["Au", "Si", "Cu"], mode="window")
    assert set(maps) == {"Au", "Si", "Cu"}
    assert maps["Au"][7, 9] > maps["Au"][0, 0]
    gauss = make_element_maps(si, energy, ["Au"], mode="gaussian")
    assert gauss["Au"].shape == si.shape[:2]
    rgb = color_overlay(maps)
    assert rgb.shape == si.shape[:2] + (3,)
    mid = line_scan(si, (8, 0), (8, 15))
    diag = line_scan(si, (1, 1), (14, 14))
    assert mid.shape[0] >= 2 and diag.shape[0] >= 2
    au_mid = line_scan_element_profile(mid, energy, "Au")
    au_diag = line_scan_element_profile(diag, energy, "Au")
    assert au_mid.size == mid.shape[0]
    assert au_diag.max() > 0
    spec = sum_spectrum(si)
    ints = integrate_windows(spec, energy, ["Au", "Si"], bg_method="velox")
    assert ints["Au"] > 0 and ints["Si"] > 0


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


def test_gui_eds_identify_quant_maps_line_roi(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from openvelox.i18n import Translator
    from openvelox.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    win = MainWindow(Translator("en"))
    win.open_sample()
    assert win.props.tabText(3) == "FFT"
    si = next(ds for ds in win.browser.all_datasets() if ds.kind.name == "SPECTRUM_IMAGE")
    win.open_dataset(si)
    tab = win.current_tab()
    assert tab is not None
    win.props.bg_eds.setCurrentText("snip")
    win.props.map_mode.setCurrentText("window")
    win.props.table.set_selected(["Au", "Si", "Cu", "C"])
    win._on_process("identify", {"elements": ["Au", "Si", "Cu", "C"], "bg_method": "snip"})
    assert win.spectrum._markers
    assert "peak" in win.status.text().lower() or "Identified" in win.status.text()
    win._on_process("quantify", {"elements": ["Au", "Si", "Cu"], "bg_method": "linear"})
    assert win.quant_rows
    assert "weight_percent" in win.quant_rows[0]
    assert win.props.quant_table.columnCount() == 6
    h, w = tab.canvas.image.shape[:2]
    tab.canvas.simulate_tool("line_profile", (1, 1), (h - 2, w - 2))
    assert win._last_line_scan is not None
    win._on_process("line_scan", {"elements": ["Au"], "bg_method": "snip"})
    assert win._last_line_path is not None
    win.tabs.setCurrentWidget(tab)
    tab.canvas.simulate_tool("roi_rect", (2, 2), (w // 2, h // 2))
    assert win._last_roi_spec is not None
    win._on_process("element_maps", {"elements": ["Au", "Si"], "map_mode": "window"})
    assert "Au" in win._last_maps
    win._on_process("overlay", {"elements": ["Au", "Si"]})
    win.close()
