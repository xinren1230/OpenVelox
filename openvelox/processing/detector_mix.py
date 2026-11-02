"""Weight and sum Super-X EDS detectors and multi-segment STEM images."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np

from openvelox.models import Dataset, DatasetKind


SUPERX_ALIASES = ("super-x", "superx", "super x", "eds stream", "edx")
DF_ALIASES = ("df4", "df-4", "segment")


def normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    out = {str(k): max(0.0, float(v)) for k, v in weights.items()}
    total = sum(out.values())
    if total <= 0:
        n = max(len(out), 1)
        return {k: 1.0 / n for k in out} or {}
    return {k: v / total for k, v in out.items()}


def mix_arrays(
    arrays: Mapping[str, np.ndarray],
    weights: Mapping[str, float] | None = None,
) -> np.ndarray:
    """Weighted sum of named arrays. All shapes must match."""
    if not arrays:
        raise ValueError("No arrays to mix")
    names = list(arrays)
    first = np.asarray(arrays[names[0]], dtype=np.float64)
    for name in names[1:]:
        arr = np.asarray(arrays[name], dtype=np.float64)
        if arr.shape != first.shape:
            raise ValueError(f"Shape mismatch: {name} {arr.shape} vs {first.shape}")
    w = normalize_weights(weights or {n: 1.0 for n in names})
    acc = np.zeros(first.shape, dtype=np.float64)
    for name in names:
        acc += float(w.get(name, 0.0)) * np.asarray(arrays[name], dtype=np.float64)
    return acc


def mix_spectrum_images(
    cubes: Mapping[str, np.ndarray],
    weights: Mapping[str, float] | None = None,
) -> np.ndarray:
    mixed = mix_arrays(cubes, weights)
    if mixed.ndim != 3:
        raise ValueError("Spectrum images must be (y, x, energy)")
    return mixed


def is_superx_dataset(ds: Dataset) -> bool:
    if ds.kind is not DatasetKind.SPECTRUM_IMAGE:
        return False
    if str(ds.metadata.get("detector_family") or "").lower() == "superx":
        return True
    if ds.group_id in {"sum", ""} and "stream" in ds.name.lower() and "sum" in ds.name.lower():
        return False
    name = ds.name.lower()
    if "eds si (stream)" in name or name.startswith("eds si"):
        return False
    blob = " ".join(
        [
            ds.name,
            str(ds.metadata.get("display_name") or ""),
        ]
    ).lower()
    return any(alias in blob for alias in SUPERX_ALIASES)


def is_segment_dataset(ds: Dataset) -> bool:
    if ds.kind not in {DatasetKind.IMAGE, DatasetKind.STACK}:
        return False
    name = f"{ds.name} {ds.detector}".lower()
    if name.startswith("df4") or "df4-" in name:
        return True
    return any(alias in name for alias in DF_ALIASES) and any(
        tag in name for tag in ("-a", "-b", "-c", "-d", " a", " b", " c", " d")
    )


def group_detector_datasets(datasets: Iterable[Any]) -> dict[str, list[Dataset]]:
    """Split open datasets into Super-X SI cubes and DF4-style STEM segments."""
    superx: list[Dataset] = []
    df4: list[Dataset] = []
    for ds in datasets:
        if not isinstance(ds, Dataset):
            continue
        if is_superx_dataset(ds):
            superx.append(ds)
        elif is_segment_dataset(ds):
            df4.append(ds)
    return {"superx": superx, "df4": df4}
