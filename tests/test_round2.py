"""Round 2: FFT masks/IFFT, DCFI, background models, contrast / LUTs."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")

from openvelox.io.synthetic import make_drift_stack, make_haadf_lattice
from openvelox.processing.display import apply_display, load_lut, lut_names, register_lut
from openvelox.processing.drift import align_and_sum, dcfi
from openvelox.processing.fft import (
    apply_mask,
    feather_mask,
    fft2d,
    ifft2d,
    make_mask,
    mask_overlay_rgba,
    reconstruct,
)
from openvelox.processing.filters import plane_background, rolling_ball_background, subtract_background


def test_soft_mask_ifft_and_overlay() -> None:
    rng = np.random.default_rng(2)
    image = rng.normal(size=(48, 48))
    spec = fft2d(image)
    hard = make_mask(image.shape, "circle", radius=8)
    soft = feather_mask(hard, 2.0)
    assert soft.min() >= 0 and soft.max() <= 1
    assert soft[24, 24] > soft[0, 0]
    rec = reconstruct(spec, kind="circle", radius=10, soft=1.5)
    assert rec.shape == image.shape
    rgba = mask_overlay_rgba(hard)
    assert rgba.shape == image.shape + (4,)
    assert rgba[..., 3].max() > 0
    band = reconstruct(spec, kind="annulus", inner=2, outer=12, invert=True)
    assert band.shape == image.shape
    masked = apply_mask(spec, soft)
    assert masked.shape == spec.shape


def test_dcfi_aligns_and_crops() -> None:
    haadf = make_haadf_lattice(size=64, spacing=8, seed=3)
    stack = make_drift_stack(haadf, n_frames=6, seed=4)
    result = dcfi(stack, reference="first", reduce="mean", crop=True)
    assert result.aligned.shape == stack.shape
    assert result.integrated.ndim == 2
    assert result.used.all()
    assert result.shifts[0].tolist() == [0.0, 0.0]
    prev = dcfi(stack, reference="previous", reduce="sum", crop=False, highpass_sigma=1.0)
    assert prev.integrated.shape == stack.shape[1:]
    rejected = dcfi(stack, max_shift=0.01, crop=False)
    assert rejected.used[0]
    aligned, summed, shifts = align_and_sum(stack)
    assert aligned.shape == stack.shape
    assert summed.shape == stack.shape[1:]
    assert np.linalg.norm(shifts[0]) == 0


def test_background_models() -> None:
    yy, xx = np.mgrid[0:32, 0:32]
    image = 3.0 + 0.08 * xx + 0.05 * yy
    image[12:18, 12:18] += 4.0
    plane = subtract_background(image, "plane")
    assert plane[15, 15] > plane[0, 0]
    assert abs(plane_background(image)[0, 0] - 3.0) < 1.5
    ball = rolling_ball_background(image, radius=6)
    assert ball.shape == image.shape
    const = subtract_background(image, "constant", percentile=0)
    assert const.min() == pytest.approx(0.0, abs=1e-6)
    avg = subtract_background(image, "average", sigma=8)
    assert avg.shape == image.shape


def test_luts_invert_and_file(tmp_path: Path) -> None:
    image = np.linspace(0, 1, 16 * 16).reshape(16, 16)
    rgb = apply_display(image, colormap="fire", invert=False)
    inv = apply_display(image, colormap="fire", invert=True)
    assert rgb.shape == (16, 16, 3)
    assert not np.array_equal(rgb, inv)
    assert "gray_inv" in lut_names()
    assert "ice" in lut_names()
    csv = tmp_path / "custom.csv"
    csv.write_text("0,0,0\n128,64,32\n255,255,255\n", encoding="utf-8")
    lut = load_lut(csv)
    register_lut("custom_r2", lut)
    assert "custom_r2" in lut_names()
    painted = apply_display(image, colormap="custom_r2")
    assert painted[0, 0, 0] <= painted[-1, -1, 0]
    raw = bytes(range(256)) + bytes(range(256)) + bytes(reversed(range(256)))
    bin_lut = tmp_path / "ij.lut"
    bin_lut.write_bytes(raw)
    loaded = load_lut(bin_lut)
    assert loaded.shape == (256, 3)


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


def test_gui_fft_mask_dcfi_bg_lut(qapp, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from openvelox.i18n import Translator
    from openvelox.ui.main_window import MainWindow

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(QMessageBox, "critical", classmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    win = MainWindow(Translator("en"))
    win.open_sample()
    haadf = next(ds for ds in win.browser.all_datasets() if ds.name == "HAADF")
    win.open_dataset(haadf)
    win._on_process("fft", {})
    fft_tab = next(win.tabs.widget(i) for i in range(win.tabs.count()) if getattr(win.tabs.widget(i), "is_fft", False))
    win.tabs.setCurrentWidget(fft_tab)
    params = win.props.fft_params()
    params["soft"] = 1.5
    win._update_fft_mask(params, tab=fft_tab)
    assert fft_tab.canvas._mask_item is not None
    win._on_process("ifft", {**params, "kind": "annulus", "inner": 3, "outer": 16})
    win._on_process("place_fft_mask", params)
    win.props.live_ifft.setChecked(False)
    win.open_dataset(haadf)
    win._on_process("bg_sub", {"method": "plane"})
    win._on_process("bg_sub", {"method": "rolling_ball", "radius": 8})
    win._on_process("bg_sub", {"method": "constant", "percentile": 2})
    win._on_process("dcfi", {"reference": "first", "reduce": "mean", "crop": True})
    win.props.invert_lut.setChecked(True)
    win.props.cmap.setCurrentText("fire")
    win.props.s_gamma.setValue(80)
    assert win.current_tab().canvas.invert is True
    csv = tmp_path / "panel.csv"
    csv.write_text("0,0,0\n255,128,0\n", encoding="utf-8")
    from openvelox.processing.display import load_lut, register_lut

    register_lut("panel_lut", load_lut(csv))
    win.props.add_lut_name("panel_lut")
    win.props.cmap.setCurrentText("panel_lut")
    win.close()
