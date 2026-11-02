"""Round 3: measurements, FFT d-spacing, histogram, scale bar, overlay export."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.writers import export_image, export_overlay
from openvelox.processing.measure import (
    area_m2,
    ellipse_mask,
    fft_d_spacing,
    format_area,
    intensity_histogram,
    polygon_mask,
    rect_mask,
    roi_stats,
)
from openvelox.processing.scalebar import ScaleBarStyle, bar_pixels, choose_bar, nice_length_m, parse_color


def test_polygon_area_and_histogram() -> None:
    image = np.zeros((32, 32), dtype=np.float64)
    image[8:20, 6:18] = 5.0
    mask = polygon_mask(image.shape, [(7, 9), (16, 9), (16, 18), (7, 18)])
    assert mask[10:16, 8:14].all()
    stats = roi_stats(image, mask)
    assert stats["mean"] == pytest.approx(5.0)
    area = area_m2(stats["n"], 1e-9)
    assert area == pytest.approx(stats["n"] * 1e-18)
    assert "nm²" in format_area(area)
    assert format_area(None) == "—"
    assert format_area(0) == "—"
    rect = rect_mask(image.shape, 6, 8, 18, 20)
    assert rect[10:16, 8:14].all()
    assert rect.sum() >= mask.sum()
    ell = ellipse_mask(image.shape, 16, 16, 6, 4)
    assert ell[16, 16] and not ell[0, 0]
    edges, counts = intensity_histogram(image, mask, bins=16)
    assert counts.sum() == stats["n"]
    assert edges.size == counts.size
    empty_x, empty_y = intensity_histogram(np.full((3, 3), np.nan))
    assert empty_x.size == 0 and empty_y.size == 0
    tiny = polygon_mask((4, 4), [(0, 0), (1, 0)])
    assert tiny.sum() == 0


def test_fft_d_spacing_center_and_pair() -> None:
    shape = (64, 64)
    px = 1e-10
    center = fft_d_spacing((32.0, 32.0), (32.0, 48.0), shape, px)
    assert center["mode"] == "center"
    assert center["d_spacing_m"] == pytest.approx(4e-10)
    pair = fft_d_spacing((16.0, 32.0), (48.0, 32.0), shape, px)
    assert pair["mode"] == "pair"
    assert pair["d_spacing_m"] == pytest.approx(4e-10)
    bad = fft_d_spacing((10.0, 10.0), (10.0, 10.0), shape, px)
    assert bad["d_spacing_m"] == 0.0
    none = fft_d_spacing((0.0, 0.0), (8.0, 0.0), shape, 0.0)
    assert none["frequency_per_m"] == 0.0


def test_scale_bar_style_and_export(tmp_path: Path) -> None:
    style = ScaleBarStyle.from_mapping(
        {"color": "#00A3E0", "length_m": 5e-9, "font_size": 12, "position": "top_right", "thickness": 6, "visible": True}
    )
    assert style.as_dict()["color"] == "#00A3E0"
    assert choose_bar(1e-10, 256, style)[0] == pytest.approx(5e-9)
    assert bar_pixels(1e-10, 5e-9) == 50
    auto = choose_bar(1e-9, 200, ScaleBarStyle())
    assert auto[0] > 0 and auto[2] >= 8
    assert nice_length_m(1e-9, 0) > 0
    assert parse_color("#112233") == (0x11, 0x22, 0x33)
    assert parse_color((9, 8, 7)) == (9, 8, 7)
    assert parse_color("nope") == (255, 255, 255)
    hidden = ScaleBarStyle.from_mapping({"length_m": -1, "visible": False})
    assert hidden.length_m is None
    assert hidden.visible is False

    image = np.linspace(0, 1, 48 * 64, dtype=np.float64).reshape(48, 64)
    dest = tmp_path / "overlay.png"
    export_overlay(
        dest,
        image,
        pixel_m=2.5e-11,
        scale_bar_style=style,
        annotations=[
            {"kind": "line", "p0": (4, 4), "p1": (20, 40), "color": "#F4C542"},
            {"kind": "rect", "box": (2, 2, 12, 10)},
            {"kind": "ellipse", "box": (16, 8, 30, 22), "color": "#7CDB6A"},
            {"kind": "polygon", "points": [(8, 28), (20, 30), (12, 40)]},
            {"kind": "angle", "p0": (40, 8), "vertex": (40, 20), "p1": (30, 20)},
            {"kind": "text", "x": 6, "y": 8, "text": "d=0.4 nm"},
        ],
        title="HAADF",
    )
    assert dest.is_file() and dest.stat().st_size > 0
    with Image.open(dest) as im:
        rgb = np.asarray(im.convert("RGB"))
    assert rgb.shape[2] == 3
    # Locked cyan bar is drawn at the top-right.
    assert rgb[24:34, -40:].reshape(-1, 3).max() > 0

    black = tmp_path / "black.png"
    export_image(
        black,
        np.full((32, 80), 0.85),
        pixel_m=1e-9,
        vmin=0.0,
        vmax=1.0,
        scale_bar_style=ScaleBarStyle(color="#000000", position="bottom_left", thickness=8, length_m=2e-8),
    )
    with Image.open(black) as im:
        arr = np.asarray(im.convert("RGB"))
    assert arr[-16:, :40].min() == 0
    assert arr[8, 40].min() > 200


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


def test_gui_measure_dspacing_scalebar_overlay(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from openvelox.i18n import Translator
    from openvelox.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "overlay.png"), "")))
    win = MainWindow(Translator("en"))
    win.open_sample()
    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    win.open_dataset(haadf)
    tab = win.current_tab()
    assert tab is not None
    assert win.props.tabText(3) == "FFT"
    h, w = tab.canvas.image.shape
    tab.canvas.simulate_tool("distance", (2, 2), (w - 4, 4))
    assert any(item.get("kind") == "line" for item in tab.canvas.collect_annotations())
    tab.canvas.simulate_tool("angle", (2, 2), (w // 2, h // 2), (w - 4, 4))
    tab.canvas.simulate_tool("roi_rect", (4, 4), (w // 3, h // 3))
    assert "area" in win.status.text()
    tab.canvas.simulate_tool("roi_polygon", (6, 6), (w // 2, 8), (w // 3, h // 2))
    mask = tab.canvas.roi_mask()
    assert mask is not None and mask.sum() > 10
    x, y = win.props.roi_hist_curve.getData()
    assert len(y) > 0
    win._on_process("fft", {})
    fft_tab = next(win.tabs.widget(i) for i in range(win.tabs.count()) if getattr(win.tabs.widget(i), "is_fft", False))
    win.tabs.setCurrentWidget(fft_tab)
    cy, cx = fft_tab.canvas.image.shape[0] / 2.0, fft_tab.canvas.image.shape[1] / 2.0
    fft_tab.canvas.simulate_tool("d_spacing", (cx, cy), (cx + 16, cy))
    assert "d-spacing" in win.status.text() or "d=" in " ".join(a.get("text", "") for a in fft_tab.canvas.collect_annotations())
    win.tabs.setCurrentWidget(tab)
    win.props.sb_visible.setChecked(True)
    win.props.sb_color.setCurrentIndex(2)
    win.props.sb_position.setCurrentIndex(1)
    win.props.sb_font.setValue(14)
    win.props.sb_thick.setValue(7)
    win.props.sb_length.setCurrentIndex(3)
    style = tab.canvas.scale_bar_style
    assert style.thickness == 7
    assert style.position == "bottom_right"
    assert style.color == "#00A3E0"
    win.invoke_action("export_overlay")
    assert (tmp_path / "overlay.png").is_file()
    win.close()
