"""Downsampled previews so large images / SI / 4D cubes paint immediately."""

from __future__ import annotations

from typing import Any

import numpy as np

from openvelox.processing.cache import memoize_array


def stride_for(shape: tuple[int, ...], max_side: int = 1024) -> int:
    spatial = [int(n) for n in shape if n > 1]
    if not spatial:
        return 1
    return max(1, int(np.ceil(max(spatial) / max(int(max_side), 8))))


def downsample2d(image: np.ndarray, max_side: int = 1024) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim != 2 or arr.size == 0:
        return np.asarray(arr)
    step = stride_for(arr.shape, max_side)
    if step <= 1:
        return arr
    return arr[::step, ::step]


def preview_sum_si(cube: np.ndarray, max_side: int = 512, energy_step: int = 4) -> np.ndarray:
    """Spatial + spectral stride, then sum energy — cheap SI navigator."""
    arr = np.asarray(cube)
    if arr.ndim != 3:
        return downsample2d(np.asarray(arr), max_side)
    step = stride_for(arr.shape[:2], max_side)
    e_step = max(1, int(energy_step))
    return arr[::step, ::step, ::e_step].sum(axis=-1)


def preview_virtual_bf(cube: np.ndarray, max_side: int = 256) -> np.ndarray:
    arr = np.asarray(cube)
    if arr.ndim != 4:
        return downsample2d(np.atleast_2d(arr), max_side)
    step = stride_for(arr.shape[:2], max_side)
    qy, qx = arr.shape[2], arr.shape[3]
    cy, cx = qy // 2, qx // 2
    r = max(1, min(qy, qx) // 6)
    yy, xx = np.ogrid[:qy, :qx]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= r**2
    scan = arr[::step, ::step]
    return scan[:, :, mask].sum(axis=-1)


def cached_preview(key: Any, factory) -> np.ndarray:
    return memoize_array(("preview", key), factory)


def thumbnail_array(image: np.ndarray, size: int = 48) -> np.ndarray:
    """Contrast-stretched uint8 thumbnail (H, W) for the experiment browser."""
    arr = np.asarray(image)
    if arr.size == 0:
        return np.zeros((int(size), int(size)), dtype=np.uint8)
    if arr.ndim == 1:
        return _sparkline(arr, int(size))
    if arr.ndim == 3 and arr.shape[-1] in {3, 4}:
        arr = np.mean(arr[..., :3], axis=-1)
    elif arr.ndim != 2:
        arr = np.reshape(arr, (arr.shape[0], -1))
    arr = np.asarray(arr, dtype=np.float64)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    side = max(8, int(size))
    step_y = max(1, int(np.ceil(arr.shape[0] / side)))
    step_x = max(1, int(np.ceil(arr.shape[1] / side)))
    small = arr[::step_y, ::step_x]
    if small.size == 0:
        return np.zeros((side, side), dtype=np.uint8)
    finite = small[np.isfinite(small)]
    if finite.size == 0:
        return np.zeros((small.shape[0], small.shape[1]), dtype=np.uint8)
    lo, hi = np.percentile(finite, (1.0, 99.0))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo, hi = float(finite.min()), float(finite.max())
        if hi <= lo:
            hi = lo + 1.0
    scaled = np.clip((small - lo) / (hi - lo), 0.0, 1.0)
    return (scaled * 255.0).astype(np.uint8)


def _sparkline(values: np.ndarray, size: int) -> np.ndarray:
    canvas = np.zeros((size, size), dtype=np.float64)
    series = np.asarray(values, dtype=np.float64).ravel()
    series = series[np.isfinite(series)]
    if series.size == 0:
        return canvas.astype(np.uint8)
    lo, hi = float(series.min()), float(series.max())
    if hi <= lo:
        hi = lo + 1.0
    xs = np.linspace(0, size - 1, num=min(series.size, size * 2))
    idx = np.clip((xs / max(size - 1, 1) * (series.size - 1)).astype(int), 0, series.size - 1)
    ys = (1.0 - (series[idx] - lo) / (hi - lo)) * (size - 3) + 1
    for x, y in zip(xs, ys):
        canvas[int(np.clip(y, 0, size - 1)), int(np.clip(x, 0, size - 1))] = 1.0
    return (canvas * 255.0).astype(np.uint8)
