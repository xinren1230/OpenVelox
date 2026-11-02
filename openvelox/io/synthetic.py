"""Generate a compact Velox-like .emd with STEM, EDS SI, DPC quadrants, stack and 4D-STEM."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from openvelox.io.velox_emd import (
    build_velox_metadata,
    read_emd,
    write_dataset_group,
    write_spectrum_stream_group,
)
from openvelox.models import ExperimentFile

DEFAULT_HV = 200000.0
DEFAULT_MAG = 320000.0
DEFAULT_PIXEL_M = 2.5e-11  # 0.025 nm
DEFAULT_DWELL = 1.0e-5


def _gaussian_blob(yy: np.ndarray, xx: np.ndarray, y0: float, x0: float, sigma: float, amp: float) -> np.ndarray:
    return amp * np.exp(-((yy - y0) ** 2 + (xx - x0) ** 2) / (2.0 * sigma**2))


def make_haadf_lattice(size: int = 192, spacing: float = 8.0, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    image = np.zeros((size, size), dtype=np.float64)
    # Two-sublattice perovskite-like columns (Sr-like bright, Ti-like dim).
    for iy in np.arange(spacing / 2, size, spacing):
        for ix in np.arange(spacing / 2, size, spacing):
            image += _gaussian_blob(yy, xx, iy, ix, 1.15, 1.0)
            image += _gaussian_blob(yy, xx, iy + spacing / 2, ix + spacing / 2, 0.95, 0.45)
    # Au-like nanoparticle cluster
    image += _gaussian_blob(yy, xx, size * 0.42, size * 0.55, 14.0, 0.55)
    image += 0.02 * rng.standard_normal(image.shape)
    image = np.clip(image, 0, None)
    image = image / image.max()
    return (image * 12000 + 400).astype(np.uint16)


def make_bf_image(haadf: np.ndarray) -> np.ndarray:
    inv = haadf.max() - haadf.astype(np.float64)
    inv = inv / inv.max()
    return (inv * 9000 + 800).astype(np.uint16)


def make_phase_object(size: int = 192) -> np.ndarray:
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    phase = np.zeros((size, size), dtype=np.float64)
    phase += _gaussian_blob(yy, xx, size * 0.40, size * 0.55, 16.0, 1.4)
    phase += _gaussian_blob(yy, xx, size * 0.62, size * 0.38, 11.0, 0.8)
    phase += 0.15 * np.sin(xx / 7.0) * np.sin(yy / 9.0)
    return phase


def make_segmented_detectors(size: int = 192) -> dict[str, np.ndarray]:
    phase = make_phase_object(size)
    gy, gx = np.gradient(phase)
    base = 0.35 + 0.15 * (phase - phase.min()) / (np.ptp(phase) + 1e-9)
    # Quadrants: A UL, B UR, C LR, D LL  (Thermo-like)
    a = base - gx + gy
    b = base + gx + gy
    c = base + gx - gy
    d = base - gx - gy
    out = {}
    for name, arr in (("DF4-A", a), ("DF4-B", b), ("DF4-C", c), ("DF4-D", d)):
        arr = np.clip(arr, 0, None)
        arr = arr / (arr.max() + 1e-12)
        out[name] = (arr * 8000 + 200).astype(np.uint16)
    return out


def make_drift_stack(haadf: np.ndarray, n_frames: int = 12, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    src = haadf.astype(np.float64)
    h, w = src.shape
    # Use a crop so shifts stay in-frame
    ch, cw = 128, 128
    y0, x0 = (h - ch) // 2, (w - cw) // 2
    frames = []
    for i in range(n_frames):
        dy = int(round(2.2 * np.sin(i / 2.4) + rng.normal(0, 0.3)))
        dx = int(round(1.8 * np.cos(i / 2.1) + 0.35 * i + rng.normal(0, 0.3)))
        yy0 = np.clip(y0 + dy, 0, h - ch)
        xx0 = np.clip(x0 + dx, 0, w - cw)
        frame = src[yy0 : yy0 + ch, xx0 : xx0 + cw].copy()
        frame += rng.normal(0, 90, frame.shape)
        frames.append(np.clip(frame, 0, 65535))
    return np.stack(frames, axis=0).astype(np.uint16)


def make_spectrum_image(
    size: int = 32,
    n_channels: int = 1024,
    e_scale: float = 0.02,
    seed: int = 5,
) -> tuple[np.ndarray, dict[str, float]]:
    """Au particle on SiNx / C support with a Cu grid bar. Channels cover 0–20.48 keV."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    cy, cx = size * 0.45, size * 0.55
    particle = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * 6.5**2))
    support = 0.55 + 0.15 * np.exp(-((yy - size / 2) ** 2) / (2 * 18**2))
    cu_bar = np.zeros((size, size), dtype=np.float64)
    cu_bar[:, : max(3, size // 8)] = 1.0
    carbon = 0.8 - 0.4 * particle

    lines = {
        "C_Ka": 0.277,
        "N_Ka": 0.392,
        "O_Ka": 0.525,
        "Si_Ka": 1.740,
        "Au_Ma": 2.123,
        "Cu_Ka": 8.048,
        "Cu_Kb": 8.905,
        "Au_La": 9.713,
        "Au_Lb": 11.442,
    }
    weights = {
        "C_Ka": 180 * carbon,
        "N_Ka": 90 * support,
        "O_Ka": 40 * support,
        "Si_Ka": 220 * support,
        "Au_Ma": 260 * particle,
        "Cu_Ka": 200 * cu_bar,
        "Cu_Kb": 40 * cu_bar,
        "Au_La": 210 * particle,
        "Au_Lb": 70 * particle,
    }
    energy = np.arange(n_channels) * e_scale
    cube = np.zeros((size, size, n_channels), dtype=np.float32)
    # Bremsstrahlung-like background
    bg = 18.0 * np.exp(-energy / 6.5) + 4.0
    sigma = 0.065
    for name, e0 in lines.items():
        peak = np.exp(-((energy - e0) ** 2) / (2 * sigma**2))
        cube += weights[name][:, :, None] * peak[None, None, :]
    cube += bg[None, None, :]
    cube = rng.poisson(np.clip(cube, 0.1, None)).astype(np.float32)
    return cube, {"energy_scale_kev": e_scale, "energy_offset_kev": 0.0}


def make_four_d(
    scan: int = 12,
    qsize: int = 24,
    seed: int = 7,
) -> np.ndarray:
    """CBED-like disks whose center of mass follows a synthetic DPC field."""
    rng = np.random.default_rng(seed)
    phase = make_phase_object(scan)
    gy, gx = np.gradient(phase)
    gx = gx / (np.max(np.abs(gx)) + 1e-9)
    gy = gy / (np.max(np.abs(gy)) + 1e-9)
    yy, xx = np.mgrid[0:qsize, 0:qsize].astype(np.float64)
    cy0 = cx0 = qsize / 2.0
    radius = 4.2
    cube = np.zeros((scan, scan, qsize, qsize), dtype=np.float32)
    for iy in range(scan):
        for ix in range(scan):
            cy = cy0 + 2.2 * gy[iy, ix]
            cx = cx0 + 2.2 * gx[iy, ix]
            disk = ((yy - cy) ** 2 + (xx - cx) ** 2) <= radius**2
            pattern = disk.astype(np.float64) * 80.0
            pattern += 4.0
            pattern += rng.normal(0, 1.2, pattern.shape)
            cube[iy, ix] = np.clip(pattern, 0, None)
    return cube


def generate_synthetic_bundle(seed: int = 1) -> dict[str, np.ndarray | dict]:
    haadf = make_haadf_lattice(seed=seed)
    bf = make_bf_image(haadf)
    segs = make_segmented_detectors()
    stack = make_drift_stack(haadf, seed=seed + 2)
    si, si_meta = make_spectrum_image(seed=seed + 4)
    fourd = make_four_d(seed=seed + 6)
    return {
        "HAADF": haadf,
        "BF": bf,
        **segs,
        "HAADF Series": stack,
        "EDS SI": si,
        "4D-STEM": fourd,
        "_si_meta": si_meta,
    }


def write_synthetic_emd(path: str | Path, seed: int = 1) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = generate_synthetic_bundle(seed=seed)
    si_meta = bundle.pop("_si_meta")
    with h5py.File(path, "w") as handle:
        handle.attrs["Version"] = "11"
        handle.attrs["Format"] = "Velox"
        handle.attrs["Generator"] = "OpenVelox"
        handle.create_dataset(
            "Version",
            data=np.array([b'{\n    "version": "11",\n    "format": "Velox"\n}\n'], dtype=object),
        )
        handle.create_dataset(
            "ExperimentalMetadata",
            data=np.bytes_("Talos F200X - synthetic OpenVelox demonstration dataset"),
        )
        images = handle.create_group("Data/Image")
        si_root = handle.create_group("Data/SpectrumImage")
        stream_root = handle.create_group("Data/SpectrumStream")
        fourd_root = handle.create_group("Data/FourDSTEM")
        handle.create_group("Operations")
        handle.create_group("Displays/ImageDisplay")

        image_names = ["HAADF", "BF", "DF4-A", "DF4-B", "DF4-C", "DF4-D", "HAADF Series"]
        for name in image_names:
            data = bundle[name]
            meta = build_velox_metadata(
                display_name=name,
                detector=name.split()[0],
                hv_v=DEFAULT_HV,
                mag=DEFAULT_MAG,
                pixel_m=DEFAULT_PIXEL_M,
                dwell_s=DEFAULT_DWELL,
            )
            write_dataset_group(images, data, meta)

        si = bundle["EDS SI"]
        meta = build_velox_metadata(
            display_name="EDS SI",
            detector="Super-X",
            hv_v=DEFAULT_HV,
            mag=DEFAULT_MAG,
            pixel_m=DEFAULT_PIXEL_M * (192 / 32),
            dwell_s=4e-5,
        )
        write_dataset_group(
            si_root,
            si,
            meta,
            attrs={
                "energy_scale_kev": float(si_meta["energy_scale_kev"]),
                "energy_offset_kev": float(si_meta["energy_offset_kev"]),
            },
        )
        # Also store a Velox-accurate sparse SpectrumStream (same cube).
        # Compact stream (downsampled) so the sample stays small.
        stream_cube = np.clip(si[::2, ::2, :512], 0, 3).astype(np.uint16)
        write_spectrum_stream_group(
            stream_root,
            stream_cube,
            meta,
            energy_scale_kev=float(si_meta["energy_scale_kev"]),
            energy_offset_kev=float(si_meta["energy_offset_kev"]),
        )

        fourd = bundle["4D-STEM"]
        meta = build_velox_metadata(
            display_name="4D-STEM",
            detector="EMPAD",
            hv_v=DEFAULT_HV,
            mag=DEFAULT_MAG,
            pixel_m=DEFAULT_PIXEL_M * (192 / 12),
            dwell_s=1e-3,
        )
        write_dataset_group(fourd_root, fourd, meta)
    return path


def generate_synthetic_emd(directory: str | Path | None = None, seed: int = 1) -> Path:
    from openvelox.paths import bundled_sample_emd, writable_dir

    if directory is None:
        directory = writable_dir(Path.cwd() / "samples")
        bundled = bundled_sample_emd()
        dest = directory / "synthetic_velox.emd"
        if bundled is not None and not dest.is_file():
            import shutil

            try:
                shutil.copy2(bundled, dest)
                return dest
            except OSError:
                pass
        if dest.is_file():
            return dest
    else:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
    path = Path(directory) / "synthetic_velox.emd"
    return write_synthetic_emd(path, seed=seed)


def load_or_create_sample(directory: str | Path | None = None) -> ExperimentFile:
    path = generate_synthetic_emd(directory)
    return read_emd(path)
