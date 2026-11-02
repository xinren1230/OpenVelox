"""Colormaps, contrast / brightness / gamma, and RGB conversion."""

from __future__ import annotations

import numpy as np

COLORMAPS = (
    "gray",
    "gray_inv",
    "thermal",
    "fire",
    "ice",
    "glow",
    "green",
    "red",
    "bone",
    "viridis",
    "magma",
    "plasma",
    "inferno",
    "hot",
    "cool",
    "jet",
    "nipy_spectral",
    "cubehelix",
    "cividis",
)


def _lerp(stops: list[tuple[float, tuple[int, int, int]]], n: int = 256) -> np.ndarray:
    xs = np.array([s[0] for s in stops], dtype=np.float64)
    colors = np.array([s[1] for s in stops], dtype=np.float64)
    t = np.linspace(0, 1, n)
    lut = np.empty((n, 3), dtype=np.uint8)
    for i in range(3):
        lut[:, i] = np.clip(np.interp(t, xs, colors[:, i]), 0, 255).astype(np.uint8)
    return lut


_LUTS: dict[str, np.ndarray] = {
    "gray": np.stack([np.arange(256, dtype=np.uint8)] * 3, axis=1),
    "gray_inv": np.stack([np.arange(255, -1, -1, dtype=np.uint8)] * 3, axis=1),
    "fire": _lerp(
        [
            (0.0, (0, 0, 0)),
            (0.2, (80, 0, 0)),
            (0.45, (255, 40, 0)),
            (0.7, (255, 180, 0)),
            (1.0, (255, 255, 255)),
        ]
    ),
    "ice": _lerp(
        [
            (0.0, (0, 0, 0)),
            (0.35, (0, 40, 160)),
            (0.65, (0, 180, 255)),
            (1.0, (230, 255, 255)),
        ]
    ),
    "glow": _lerp([(0.0, (0, 0, 0)), (0.5, (180, 20, 80)), (1.0, (255, 230, 160))]),
    "green": _lerp([(0.0, (0, 0, 0)), (1.0, (0, 255, 80))]),
    "red": _lerp([(0.0, (0, 0, 0)), (1.0, (255, 40, 20))]),
    "bone": _lerp([(0.0, (0, 0, 0)), (0.4, (80, 80, 100)), (1.0, (255, 255, 245))]),
    "thermal": _lerp(
        [
            (0.0, (0, 0, 0)),
            (0.25, (80, 0, 90)),
            (0.5, (200, 30, 40)),
            (0.75, (255, 160, 0)),
            (1.0, (255, 255, 220)),
        ]
    ),
    "hot": _lerp([(0, (0, 0, 0)), (0.33, (255, 0, 0)), (0.66, (255, 255, 0)), (1, (255, 255, 255))]),
    "cool": _lerp([(0, (0, 255, 255)), (1, (255, 0, 255))]),
    "jet": _lerp(
        [
            (0, (0, 0, 128)),
            (0.15, (0, 0, 255)),
            (0.4, (0, 255, 255)),
            (0.65, (255, 255, 0)),
            (0.85, (255, 0, 0)),
            (1, (128, 0, 0)),
        ]
    ),
    "viridis": _lerp(
        [
            (0, (68, 1, 84)),
            (0.25, (59, 82, 139)),
            (0.5, (33, 145, 140)),
            (0.75, (94, 201, 98)),
            (1, (253, 231, 37)),
        ]
    ),
    "magma": _lerp(
        [
            (0, (0, 0, 4)),
            (0.3, (81, 18, 124)),
            (0.55, (183, 55, 121)),
            (0.8, (252, 137, 97)),
            (1, (252, 253, 191)),
        ]
    ),
    "plasma": _lerp(
        [
            (0, (13, 8, 135)),
            (0.3, (126, 3, 168)),
            (0.55, (204, 71, 120)),
            (0.8, (248, 149, 64)),
            (1, (240, 249, 33)),
        ]
    ),
    "inferno": _lerp(
        [
            (0, (0, 0, 4)),
            (0.3, (87, 16, 110)),
            (0.55, (188, 55, 90)),
            (0.8, (249, 142, 9)),
            (1, (252, 255, 164)),
        ]
    ),
    "cividis": _lerp(
        [
            (0, (0, 32, 77)),
            (0.5, (126, 125, 121)),
            (1, (253, 234, 69)),
        ]
    ),
    "cubehelix": _lerp(
        [
            (0, (0, 0, 0)),
            (0.25, (22, 80, 90)),
            (0.5, (108, 92, 50)),
            (0.75, (198, 140, 180)),
            (1, (255, 255, 255)),
        ]
    ),
    "nipy_spectral": _lerp(
        [
            (0, (0, 0, 0)),
            (0.15, (0, 0, 180)),
            (0.35, (0, 180, 180)),
            (0.5, (0, 200, 0)),
            (0.7, (220, 220, 0)),
            (0.85, (220, 0, 0)),
            (1, (255, 255, 255)),
        ]
    ),
}


