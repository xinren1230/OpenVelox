"""Common TEM image filters."""

from __future__ import annotations

import numpy as np
from scipy import ndimage, signal


def gaussian_filter(image: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    return ndimage.gaussian_filter(np.asarray(image, dtype=np.float64), sigma=float(sigma))


def median_filter(image: np.ndarray, size: int = 3) -> np.ndarray:
    size = max(1, int(size))
    return ndimage.median_filter(np.asarray(image, dtype=np.float64), size=size)


def wiener_filter(image: np.ndarray, mysize: int = 5) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.size == 0:
        return arr
    arr = np.nan_to_num(arr, nan=0.0)
    size = max(3, int(mysize))
    size = min(size, max(3, int(min(arr.shape) if arr.ndim >= 2 else arr.size)))
    try:
        return signal.wiener(arr, mysize=size)
    except Exception:
        return arr


def average_background(image: np.ndarray, sigma: float = 25.0) -> np.ndarray:
    """Subtract a heavily smoothed copy (Velox-style average background)."""
    arr = np.asarray(image, dtype=np.float64)
    bg = ndimage.gaussian_filter(arr, sigma=float(sigma))
    return arr - bg


def _disk(radius: int) -> np.ndarray:
    r = max(1, int(radius))
    yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
    return (yy * yy + xx * xx) <= r * r


def rolling_ball_background(image: np.ndarray, radius: float = 25.0) -> np.ndarray:
    """Morphological rolling-ball (grey opening with a disk)."""
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2 or arr.size == 0:
        return np.zeros_like(arr)
    footprint = _disk(int(max(1, round(float(radius)))))
    return ndimage.grey_opening(arr, footprint=footprint)


def plane_background(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2 or arr.size == 0:
        return np.zeros_like(arr)
    h, w = arr.shape
    yy, xx = np.mgrid[0:h, 0:w]
    finite = np.isfinite(arr)
    if int(finite.sum()) < 3:
        return np.zeros_like(arr)
    a = np.stack([xx[finite], yy[finite], np.ones(int(finite.sum()))], axis=1)
    coef, *_ = np.linalg.lstsq(a, arr[finite], rcond=None)
    return coef[0] * xx + coef[1] * yy + coef[2]


def constant_background(image: np.ndarray, percentile: float = 1.0) -> float:
    arr = np.asarray(image, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    return float(np.percentile(finite, float(percentile)))


def subtract_background(
    image: np.ndarray,
    method: str = "average",
    *,
    sigma: float = 25.0,
    radius: float = 25.0,
    percentile: float = 1.0,
) -> np.ndarray:
    """Velox-like background models: average, rolling ball, plane, constant."""
    arr = np.asarray(image, dtype=np.float64)
    kind = (method or "average").lower()
    if kind in {"rolling", "rolling_ball", "ball"}:
        bg = rolling_ball_background(arr, radius=radius)
        return arr - bg
    if kind == "plane":
        return arr - plane_background(arr)
    if kind == "constant":
        return arr - constant_background(arr, percentile=percentile)
    return average_background(arr, sigma=sigma)


def unsharp_mask(image: np.ndarray, sigma: float = 1.2, amount: float = 1.0) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    blur = ndimage.gaussian_filter(arr, sigma=float(sigma))
    return arr + float(amount) * (arr - blur)


def sobel_filter(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2 or arr.size == 0:
        return arr
    gx = ndimage.sobel(arr, axis=1)
    gy = ndimage.sobel(arr, axis=0)
    return np.hypot(gx, gy)


def highpass_filter(image: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    return average_background(image, sigma=sigma)
