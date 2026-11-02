"""Exhaustive GUI smoke: every menu, toolbar, panel control, and edge case."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_NO_DIALOG", "1")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

pytest.importorskip("PySide6")

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from openvelox.crashlog import install
from openvelox.i18n import Translator
from openvelox.io.synthetic import write_synthetic_emd
from openvelox.io.tiff_io import write_tiff
from openvelox.models import Dataset, DatasetKind
from openvelox.theme import STYLESHEET, apply_pyqtgraph
from openvelox.ui.dialogs import ImageCalculatorDialog
from openvelox.ui.main_window import ImageTab, MainWindow


@pytest.fixture(scope="module")
def qapp():
    apply_pyqtgraph()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    app.setStyleSheet(STYLESHEET)
    install()
    return app


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "about", classmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "information", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    saves = {"n": 0}

    def _save(*_a, **_k):
        saves["n"] += 1
        suffix = "png" if "image" in str(_a[1:2]).lower() or saves["n"] == 1 else "csv"
        return str(tmp_path / f"export_{saves['n']}.{suffix}"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_save))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "batch")))
    monkeypatch.setattr(ImageCalculatorDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    window = MainWindow(Translator("en"))
    exp = window.open_sample()
    assert exp.datasets
    yield window
    window.close()


def _image_tabs(window: MainWindow) -> list[ImageTab]:
    return [window.tabs.widget(i) for i in range(window.tabs.count()) if isinstance(window.tabs.widget(i), ImageTab)]


def test_every_named_action_trigger(win) -> None:
    """QAction.triggered(bool) used to TypeError and kill the windowed exe."""
    skip = {"quit"}
    for key, act in list(win._actions.items()):
        if key in skip:
            continue
        act.trigger()
    win.invoke_action("fit")
    win.invoke_action("fft")
    win.invoke_action("about")


def test_open_every_sample_dataset(win) -> None:
    names = []
    for ds in win.browser.all_datasets():
        tab = win.open_dataset(ds)
        assert tab is not None
        names.append(ds.kind)
        if ds.kind is DatasetKind.STACK:
            tab.canvas.set_stack_frame(min(1, ds.n_frames() - 1))
    assert DatasetKind.IMAGE in names
    assert DatasetKind.SPECTRUM_IMAGE in names
    assert DatasetKind.FOUR_D in names
    assert DatasetKind.STACK in names


def test_measurement_tools(win) -> None:
    tab = win.current_tab() or _image_tabs(win)[0]
    win.tabs.setCurrentWidget(tab)
    h, w = tab.canvas.image.shape
    tab.canvas.simulate_tool("line_profile", (1, 1), (w - 2, h - 2))
    tab.canvas.simulate_tool("distance", (2, 2), (w - 3, 4))
    tab.canvas.simulate_tool("angle", (2, 2), (w // 2, h // 2), (w - 3, 3))
    tab.canvas.simulate_tool("roi_rect", (2, 2), (w // 2, h // 2))
    tab.canvas.simulate_tool("roi_ellipse", (3, 3), (w // 2, h // 2))
    tab.canvas.simulate_tool("roi_polygon", (2, 2), (w // 2, 3), (4, h // 2))
    tab.canvas.simulate_tool("d_spacing", (2, 2), (w - 3, 4))
    win._clear_overlays()
    win._set_tool("pointer")


def test_filters_fft_calculator(win) -> None:
    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    win.open_dataset(haadf)
    for name, params in (
        ("gaussian", {"sigma": 1.2}),
        ("median", {"size": 3}),
        ("wiener", {"size": 5}),
        ("bg_sub", {"bg_sigma": 8}),
        ("fft", {}),
        ("ifft", {"kind": "circle", "radius": 12}),
        ("ifft", {"kind": "annulus", "inner": 4, "outer": 20}),
        ("ifft", {"kind": "rect", "radius": 10, "invert": True}),
    ):
        win._on_process(name, params)
    win._on_process("image_calc", {})
    win._auto_contrast()
    win.props.cmap.setCurrentText("thermal")
    win.props.s_bright.setValue(120)
    win.props.s_contrast.setValue(80)
    win.props.s_gamma.setValue(90)


def test_eds_full_pipeline(win) -> None:
    si = next(ds for ds in win.browser.all_datasets() if ds.kind is DatasetKind.SPECTRUM_IMAGE)
    win.open_dataset(si)
    win.props.table.set_selected(["Au", "Si", "Cu", "C"])
    for name in ("identify", "element_maps", "overlay", "quantify", "pca", "line_scan", "gauss_maps"):
        win._on_process(name, {"elements": ["Au", "Si", "Cu"], "absorption": True, "thickness_nm": 40})
    win.props.table._toggle("Fe", True)
    if win.mixer._sliders:
        next(iter(win.mixer._sliders.values())).setValue(50)
    tab = next((t for t in _image_tabs(win) if t.dataset.kind is DatasetKind.SPECTRUM_IMAGE), None)
    assert tab is not None
    tab.canvas.simulate_tool("roi_rect", (1, 1), (6, 6))


def test_dpc_4d_atoms_drift(win) -> None:
    win._on_process("dpc", {})
    win._on_process("virtual_bf", {"radius": 4})
    win._on_process("virtual_adf", {"inner": 5, "outer": 10})
    win._on_process("virtual_abf", {"abf_inner": 1.5, "abf_outer": 3.0})
    win._on_process("com", {})
    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    win.open_dataset(haadf)
    win._on_process("atoms", {"sigma": 1.1, "min_distance": 5})
    win._on_process("drift", {})


def test_undo_redo_session_exports_language_tile(win, tmp_path) -> None:
    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    win.open_dataset(haadf)
    win._on_process("gaussian", {"sigma": 1.0})
    win.invoke_action("undo")
    win.invoke_action("redo")
    sess = tmp_path / "s.openvelox.json"
    from openvelox.ui.session import save_session

    save_session(sess, {"files": win._open_paths, "language": "zh", "k_factors": {"Au": 1.7}})
    win.load_session_file(sess)
    win.invoke_action("export_image")
    win.invoke_action("export_spectrum")
    win.invoke_action("export_map")
    win.invoke_action("export_quant")
    win.invoke_action("export_roi")
    win.invoke_action("export_linescan")
    win.tr_.set_language("zh")
    assert "透射" in win.windowTitle()
    win.tr_.set_language("en")
    win.invoke_action("sync_views")
    win.invoke_action("tile")


def test_close_tabs_then_tools_and_invalid_files(win, tmp_path) -> None:
    while win.tabs.count():
        win._close_tab(0)
    win.invoke_action("fft")
    win.invoke_action("fit")
    win._set_tool("distance")
    win._clear_overlays()
    win._on_process("gaussian", {"sigma": 1.0})
    win._on_process("atoms", {})
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    exp = win.load_path(empty)
    assert exp.datasets == []
    bogus = tmp_path / "not-an.emd"
    bogus.write_bytes(b"not hdf5")
    exp2 = win.load_path(bogus)
    assert exp2.datasets == []


def test_tiny_and_nan_images(win) -> None:
    nan = Dataset(name="NaNs", kind=DatasetKind.IMAGE, data=np.full((6, 6), np.nan))
    tiny = Dataset(name="tiny", kind=DatasetKind.IMAGE, data=np.zeros((1, 1)))
    empty = Dataset(name="empty", kind=DatasetKind.IMAGE, data=np.zeros((0, 0)))
    for ds in (nan, tiny, empty):
        tab = win.open_dataset(ds)
        tab.canvas.simulate_tool("line_profile", (0, 0), (0, 0))
        win._on_process("fft", {})
        win._on_process("gaussian", {"sigma": 0.5})
        win._on_process("atoms", {"min_distance": 2})
        win.props.set_histogram(tab.canvas.image)


def test_public_velox_emd_in_gui(win, public_si_emd, public_stack_emd, public_dpc_emd) -> None:
    for path in (public_si_emd, public_stack_emd, public_dpc_emd):
        exp = win.load_path(path)
        assert exp.datasets
        win.open_dataset(exp.datasets[0])
        win.invoke_action("fit")
    si = next((ds for ds in win.browser.all_datasets() if ds.kind is DatasetKind.SPECTRUM_IMAGE), None)
    if si is not None:
        win.open_dataset(si)
        win._on_process("identify", {"elements": ["Si", "O", "C"]})
