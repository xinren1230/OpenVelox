"""Measurement tools: line profile, distance, angle, ROI statistics."""

from __future__ import annotations

import numpy as np
from skimage.measure import profile_line


def line_profile(
    image: np.ndarray,
    p0: tuple[float, float],
    p1: tuple[float, float],
    linewidth: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(image, dtype=np.float64)
    if arr.size == 0:
        return np.zeros(1), np.zeros(1)
    values = profile_line(
        arr, p0, p1, linewidth=max(1, int(round(linewidth))), mode="nearest", reduce_func=np.mean
    )
    dist = np.linspace(0.0, float(np.hypot(p1[0] - p0[0], p1[1] - p0[1])), num=values.size)
    return dist, values


def profile_stats(dist: np.ndarray, values: np.ndarray) -> dict[str, float]:
    y = np.asarray(values, dtype=np.float64)
    x = np.asarray(dist, dtype=np.float64)
    if y.size == 0:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "fwhm": 0.0, "length": 0.0}
    half = 0.5 * (float(y.max()) + float(y.min()))
    above = np.where(y >= half)[0]
    fwhm = float(x[above[-1]] - x[above[0]]) if above.size else 0.0
    return {
        "mean": float(y.mean()),
        "min": float(y.min()),
        "max": float(y.max()),
        "fwhm": fwhm,
        "length": float(x[-1] - x[0]) if x.size else 0.0,
    }


def distance(p0: tuple[float, float], p1: tuple[float, float], pixel_m: float = 1.0) -> float:
    return float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]) * pixel_m)


def angle_deg(
    p0: tuple[float, float],
    vertex: tuple[float, float],
    p1: tuple[float, float],
) -> float:
    v0 = np.array(p0, dtype=np.float64) - np.array(vertex, dtype=np.float64)
    v1 = np.array(p1, dtype=np.float64) - np.array(vertex, dtype=np.float64)
    n0 = np.linalg.norm(v0)
    n1 = np.linalg.norm(v1)
    if n0 == 0 or n1 == 0:
        return 0.0
    cos = float(np.clip(np.dot(v0, v1) / (n0 * n1), -1.0, 1.0))
    return float(np.degrees(np.arccos(cos)))


def roi_stats(image: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    arr = np.asarray(image, dtype=np.float64)
    sel = arr[np.asarray(mask, dtype=bool)]
    if sel.size == 0:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "sum": 0.0, "n": 0.0}
    return {
        "mean": float(sel.mean()),
        "std": float(sel.std()),
        "min": float(sel.min()),
        "max": float(sel.max()),
        "sum": float(sel.sum()),
        "n": float(sel.size),
    }


def rect_mask(shape: tuple[int, int], x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    xa, xb = sorted((x0, x1))
    ya, yb = sorted((y0, y1))
    return (xx >= xa) & (xx <= xb) & (yy >= ya) & (yy <= yb)


def ellipse_mask(
    shape: tuple[int, int],
    cx: float,
    cy: float,
    rx: float,
    ry: float,
) -> np.ndarray:
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    rx = max(rx, 1e-6)
    ry = max(ry, 1e-6)
    return ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0


def polygon_mask(shape: tuple[int, int], points: list[tuple[float, float]]) -> np.ndarray:
    """``points`` are (x/col, y/row) in image coordinates."""
    h, w = int(shape[0]), int(shape[1])
    mask = np.zeros((h, w), dtype=bool)
    if len(points) < 3:
        return mask
    from skimage.draw import polygon

    cols = np.array([p[0] for p in points], dtype=np.float64)
    rows = np.array([p[1] for p in points], dtype=np.float64)
    rr, cc = polygon(rows, cols, shape=(h, w))
    mask[rr, cc] = True
    return mask


def area_m2(n_pixels: float, pixel_m: float | None) -> float:
    px = float(pixel_m or 0.0)
    if px <= 0:
        return 0.0
    return float(n_pixels) * px * px


def format_area(meters2: float | None) -> str:
    if meters2 is None:
        return "—"
    try:
        a = float(meters2)
    except (TypeError, ValueError):
        return "—"
    if a <= 0:
        return "—"
    if a >= 1e-12:
        return f"{a * 1e12:.3g} µm²"
    if a >= 1e-18:
        return f"{a * 1e18:.3g} nm²"
    return f"{a:.3e} m²"


def intensity_histogram(
    image: np.ndarray,
    mask: np.ndarray | None = None,
    bins: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(image, dtype=np.float64)
    if mask is not None:
        sel = arr[np.asarray(mask, dtype=bool)]
    else:
        sel = arr.ravel()
    finite = sel[np.isfinite(sel)]
    if finite.size == 0:
        return np.zeros(0), np.zeros(0)
    counts, edges = np.histogram(finite, bins=min(max(8, int(bins)), int(finite.size)))
    return edges[:-1], counts.astype(np.float64)


def fft_d_spacing(
    p0: tuple[float, float],
    p1: tuple[float, float],
    shape: tuple[int, ...],
    pixel_m: float,
    center_tol: float = 8.0,
) -> dict[str, float | str]:
    """Real-space d-spacing from two FFT clicks.

    ``p0`` / ``p1`` are (row, col). A click near the DC peak uses *center*
    mode (``d = 1/|g|``); two Bragg spots use *pair* mode (``d = 2/|Δg|``).
    """
    h = max(int(shape[0]), 1)
    w = max(int(shape[1]) if len(shape) > 1 else h, 1)
    px = float(pixel_m or 0.0)
    drow = float(p1[0]) - float(p0[0])
    dcol = float(p1[1]) - float(p0[1])
    r_px = float(np.hypot(drow, dcol))
    cy, cx = h / 2.0, w / 2.0
    near_dc = min(np.hypot(p0[0] - cy, p0[1] - cx), np.hypot(p1[0] - cy, p1[1] - cx)) <= float(center_tol)
    if px <= 0 or r_px <= 1e-9:
        return {
            "delta_px": r_px,
            "frequency_per_m": 0.0,
            "d_spacing_m": 0.0,
            "mode": "center" if near_dc else "pair",
        }
    fx = dcol / (w * px)
    fy = drow / (h * px)
    freq = float(np.hypot(fx, fy))
    mode = "center" if near_dc else "pair"
    d_m = (1.0 / freq) if mode == "center" else (2.0 / freq)
    return {
        "delta_px": r_px,
        "frequency_per_m": freq,
        "d_spacing_m": float(d_m),
        "mode": mode,
    }
