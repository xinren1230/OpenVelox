"""FFT / inverse FFT with circular, annular and rectangular masks."""

from __future__ import annotations

from typing import Literal

import numpy as np

MaskKind = Literal["circle", "annulus", "rect"]


def fft2d(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2 or arr.size == 0:
        arr = np.zeros((8, 8), dtype=np.float64)
    arr = np.nan_to_num(arr, nan=0.0)
    return np.fft.fftshift(np.fft.fft2(arr))


def ifft2d(spectrum: np.ndarray) -> np.ndarray:
    rec = np.fft.ifft2(np.fft.ifftshift(np.asarray(spectrum)))
    return np.real(rec)


def power_spectrum(image: np.ndarray, log: bool = True, eps: float = 1e-12) -> np.ndarray:
    spec = fft2d(image)
    power = np.abs(spec) ** 2
    if log:
        return np.log10(power + eps)
    return power


def make_mask(
    shape: tuple[int, int],
    kind: MaskKind = "circle",
    *,
    center: tuple[float, float] | None = None,
    radius: float | None = None,
    inner: float = 0.0,
    outer: float | None = None,
    width: float | None = None,
    height: float | None = None,
    invert: bool = False,
) -> np.ndarray:
    h, w = shape
    cy, cx = center if center is not None else (h / 2.0, w / 2.0)
    yy, xx = np.ogrid[:h, :w]
    if kind == "circle":
        r = radius if radius is not None else min(h, w) / 6.0
        mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= r**2
    elif kind == "annulus":
        r_out = outer if outer is not None else (radius if radius is not None else min(h, w) / 4.0)
        r_in = inner
        rr = (yy - cy) ** 2 + (xx - cx) ** 2
        mask = (rr >= r_in**2) & (rr <= r_out**2)
    elif kind == "rect":
        rw = width if width is not None else w / 4.0
        rh = height if height is not None else h / 4.0
        mask = (np.abs(yy - cy) <= rh / 2.0) & (np.abs(xx - cx) <= rw / 2.0)
    else:
        raise ValueError(f"Unknown mask kind {kind}")
    if invert:
        mask = ~mask
    return mask.astype(bool)


def feather_mask(mask: np.ndarray, soft: float = 0.0) -> np.ndarray:
    """Boolean or 0–1 mask with an optional Gaussian soft edge (Velox-style)."""
    arr = np.asarray(mask, dtype=np.float64)
    if arr.ndim != 2:
        arr = np.atleast_2d(arr)
    arr = np.clip(arr, 0.0, 1.0)
    sigma = float(soft or 0.0)
    if sigma > 0:
        from scipy import ndimage

        arr = ndimage.gaussian_filter(arr, sigma=sigma)
        peak = float(arr.max()) if arr.size else 0.0
        if peak > 0:
            arr = arr / peak
        arr = np.clip(arr, 0.0, 1.0)
    return arr


def apply_mask(spectrum: np.ndarray, mask: np.ndarray) -> np.ndarray:
    spec = np.asarray(spectrum, dtype=np.complex128)
    weights = np.asarray(mask)
    if weights.shape != spec.shape[:2]:
        weights = np.ones(spec.shape[:2], dtype=np.float64)
    if weights.dtype == bool:
        out = spec.copy()
        out[~weights] = 0
        return out
    return spec * feather_mask(weights, 0.0)


def mask_overlay_rgba(mask: np.ndarray, color: tuple[int, int, int, int] = (0, 163, 224, 80)) -> np.ndarray:
    weights = feather_mask(mask, 0.0)
    rgba = np.zeros(weights.shape + (4,), dtype=np.uint8)
    on = weights > 0.02
    rgba[on, 0] = color[0]
    rgba[on, 1] = color[1]
    rgba[on, 2] = color[2]
    rgba[on, 3] = np.clip((weights[on] * color[3]).astype(np.int32), 0, 255).astype(np.uint8)
    return rgba


def reconstruct(
    spectrum: np.ndarray,
    *,
    kind: MaskKind = "circle",
    center: tuple[float, float] | None = None,
    radius: float | None = None,
    inner: float = 0.0,
    outer: float | None = None,
    width: float | None = None,
    height: float | None = None,
    invert: bool = False,
    soft: float = 0.0,
) -> np.ndarray:
    """Mask a shifted FFT and invert it."""
    spec = np.asarray(spectrum)
    mask = make_mask(
        spec.shape[:2],
        kind,
        center=center,
        radius=radius,
        inner=inner,
        outer=outer,
        width=width,
        height=height,
        invert=invert,
    )
    return ifft2d(apply_mask(spec, feather_mask(mask, soft)))


def bandpass(image: np.ndarray, inner: float, outer: float, invert: bool = False) -> np.ndarray:
    spec = fft2d(image)
    mask = make_mask(image.shape, "annulus", inner=inner, outer=outer, invert=invert)
    return ifft2d(apply_mask(spec, mask))
