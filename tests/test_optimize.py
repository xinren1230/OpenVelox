"""Tests for the 0.3 performance / UI / export / filter pass."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_NO_DIALOG", "1")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.lazy import LazyArray, h5_slicer
from openvelox.io.metadata import format_coord
from openvelox.io.synthetic import write_synthetic_emd
from openvelox.io.velox_emd import read_emd
from openvelox.io.writers import batch_export_images, export_image
from openvelox.models import Dataset, DatasetKind
from openvelox.processing.cache import cache_clear
from openvelox.processing.filters import highpass_filter, sobel_filter, unsharp_mask
from openvelox.processing.measure import line_profile, profile_stats
from openvelox.processing.preview import cached_preview, downsample2d, preview_sum_si, preview_virtual_bf, stride_for
from openvelox.ui.prefs import add_recent, clear_recent, load_prefs, recent_files, save_prefs


def test_stride_and_downsample() -> None:
    assert stride_for((64, 64), 128) == 1
    assert stride_for((2048, 1024), 512) >= 4
    image = np.arange(200 * 200, dtype=np.float64).reshape(200, 200)
    small = downsample2d(image, 50)
    assert small.shape[0] < image.shape[0]
    assert downsample2d(image, 400).shape == image.shape


def test_preview_si_and_4d() -> None:
    si = np.ones((40, 40, 80), dtype=np.float64)
    si[10, 12, :] = 5
    preview = preview_sum_si(si, max_side=20, energy_step=4)
    assert preview.ndim == 2
    assert preview.shape[0] <= 20
    cube = np.zeros((16, 16, 20, 20), dtype=np.float64)
    cube[:, :, 10, 10] = 3
    bf = preview_virtual_bf(cube, max_side=8)
    assert bf.shape[0] <= 8
    assert bf.max() > 0


def test_cached_preview() -> None:
    cache_clear()
    n = {"calls": 0}

    def factory() -> np.ndarray:
        n["calls"] += 1
        return np.ones((4, 4))

    a = cached_preview("k1", factory)
    b = cached_preview("k1", factory)
    assert n["calls"] == 1
    np.testing.assert_array_equal(a, b)


def test_dataset_preview_and_is_large() -> None:
    small = Dataset(name="s", kind=DatasetKind.IMAGE, data=np.ones((16, 16)))
    assert small.is_large() is False
    huge = Dataset(name="h", kind=DatasetKind.SPECTRUM_IMAGE, data=np.ones((8, 8, 4096)))
    assert huge.is_large() is True
    stack = np.stack([np.full((12, 10), i) for i in range(5)])
    ds = Dataset(name="st", kind=DatasetKind.STACK, data=stack)
    frame = ds.image2d(index=3, preview=False)
    assert frame.shape == (12, 10)
    assert frame[0, 0] == 3
    prev = huge.image2d(preview=True, max_side=8)
    assert prev.ndim == 2


def test_lazy_slicer_avoids_full_load(tmp_path: Path) -> None:
    import h5py

    path = tmp_path / "cube.h5"
    cube = np.arange(4 * 6 * 8, dtype=np.float32).reshape(4, 6, 8)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("Data", data=cube)

    loaded = {"n": 0}

    def loader() -> np.ndarray:
        loaded["n"] += 1
        return cube

    lazy = LazyArray(loader, cube.shape, dtype=np.float32, slicer=h5_slicer(path, "Data"))
    assert lazy.has_slicer()
    sl = lazy[1]
    np.testing.assert_array_equal(sl, cube[1])
    assert loaded["n"] == 0
    assert lazy.materialized() is False
    full = lazy.materialize()
    assert loaded["n"] == 1
    np.testing.assert_array_equal(full, cube)


def test_emd_stack_frame_slicer(tmp_path: Path) -> None:
    path = write_synthetic_emd(tmp_path / "demo.emd")
    exp = read_emd(path)
    stack = next(ds for ds in exp.datasets if ds.kind is DatasetKind.STACK)
    assert stack.data.materialized() is False
    frame0 = stack.image2d(index=0, preview=False)
    frame1 = stack.image2d(index=min(1, stack.n_frames() - 1), preview=False)
    assert frame0.shape == frame1.shape
    assert frame0.ndim == 2


def test_new_filters_and_profile_stats() -> None:
    image = np.zeros((32, 32), dtype=np.float64)
    image[8:24, 8:24] = 4
    sharp = unsharp_mask(image, sigma=1.0, amount=1.0)
    assert sharp[16, 16] >= image[16, 16]
    edges = sobel_filter(image)
    assert edges[8, 16] > edges[16, 16]
    hp = highpass_filter(image, sigma=4)
    assert hp.shape == image.shape
    empty_d, empty_p = line_profile(np.zeros((0, 0)), (0, 0), (1, 1))
    assert empty_d.size and empty_p.size
    dist, prof = line_profile(image, (16, 0), (16, 31), linewidth=3)
    stats = profile_stats(dist, prof)
    assert stats["max"] >= 3
    assert stats["fwhm"] > 0
    assert stats["length"] > 0
    assert profile_stats(np.array([]), np.array([]))["fwhm"] == 0


def test_annotated_and_batch_export(tmp_path: Path) -> None:
    image = np.linspace(0, 1, 48 * 48, dtype=np.float64).reshape(48, 48)
    dest = tmp_path / "ann.png"
    export_image(
        dest,
        image,
        pixel_m=2.5e-11,
        title="HAADF",
        annotations=[
            {"kind": "line", "p0": (4, 4), "p1": (20, 30)},
            {"kind": "text", "x": 6, "y": 8, "text": "10 nm"},
            {"kind": "rect", "box": (2, 2, 10, 10)},
        ],
    )
    assert dest.is_file() and dest.stat().st_size > 0
    tif = tmp_path / "ann.tif"
    export_image(tif, image, pixel_m=2.5e-11, title="HAADF")
    assert tif.is_file()
    written = batch_export_images(
        tmp_path / "batch",
        [("map A", image, {"pixel_m": 1e-9, "title": "A"}), ("map/B", image, {})],
    )
    assert len(written) == 2
    assert all(p.is_file() for p in written)


def test_prefs_recent_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENVELOX_DATA_DIR", str(tmp_path / "data"))
    a = tmp_path / "a.emd"
    b = tmp_path / "b.emd"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    add_recent(a)
    add_recent(b)
    rec = recent_files()
    assert rec[0] == str(b)
    assert str(a) in rec
    save_prefs({"geometry": "00"})
    assert load_prefs().get("geometry") == "00"
    clear_recent()
    assert recent_files() == []


def test_format_coord() -> None:
    assert format_coord(12, None) == "12"
    text = format_coord(10, 1e-10)
    assert text.startswith("10")
    assert "nm" in text or "pm" in text


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


def test_icons_and_prefs_gui(qapp, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENVELOX_DATA_DIR", str(tmp_path / "data"))
    from openvelox.ui.icons import icon_for

    for key in ("open", "fit", "fft", "pointer", "line_profile", "roi_rect"):
        icon = icon_for(key)
        assert not icon.isNull()
    assert icon_for("missing").isNull()


def test_main_window_optimize_features(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from openvelox.crashlog import install
    from openvelox.i18n import Translator
    from openvelox.ui.main_window import MainWindow

    install()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENVELOX_DATA_DIR", str(tmp_path / "ovdata"))
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "out")))
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "shot.png"), "")),
    )

    win = MainWindow(Translator("en"))
    exp = win.open_sample()
    assert exp.datasets
    assert win._recent_menu is not None
    assert recent_files()

    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    tab = win.open_dataset(haadf)
    tab.canvas.simulate_tool("line_profile", (2, 2), (20, 8))
    assert "mean" in win.status.text().lower() or "Profile" in win.status.text()
    win.props.profile_width.setValue(5)
    assert tab.canvas.profile_linewidth == 5

    tab.canvas.pixelPicked.emit(4, 6, 1.5)
    assert "x=" in win.coord.text()
    assert "nm" in win.coord.text() or "I=" in win.coord.text()

    win._on_process("unsharp", {"sigma": 1.0})
    win._on_process("sobel", {})
    win._on_process("highpass", {"bg_sigma": 4})

    win.invoke_action("export_image")
    assert (tmp_path / "shot.png").is_file()
    win.invoke_action("batch_export")
    assert any((tmp_path / "out").glob("*.png"))

    extra = write_synthetic_emd(tmp_path / "drop.emd")
    win.open_dropped_paths([str(extra)])
    assert any(Path(p).name == "drop.emd" for p in win._open_paths)

    payload = win.chrome_payload()
    assert payload.get("geometry") and payload.get("docks")
    win.save_chrome()
    assert load_prefs().get("docks")
    win.reset_layout()
    assert win.restore_chrome(payload)

    si = next(ds for ds in win.browser.all_datasets() if ds.kind is DatasetKind.SPECTRUM_IMAGE)
    win.open_dataset(si)
    win.props.table.set_selected(["Au", "Si"])
    win.props.refresh_selected()
    assert "Au" in win.props.sel_count.text()
    win._on_process("quantify", {"elements": ["Au", "Si"], "absorption": False})
    assert win.quant_rows
    assert "at.%" in win.status.text() or "Quant" in win.status.text()

    win.invoke_action("clear_recent")
    win.invoke_action("close_tab")
    win.close()


def test_image_tab_does_not_materialize_stack(qapp, tmp_path, monkeypatch) -> None:
    from openvelox.i18n import Translator
    from openvelox.ui.main_window import ImageTab, MainWindow

    monkeypatch.chdir(tmp_path)
    win = MainWindow(Translator("en"))
    win.open_sample()
    stack = next(ds for ds in win.browser.all_datasets() if ds.kind is DatasetKind.STACK)
    assert stack.data.materialized() is False
    tab = ImageTab(stack)
    assert tab.canvas._n_frames > 1
    assert not tab.canvas.frame_row.isHidden()
    tab.canvas.set_stack_frame(1)
    assert tab.canvas.image.ndim == 2
    assert stack.data.materialized() is False
    win.close()
