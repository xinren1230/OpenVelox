"""DPC / iDPC / dDPC from four-quadrant segmented STEM detectors."""

from __future__ import annotations

from typing import Mapping

import numpy as np


def dpc_from_quadrants(
    quadrants: Mapping[str, np.ndarray] | tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Return (dpc_x, dpc_y).

    Thermo-like 4-quadrant convention:
        A | B
        --+--
        D | C
    DPC_x = (B + C) − (A + D)
    DPC_y = (A + B) − (D + C)
    """
    if isinstance(quadrants, tuple):
        a, b, c, d = (np.asarray(q, dtype=np.float64) for q in quadrants)
    else:
        lookup = {k.upper(): np.asarray(v, dtype=np.float64) for k, v in quadrants.items()}

        def _pick(*names: str) -> np.ndarray:
            for name in names:
                for key, val in lookup.items():
                    if name in key:
                        return val
            raise KeyError(f"Missing quadrant among {names}")

        a = _pick("DF4-A", "A")
        b = _pick("DF4-B", "B")
        c = _pick("DF4-C", "C")
        d = _pick("DF4-D", "D")
    dpc_x = (b + c) - (a + d)
    dpc_y = (a + b) - (d + c)
    return dpc_x, dpc_y


def idpc(dpc_x: np.ndarray, dpc_y: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Fourier integration of the DPC vector field (iDPC)."""
    fx = np.asarray(dpc_x, dtype=np.float64)
    fy = np.asarray(dpc_y, dtype=np.float64)
    if fx.shape != fy.shape:
        raise ValueError("DPC components must share a shape")
    h, w = fx.shape
    ky = np.fft.fftfreq(h).reshape(-1, 1)
    kx = np.fft.fftfreq(w).reshape(1, -1)
    denom = kx**2 + ky**2
    denom[0, 0] = 1.0
    fx_k = np.fft.fft2(fx)
    fy_k = np.fft.fft2(fy)
    integ = -1j * (kx * fx_k + ky * fy_k) / (denom + eps)
    integ[0, 0] = 0
    rec = np.real(np.fft.ifft2(integ))
    rec -= rec.mean()
    return rec


def ddpc(dpc_x: np.ndarray, dpc_y: np.ndarray) -> np.ndarray:
    """Divergence of the DPC field (dDPC)."""
    fx = np.asarray(dpc_x, dtype=np.float64)
    fy = np.asarray(dpc_y, dtype=np.float64)
    dxy, dxx = np.gradient(fx)
    dyy, dyx = np.gradient(fy)
    return dxx + dyy


def dpc_magnitude(dpc_x: np.ndarray, dpc_y: np.ndarray) -> np.ndarray:
    return np.hypot(np.asarray(dpc_x, dtype=np.float64), np.asarray(dpc_y, dtype=np.float64))


def dpc_color(dpc_x: np.ndarray, dpc_y: np.ndarray) -> np.ndarray:
    """HSV-like direction (hue) + magnitude (value) color map of a DPC vector field."""
    fx = np.asarray(dpc_x, dtype=np.float64)
    fy = np.asarray(dpc_y, dtype=np.float64)
    mag = np.hypot(fx, fy)
    mag = mag / (mag.max() + 1e-12)
    ang = (np.arctan2(fy, fx) + np.pi) / (2 * np.pi)
    hsv = np.stack([ang, np.ones_like(ang), mag], axis=-1)
    return _hsv_to_rgb(hsv)


def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6).astype(int) % 6
    f = h * 6 - np.floor(h * 6)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)
