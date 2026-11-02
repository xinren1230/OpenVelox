"""Atom-column finding (Atomap-style local maxima + optional refinement)."""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def find_atom_columns(
    image: np.ndarray,
    *,
    sigma: float = 1.2,
    min_distance: int = 5,
    threshold: float | None = None,
    refine: bool = True,
) -> np.ndarray:
    """Return (N, 2) array of (row, col) sub-pixel positions."""
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2 or arr.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    smooth = ndimage.gaussian_filter(arr, sigma=float(sigma))
    size = max(3, int(min_distance) * 2 + 1)
    maxima = smooth == ndimage.maximum_filter(smooth, size=size)
    if threshold is None:
        finite = smooth[np.isfinite(smooth)]
        threshold = float(np.percentile(finite, 75)) if finite.size else 0.0
    maxima &= smooth >= float(threshold)
    ys, xs = np.nonzero(maxima)
    if ys.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    coords = np.column_stack([ys.astype(np.float64), xs.astype(np.float64)])
    if refine:
        coords = _refine_com(arr, coords, window=max(3, int(min_distance)))
    return coords


def _refine_com(image: np.ndarray, coords: np.ndarray, window: int = 3) -> np.ndarray:
    h, w = image.shape
    r = max(1, window // 2)
    refined = []
    for y, x in coords:
        y0 = int(max(0, np.floor(y) - r))
        x0 = int(max(0, np.floor(x) - r))
        y1 = int(min(h, np.floor(y) + r + 1))
        x1 = int(min(w, np.floor(x) + r + 1))
        patch = image[y0:y1, x0:x1]
        mass = patch.sum()
        if mass <= 0:
            refined.append((y, x))
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        refined.append(((yy * patch).sum() / mass, (xx * patch).sum() / mass))
    return np.asarray(refined, dtype=np.float64)


def try_atomap(image: np.ndarray, separation: int = 6) -> np.ndarray | None:
    """Use Atomap when installed; otherwise return None."""
    try:
        from atomap.atom_finding_refining import get_atom_positions  # type: ignore
    except Exception:
        return None
    try:
        dummy = type("S", (), {"data": np.asarray(image)})()
        pos = get_atom_positions(dummy, separation=separation)
        return np.asarray(pos, dtype=np.float64)[:, ::-1]  # x,y → row,col if needed
    except Exception:
        return None
