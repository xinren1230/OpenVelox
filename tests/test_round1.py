"""Round 1: window icon, thumbnails, acquisition metadata, linked layouts."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.metadata import (
    acquisition_row_count,
    acquisition_sections,
    flatten_velox_metadata,
    format_current,
    format_mrad,
    walk_metadata_tree,
)
from openvelox.io.synthetic import write_synthetic_emd
from openvelox.io.velox_emd import build_velox_metadata, read_emd
from openvelox.models import Dataset, DatasetKind
from openvelox.paths import ensure_window_icon, window_icon_path, write_placeholder_ico
from openvelox.processing.preview import thumbnail_array


def test_window_icon_path_package() -> None:
    path = window_icon_path()
    assert path.name == "openvelox.ico"
    assert path.parent.name == "resources"
    assert path.parent.parent.name == "openvelox"


def test_window_icon_path_frozen(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "meipass"
    ico = root / "openvelox" / "resources" / "openvelox.ico"
    ico.parent.mkdir(parents=True)
    ico.write_bytes(b"real-icon")
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    assert window_icon_path() == ico


def test_ensure_icon_does_not_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "openvelox.ico"
    dest.write_bytes(b"USER-ICON")
    out = ensure_window_icon(dest)
    assert out == dest
    assert dest.read_bytes() == b"USER-ICON"


def test_placeholder_ico_written_only_when_missing(tmp_path: Path) -> None:
    dest = tmp_path / "resources" / "openvelox.ico"
    assert dest.exists() is False
    written = write_placeholder_ico(dest)
    assert written.is_file()
    from PIL import Image

    with Image.open(written) as im:
        assert im.format == "ICO"
        assert im.size[0] >= 16
    again = ensure_window_icon(dest)
    assert again == dest
    with Image.open(dest) as im:
        assert im.format == "ICO"


def test_thumbnail_array_and_sparkline() -> None:
    image = np.linspace(0, 1, 80 * 60, dtype=np.float64).reshape(80, 60)
    thumb = thumbnail_array(image, size=24)
    assert thumb.shape[0] <= 24 or thumb.shape[1] <= 24
    assert thumb.dtype == np.uint8
    spec = np.linspace(0, 10, 128)
    spark = thumbnail_array(spec, size=20)
    assert spark.shape == (20, 20)
    assert spark.max() > 0


def test_flatten_and_acquisition_sections() -> None:
    raw = build_velox_metadata(
        display_name="HAADF",
        detector="HAADF",
        hv_v=200000.0,
        mag=320000.0,
        pixel_m=2.5e-11,
        dwell_s=1e-5,
    )
    flat = flatten_velox_metadata(raw)
    assert flat["high_tension_kv"] == 200
    assert flat["beam_current_a"] == pytest.approx(5e-11)
    assert flat["spot_index"] == 5
    assert flat["operating_mode"] == "STEM"
    assert flat["holder"] == "Single Tilt"
    assert "stage_x_m" in flat
    assert flat["acquisition_datetime"]
    sections = dict(acquisition_sections(flat))
    assert "optics" in sections
    assert "stage" in sections
    assert "all_metadata" in sections
    optics = dict(sections["optics"])
    assert "200" in optics["hv"]
    assert format_current(5e-11).endswith("pA")
    assert "mrad" in format_mrad(0.021)
    assert acquisition_row_count(flat) > 20
    tree = walk_metadata_tree(flat["_raw"])
    assert any(path.endswith("AccelerationVoltage") for path, _ in tree)


def test_synthetic_emd_exposes_full_metadata(tmp_path: Path) -> None:
    path = write_synthetic_emd(tmp_path / "full.emd")
    exp = read_emd(path)
    haadf = next(ds for ds in exp.datasets if ds.name == "HAADF")
    assert haadf.metadata.get("beam_current_a") == pytest.approx(5e-11)
    assert haadf.metadata.get("sample_id") == "OpenVelox demo"
    assert haadf.metadata.get("probe_mode") == "Microprobe"


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


def test_app_sets_window_icon(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from openvelox.app import main

    dest = tmp_path / "openvelox" / "resources" / "openvelox.ico"
    write_placeholder_ico(dest)
    monkeypatch.setattr("openvelox.paths.ensure_window_icon", lambda: dest)
    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    monkeypatch.setattr("openvelox.ui.main_window.MainWindow.show", lambda self: None)
    assert main([]) == 0
    icon = QApplication.instance().windowIcon()
    assert isinstance(icon, QIcon)
    assert icon.isNull() is False


def test_browser_thumbnails_filter_and_metadata_panel(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from openvelox.i18n import Translator
    from openvelox.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    win = MainWindow(Translator("en"))
    exp = win.open_sample()
    assert exp.datasets
    thumbs = 0
    for ds_item in _dataset_items(win.browser.tree):
        if not ds_item.icon(0).isNull():
            thumbs += 1
    assert thumbs >= 4
    before = win.tabs.count()
    first = _dataset_items(win.browser.tree)[0]
    win.browser._on_click(first, 0)
    assert win.tabs.count() == before
    assert win.props.metadata_pairs()
    assert any("kV" in value or "200" in value for _k, value in win.props.metadata_pairs())
    win.browser.filter.setText("HAADF")
    visible = [it for it in _dataset_items(win.browser.tree) if not it.isHidden()]
    assert visible
    assert all("haadf" in it.text(0).lower() for it in visible)
    win.browser.filter.setText("zzz-no-such")
    hidden_ds = [it for it in _dataset_items(win.browser.tree) if it.isHidden()]
    assert hidden_ds
    win.browser.filter.setText("")
    win.browser._on_double(first, 0)
    assert win.tabs.count() >= before
    win.props.meta_filter.setText("optics")
    win.close()


def test_multi_panel_linked_views(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from openvelox.i18n import Translator
    from openvelox.ui.main_window import ImageTab, MainWindow
    from openvelox.ui.workspace import mirror_view

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    win = MainWindow(Translator("en"))
    win.open_sample()
    view = win.apply_layout("2x2")
    assert view is not None
    assert view.panel_count() == 4
    assert len(view.panels()) >= 2
    win.apply_layout("1x2")
    assert win.tabs.currentWidget().panel_count() == 2
    win._toggle_sync(True)
    panels = win.tabs.currentWidget().panels()
    src, dst = panels[0], panels[1]
    src.canvas.vb.setRange(xRange=(10, 40), yRange=(12, 42), padding=0)
    win.tabs.currentWidget()._sync_from(src)
    xr, yr = dst.canvas.view_range()
    sx, sy = src.canvas.view_range()
    assert xr[1] > xr[0]
    assert xr[0] == pytest.approx(sx[0], abs=1e-3)
    assert xr[1] == pytest.approx(sx[1], abs=1e-3)
    assert yr[0] == pytest.approx(sy[0], abs=1e-3)
    assert yr[1] == pytest.approx(sy[1], abs=1e-3)
    other = Dataset(name="tiny-cal", kind=DatasetKind.IMAGE, data=np.ones((32, 32)), metadata={"pixel_size_m": 5e-11})
    other_tab = ImageTab(other)
    other_tab.canvas.pixel_m = 5e-11
    src.canvas.pixel_m = 2.5e-11
    src.canvas.vb.setRange(xRange=(0, 20), yRange=(0, 20), padding=0)
    mirror_view(src.canvas, other_tab.canvas)
    sx = src.canvas.view_range()[0]
    ox = other_tab.canvas.view_range()[0]
    scale = (src.canvas.pixel_m or 1.0) / (other_tab.canvas.pixel_m or 1.0)
    assert ox[0] == pytest.approx(sx[0] * scale, rel=0.15, abs=1.5)
    assert ox[1] == pytest.approx(sx[1] * scale, rel=0.15, abs=1.5)
    win.apply_layout("1x1")
    win.close()


def _dataset_items(tree):
    from openvelox.models import Dataset
    from PySide6.QtCore import Qt

    items = []

    def walk(item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Dataset):
            items.append(item)
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return items
