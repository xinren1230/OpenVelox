"""4D-STEM virtual detectors, CoM DPC and diffraction calibration."""

from __future__ import annotations

import math

import numpy as np


def _disk_mask(shape: tuple[int, int], cy: float, cx: float, radius: float) -> np.ndarray:
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= radius**2


def _annulus_mask(
    shape: tuple[int, int],
    cy: float,
    cx: float,
    inner: float,
    outer: float,
) -> np.ndarray:
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    rr = (yy - cy) ** 2 + (xx - cx) ** 2
    return (rr >= inner**2) & (rr <= outer**2)


def _cube_shape(cube) -> tuple[int, int, int, int]:
    shape = getattr(cube, "shape", None)
    if shape is not None and len(shape) == 4:
        return tuple(int(n) for n in shape)
    arr = np.asarray(cube)
    if arr.ndim != 4:
        raise ValueError("4D-STEM cube must be (sy, sx, qy, qx)")
    return tuple(int(n) for n in arr.shape)


def virtual_bf(
    cube: np.ndarray,
    radius: float | None = None,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    from openvelox.io.lazy import iter_4d_rows

    sy, sx, qy, qx = _cube_shape(cube)
    cy, cx = center if center is not None else (qy / 2.0, qx / 2.0)
    r = radius if radius is not None else min(qy, qx) / 6.0
    mask = _disk_mask((qy, qx), cy, cx, r)
    out = np.zeros((sy, sx), dtype=np.float64)
    for y0, y1, slab in iter_4d_rows(cube):
        out[y0:y1] = slab[:, :, mask].sum(axis=-1)
    return out


def virtual_adf(
    cube: np.ndarray,
    inner: float | None = None,
    outer: float | None = None,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    from openvelox.io.lazy import iter_4d_rows

    sy, sx, qy, qx = _cube_shape(cube)
    cy, cx = center if center is not None else (qy / 2.0, qx / 2.0)
    r_in = inner if inner is not None else min(qy, qx) / 5.0
    r_out = outer if outer is not None else min(qy, qx) / 2.2
    mask = _annulus_mask((qy, qx), cy, cx, r_in, r_out)
    out = np.zeros((sy, sx), dtype=np.float64)
    for y0, y1, slab in iter_4d_rows(cube):
        out[y0:y1] = slab[:, :, mask].sum(axis=-1)
    return out


def center_of_mass_dpc(cube: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """CoM of each CBED pattern relative to the array center → (com_x, com_y)."""
    from openvelox.io.lazy import iter_4d_rows

    sy, sx, qy, qx = _cube_shape(cube)
    yy = np.arange(qy, dtype=np.float64) - (qy - 1) / 2.0
    xx = np.arange(qx, dtype=np.float64) - (qx - 1) / 2.0
    com_x = np.zeros((sy, sx), dtype=np.float64)
    com_y = np.zeros((sy, sx), dtype=np.float64)
    for y0, y1, slab in iter_4d_rows(cube):
        mass = slab.reshape(slab.shape[0], slab.shape[1], -1).sum(axis=-1)
        mass = np.where(mass == 0, 1.0, mass)
        com_y[y0:y1] = (slab * yy[None, None, :, None]).sum(axis=(2, 3)) / mass
        com_x[y0:y1] = (slab * xx[None, None, None, :]).sum(axis=(2, 3)) / mass
    return com_x, com_y


def probe_pattern(cube: np.ndarray, iy: int, ix: int) -> np.ndarray:
    arr = np.asarray(cube)
    iy = int(np.clip(iy, 0, arr.shape[0] - 1))
    ix = int(np.clip(ix, 0, arr.shape[1] - 1))
    return arr[iy, ix]


def virtual_abf(
    cube: np.ndarray,
    inner: float | None = None,
    outer: float | None = None,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    """Annular bright-field: a ring inside the transmitted disk."""
    from openvelox.io.lazy import iter_4d_rows

    sy, sx, qy, qx = _cube_shape(cube)
    cy, cx = center if center is not None else (qy / 2.0, qx / 2.0)
    r_out = outer if outer is not None else min(qy, qx) / 6.0
    r_in = inner if inner is not None else max(r_out * 0.55, 1.0)
    if r_in > r_out:
        r_in, r_out = r_out, r_in
    mask = _annulus_mask((qy, qx), cy, cx, r_in, r_out)
    out = np.zeros((sy, sx), dtype=np.float64)
    for y0, y1, slab in iter_4d_rows(cube):
        out[y0:y1] = slab[:, :, mask].sum(axis=-1)
    return out


def electron_wavelength_m(volts: float) -> float:
    """Relativistic electron wavelength (m) from accelerating voltage."""
    v = float(volts)
    if v <= 0:
        return 0.0
    h = 6.62607015e-34
    m = 9.1093837015e-31
    e = 1.602176634e-19
    c = 299792458.0
    energy = v * e
    p = math.sqrt(2.0 * m * energy * (1.0 + energy / (2.0 * m * c * c)))
    return h / p


def q_per_px_inv_angstrom(
    *,
    camera_length_m: float,
    detector_pixel_m: float,
    wavelength_m: float,
) -> float:
    """Å⁻¹ per diffraction pixel from camera length, pixel size and λ."""
    cl = float(camera_length_m)
    px = float(detector_pixel_m)
    lam = float(wavelength_m)
    if cl <= 0 or px <= 0 or lam <= 0:
        return 0.0
    theta = px / cl
    return (theta / lam) * 1e-10


def radius_to_pixels(
    value: float,
    unit: str = "px",
    *,
    q_per_px: float | None = None,
    camera_length_m: float | None = None,
    detector_pixel_m: float | None = None,
) -> float:
    """Convert a detector radius in px, mrad or Å⁻¹ into pattern pixels."""
    v = float(value)
    kind = str(unit or "px").lower()
    if kind in {"px", "pixel", "pixels"}:
        return v
    if kind == "mrad" and camera_length_m and detector_pixel_m and float(detector_pixel_m) > 0:
        return v * 1e-3 * float(camera_length_m) / float(detector_pixel_m)
    if kind in {"a-1", "1/a", "inv_a", "q"} and q_per_px and float(q_per_px) > 0:
        return v / float(q_per_px)
    return v


def rotate_vector_field(
    vx: np.ndarray,
    vy: np.ndarray,
    rotation_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    th = math.radians(float(rotation_deg))
    c, s = math.cos(th), math.sin(th)
    fx = np.asarray(vx, dtype=np.float64)
    fy = np.asarray(vy, dtype=np.float64)
    return fx * c - fy * s, fx * s + fy * c


def apply_diffraction_cal(
    com_x: np.ndarray,
    com_y: np.ndarray,
    *,
    rotation_deg: float = 0.0,
    q_per_px: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    rx, ry = rotate_vector_field(com_x, com_y, rotation_deg)
    if q_per_px and float(q_per_px) > 0:
        rx = rx * float(q_per_px)
        ry = ry * float(q_per_px)
    return rx, ry


def detector_cartoon(
    size: int = 96,
    *,
    bf_r: float = 4.0,
    adf_in: float = 5.0,
    adf_out: float = 11.0,
    abf_in: float = 2.0,
    abf_out: float = 3.5,
    center: tuple[float, float] | None = None,
) -> np.ndarray:
    """RGB cartoon of BF (cyan), ABF (green) and ADF (amber) disks."""
    n = max(16, int(size))
    rgb = np.zeros((n, n, 3), dtype=np.uint8)
    rgb[:] = (16, 22, 28)
    cy, cx = center if center is not None else ((n - 1) / 2.0, (n - 1) / 2.0)
    scale = n / 24.0
    yy, xx = np.ogrid[:n, :n]
    rr = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    adf = (rr >= adf_in * scale) & (rr <= adf_out * scale)
    abf = (rr >= abf_in * scale) & (rr <= abf_out * scale)
    bf = rr <= bf_r * scale
    rgb[adf] = (220, 140, 40)
    rgb[bf] = (0, 163, 224)
    rgb[abf] = (80, 200, 80)
    # Quadrant ticks for a DPC cartoon.
    mid = int(round(cy))
    rgb[max(0, mid - 1) : mid + 2, :] = np.maximum(rgb[max(0, mid - 1) : mid + 2, :], 40)
    rgb[:, max(0, int(round(cx)) - 1) : int(round(cx)) + 2] = np.maximum(
        rgb[:, max(0, int(round(cx)) - 1) : int(round(cx)) + 2], 40
    )
    return rgb
