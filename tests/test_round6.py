"""Round 6: expression calculator, Super-X / DF mixing, lazy startup, mmap."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.lazy import LazyArray, mmap_threshold, sum_lazy_si
from openvelox.io.synthetic import make_four_d, make_segmented_detectors, write_synthetic_emd
from openvelox.models import Dataset, DatasetKind
from openvelox.processing.detector_mix import group_detector_datasets, mix_arrays, mix_spectrum_images
from openvelox.processing.image_calc import evaluate_expression, image_calculate
from openvelox.processing.stem4d import virtual_bf
from openvelox.ui.session import save_session


def test_expression_calculator_ops_and_shape() -> None:
    a = np.array([[2.0, 4.0], [6.0, 8.0]])
    b = np.array([[1.0, 1.0], [2.0, 0.0]])
    np.testing.assert_allclose(evaluate_expression("A+B", a, b), a + b)
    np.testing.assert_allclose(evaluate_expression("A-B", a, b), a - b)
    np.testing.assert_allclose(evaluate_expression("A*B", a, b), a * b)
    div = evaluate_expression("A/B", a, b)
    assert np.isnan(div[1, 1])
    np.testing.assert_allclose(div[0, 0], 2.0)
    ratio = evaluate_expression("A/(A+B)", a, np.ones_like(a))
    np.testing.assert_allclose(ratio[0, 0], 2.0 / 3.0)
    np.testing.assert_allclose(evaluate_expression("2*A", a, b), 2 * a)
    np.testing.assert_allclose(evaluate_expression("abs(A-B)", a, b), np.abs(a - b))
    np.testing.assert_allclose(evaluate_expression("sqrt(A)", a, b), np.sqrt(a))
    np.testing.assert_allclose(evaluate_expression("log(A+1)", a), np.log(a + 1))
    np.testing.assert_allclose(image_calculate("add", a, a), 2 * a)
    with pytest.raises(ValueError, match="Shape mismatch"):
        evaluate_expression("A+B", a, np.ones((3, 3)))
    with pytest.raises(ValueError, match="Unknown name"):
        evaluate_expression("A+C", a, b)


def test_superx_and_df_mixing() -> None:
    a = np.ones((4, 4, 8), dtype=np.float64)
    b = 3 * np.ones((4, 4, 8), dtype=np.float64)
    mixed = mix_spectrum_images({"A": a, "B": b}, {"A": 1.0, "B": 1.0})
    np.testing.assert_allclose(mixed, 2.0 * np.ones_like(a))
    segs = make_segmented_detectors(32)
    stacked = mix_arrays(segs, {name: 1.0 for name in segs})
    assert stacked.shape == next(iter(segs.values())).shape
    assert float(stacked.mean()) > 0
    with pytest.raises(ValueError, match="Shape mismatch"):
        mix_arrays({"A": np.ones((2, 2)), "B": np.ones((3, 3))})

    ds_a = Dataset(name="Super-X A", kind=DatasetKind.SPECTRUM_IMAGE, data=a, metadata={"detector_family": "superx"})
    ds_b = Dataset(name="Super-X B", kind=DatasetKind.SPECTRUM_IMAGE, data=b, metadata={"detector_family": "superx"})
    ds_sum = Dataset(name="EDS SI (stream)", kind=DatasetKind.SPECTRUM_IMAGE, data=a + b)
    df = [
        Dataset(name=name, kind=DatasetKind.IMAGE, data=arr)
        for name, arr in segs.items()
    ]
    groups = group_detector_datasets([ds_a, ds_b, ds_sum, *df])
    assert {d.name for d in groups["superx"]} == {"Super-X A", "Super-X B"}
    assert {d.name for d in groups["df4"]} == set(segs)


def test_lazy_4d_virtual_bf_and_mmap(tmp_path: Path, monkeypatch) -> None:
    cube = make_four_d(scan=6, qsize=12, seed=2)
    store = {"n": 0}

    def _slice(item):
        store["n"] += 1
        return cube[item]

    lazy = LazyArray(lambda: cube, cube.shape, dtype=cube.dtype, label="t4d", slicer=_slice)
    img = virtual_bf(lazy, radius=3)
    assert img.shape == (6, 6)
    assert store["n"] >= 1
    assert not lazy.materialized()

    monkeypatch.setenv("OPENVELOX_MMAP_DIR", str(tmp_path / "mmap"))
    monkeypatch.setenv("OPENVELOX_MMAP_ELEMS", "20")
    assert mmap_threshold() == 20
    big = np.arange(48, dtype=np.float64).reshape(6, 8)
    lazy2 = LazyArray(lambda: big, big.shape, dtype=big.dtype, label="mmap-test")
    got = lazy2.materialize()
    np.testing.assert_allclose(np.asarray(got), big)

    lazy_si = LazyArray(lambda: np.ones((5, 4, 7)), (5, 4, 7), dtype=np.float64, slicer=lambda item: np.ones((5, 4, 7))[item])
    spec = sum_lazy_si(lazy_si)
    np.testing.assert_allclose(spec, np.full(7, 20.0))


def test_startup_skips_heavy_optional_modules() -> None:
    code = (
        "import os,sys; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "import openvelox.app, openvelox.ui.splash, openvelox.ui.main_window; "
        "heavy=('scipy','skimage','hyperspy','py4DSTEM','reportlab','pptx'); "
        "print(','.join(m for m in heavy if m in sys.modules))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    env["QT_QPA_PLATFORM"] = "offscreen"
    out = subprocess.check_output([sys.executable, "-c", code], env=env, text=True).strip()
    assert "hyperspy" not in out
    assert "py4DSTEM" not in out
    assert "reportlab" not in out
    assert "pptx" not in out
    assert "scipy" not in out
    assert "skimage" not in out


def test_frozen_roots_onedir_and_package(tmp_path: Path, monkeypatch) -> None:
    from openvelox.paths import frozen_roots, resource_root, window_icon_path

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    (tmp_path / "_internal" / "openvelox" / "resources").mkdir(parents=True)
    (tmp_path / "_internal" / "samples").mkdir(parents=True)
    roots = frozen_roots()
    assert any(p.name == "_internal" for p in roots)
    root = resource_root()
    assert root.name == "_internal"
    icon = window_icon_path()
    assert icon.name == "openvelox.ico"


@pytest.fixture
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


def test_gui_calculator_and_mixer(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

    from openvelox.i18n import Translator
    from openvelox.ui.dialogs import ImageCalculatorDialog
    from openvelox.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(ImageCalculatorDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    win = MainWindow(Translator("en"))
    win.open_sample()
    assert win.props.tabText(3) == "FFT"
    assert win.props.tabText(4) == "EDS"
    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    win.open_dataset(haadf)
    before = win.tabs.count()
    win._on_process("image_calc", {})
    assert win.tabs.count() >= before
    calc_tab = win.current_tab()
    assert calc_tab is not None
    assert calc_tab.dataset.pixel_size_m() == pytest.approx(haadf.pixel_size_m())

    assert len(win.detector_mixer.datasets("superx")) >= 2
    assert len(win.detector_mixer.datasets("df4")) >= 2
    weights = win.detector_mixer.weights()
    weights["superx"] = {name: (2.0 if i == 0 else 0.1) for i, name in enumerate(weights["superx"])}
    weights["df4"] = {name: 1.0 for name in weights["df4"]}
    win._detector_mix_guard = False
    win._on_detector_mix(weights)
    assert win._mixed_si is not None
    assert any(
        isinstance(win.tabs.widget(i), type(calc_tab)) and getattr(win.tabs.widget(i), "dataset", None) is not None
        and win.tabs.widget(i).dataset.name == "DF mix"
        for i in range(win.tabs.count())
    )
    sess = tmp_path / "r6.openvelox.json"
    save_session(sess, win.session_payload())
    win.close()
