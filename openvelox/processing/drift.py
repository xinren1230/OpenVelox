"""Drift-corrected alignment and Velox-style DCFI (frame integration)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter, shift as ndi_shift
from skimage.registration import phase_cross_correlation


@dataclass
class DCFIResult:
    aligned: np.ndarray
    integrated: np.ndarray
    shifts: np.ndarray
    used: np.ndarray
    crop: tuple[int, int, int, int] | None
    residual_rms: float


def _prepare(frame: np.ndarray, highpass_sigma: float) -> np.ndarray:
    arr = np.nan_to_num(np.asarray(frame, dtype=np.float64), nan=0.0)
    if highpass_sigma and highpass_sigma > 0:
        arr = arr - gaussian_filter(arr, sigma=float(highpass_sigma))
    return arr


def estimate_shifts(
    stack: np.ndarray,
    upsample: int = 10,
    *,
    reference: str = "first",
    highpass_sigma: float = 0.0,
) -> np.ndarray:
    frames = np.asarray(stack, dtype=np.float64)
    if frames.ndim != 3:
        raise ValueError("Stack must be (n, y, x)")
    n = frames.shape[0]
    shifts = np.zeros((n, 2), dtype=np.float64)
    if n <= 1:
        return shifts
    prepared = [_prepare(frames[i], highpass_sigma) for i in range(n)]
    mode = (reference or "first").lower()
    if mode == "previous":
        acc = np.zeros(2, dtype=np.float64)
        for i in range(1, n):
            delta, _err, _ph = phase_cross_correlation(prepared[i - 1], prepared[i], upsample_factor=upsample)
            acc = acc + np.asarray(delta, dtype=np.float64)
            shifts[i] = acc
        return shifts
    ref = prepared[0]
    for i in range(1, n):
        delta, _err, _ph = phase_cross_correlation(ref, prepared[i], upsample_factor=upsample)
        shifts[i] = np.asarray(delta, dtype=np.float64)
    if mode == "mean":
        aligned = apply_shifts(frames, shifts)
        mean_ref = _prepare(aligned.mean(axis=0), highpass_sigma)
        refined = np.zeros_like(shifts)
        for i in range(n):
            delta, _err, _ph = phase_cross_correlation(mean_ref, _prepare(aligned[i], highpass_sigma), upsample_factor=upsample)
            refined[i] = shifts[i] + np.asarray(delta, dtype=np.float64)
        refined -= refined.mean(axis=0)
        return refined
    return shifts


def apply_shifts(stack: np.ndarray, shifts: np.ndarray) -> np.ndarray:
    frames = np.asarray(stack, dtype=np.float64)
    aligned = np.empty_like(frames)
    for i, sh in enumerate(shifts):
        aligned[i] = ndi_shift(frames[i], shift=sh, order=1, mode="nearest")
    return aligned


def _overlap_box(shape: tuple[int, int], shifts: np.ndarray, used: np.ndarray) -> tuple[int, int, int, int] | None:
    h, w = shape
    sel = shifts[np.asarray(used, dtype=bool)]
    if sel.size == 0:
        return None
    top = int(np.ceil(max(0.0, float(sel[:, 0].max()))))
    left = int(np.ceil(max(0.0, float(sel[:, 1].max()))))
    bottom = int(np.floor(min(h, h + float(sel[:, 0].min()))))
    right = int(np.floor(min(w, w + float(sel[:, 1].min()))))
    if bottom - top < 2 or right - left < 2:
        return None
    return top, bottom, left, right


def dcfi(
    stack: np.ndarray,
    *,
    upsample: int = 10,
    reference: str = "first",
    highpass_sigma: float = 0.0,
    max_shift: float | None = None,
    crop: bool = True,
    reduce: str = "mean",
) -> DCFIResult:
    """Drift-corrected frame integration (Velox DCFI).

    ``reference`` is ``first``, ``previous`` or ``mean``. Frames whose shift
    exceeds ``max_shift`` (pixels) are dropped from the integral. ``reduce``
    is ``mean`` or ``sum``. When ``crop`` is true the result is the common
    overlap after alignment.
    """
    frames = np.asarray(stack, dtype=np.float64)
    if frames.ndim != 3:
        raise ValueError("Stack must be (n, y, x)")
    shifts = estimate_shifts(frames, upsample=upsample, reference=reference, highpass_sigma=highpass_sigma)
    used = np.ones(frames.shape[0], dtype=bool)
    if max_shift is not None and float(max_shift) > 0:
        mag = np.hypot(shifts[:, 0], shifts[:, 1])
        used = mag <= float(max_shift)
        used[0] = True
        if not used.any():
            used[:] = True
    aligned = apply_shifts(frames, shifts)
    box = _overlap_box(frames.shape[1:], shifts, used) if crop else None
    work = aligned[used]
    if box is not None:
        y0, y1, x0, x1 = box
        work = work[:, y0:y1, x0:x1]
    if work.shape[0] == 0:
        work = aligned
    if (reduce or "mean").lower() == "sum":
        integrated = work.sum(axis=0)
    else:
        integrated = work.mean(axis=0)
    residual = shifts[used] - shifts[used].mean(axis=0)
    rms = float(np.sqrt(np.mean(residual**2))) if residual.size else 0.0
    return DCFIResult(
        aligned=aligned,
        integrated=np.asarray(integrated, dtype=np.float64),
        shifts=shifts,
        used=used,
        crop=box,
        residual_rms=rms,
    )


def align_and_sum(stack: np.ndarray, upsample: int = 10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (aligned_stack, sum_image, shifts). Back-compat wrapper around DCFI."""
    result = dcfi(stack, upsample=upsample, reduce="sum", crop=False, reference="first")
    return result.aligned, result.integrated, result.shifts