def colormap_lut(name: str) -> np.ndarray:
    return _LUTS.get(name, _LUTS["gray"])


def lut_names() -> list[str]:
    names = list(COLORMAPS)
    for key in _LUTS:
        if key not in names:
            names.append(key)
    return names


def register_lut(name: str, lut: np.ndarray) -> np.ndarray:
    arr = np.asarray(lut, dtype=np.uint8)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise ValueError("LUT must be (N, 3) RGB")
    if arr.shape[0] != 256:
        x = np.linspace(0, 1, arr.shape[0])
        xi = np.linspace(0, 1, 256)
        arr = np.stack([np.interp(xi, x, arr[:, i]).astype(np.uint8) for i in range(3)], axis=1)
    _LUTS[name] = arr[:, :3]
    if name not in COLORMAPS:
        globals()["COLORMAPS"] = tuple(list(COLORMAPS) + [name])
    return _LUTS[name]


def load_lut(path: str | bytes) -> np.ndarray:
    """Load an ImageJ-style 768-byte .lut or a CSV of r,g,b rows."""
    from pathlib import Path

    raw = Path(path).read_bytes() if not isinstance(path, (bytes, bytearray)) else bytes(path)
    if len(raw) == 768:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(3, 256).T
        return arr.copy()
    text = raw.decode("utf-8", errors="replace")
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p for p in line.replace(",", " ").split() if p]
        if len(parts) >= 3:
            rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
    if not rows:
        raise ValueError("No RGB rows in LUT file")
    return np.clip(np.asarray(rows), 0, 255).astype(np.uint8)


def auto_levels(image: np.ndarray, low: float = 0.5, high: float = 99.5) -> tuple[float, float]:
    arr = np.asarray(image, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin, vmax = np.percentile(finite, (low, high))
    if vmax <= vmin:
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def normalize(image: np.ndarray, vmin: float | None = None, vmax: float | None = None) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if vmin is None or vmax is None:
        auto_min, auto_max = auto_levels(arr)
        vmin = auto_min if vmin is None else vmin
        vmax = auto_max if vmax is None else vmax
    if vmax <= vmin:
        vmax = vmin + 1.0
    return np.clip((arr - vmin) / (vmax - vmin), 0.0, 1.0)


def apply_display(
    image: np.ndarray,
    *,
    colormap: str = "gray",
    vmin: float | None = None,
    vmax: float | None = None,
    gamma: float = 1.0,
    brightness: float = 1.0,
    invert: bool = False,
) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float64)
    if arr.size == 0:
        arr = np.zeros((8, 8), dtype=np.float64)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    norm = normalize(arr, vmin, vmax)
    gamma = max(float(gamma), 1e-3)
    norm = np.clip(norm ** (1.0 / gamma), 0.0, 1.0)
    norm = np.clip(norm * float(brightness), 0.0, 1.0)
    if invert:
        norm = 1.0 - norm
    idx = np.clip((norm * 255.0).astype(np.int32), 0, 255)
    return colormap_lut(colormap)[idx]
