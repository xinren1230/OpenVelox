"""Lazy HDF5-backed arrays so large Velox files are not fully loaded on open."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

Loader = Callable[[], np.ndarray]

# Arrays larger than this materialize through a numpy.memmap instead of RAM.
_DEFAULT_MMAP_ELEMS = 2_000_000


def mmap_threshold() -> int:
    raw = os.environ.get("OPENVELOX_MMAP_ELEMS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_MMAP_ELEMS


def mmap_dir() -> Path:
    override = os.environ.get("OPENVELOX_MMAP_DIR")
    if override:
        folder = Path(override)
    else:
        from openvelox.paths import user_data_dir

        folder = user_data_dir() / "mmap"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class LazyArray:
    """Numpy-compatible proxy that materializes once and then caches."""

    def __init__(
        self,
        loader: Loader,
        shape: tuple[int, ...],
        dtype: np.dtype | type = np.float64,
        *,
        label: str = "",
        slicer: Callable[..., np.ndarray] | None = None,
    ) -> None:
        self._loader = loader
        self._shape = tuple(int(n) for n in shape)
        self._dtype = np.dtype(dtype)
        self._cache: np.ndarray | None = None
        self._slicer = slicer
        self.label = label

    @property
    def shape(self) -> tuple[int, ...]:
        return self._shape

    @property
    def ndim(self) -> int:
        return len(self._shape)

    @property
    def dtype(self) -> np.dtype:
        return self._dtype

    @property
    def size(self) -> int:
        n = 1
        for s in self._shape:
            n *= s
        return n

    def materialized(self) -> bool:
        return self._cache is not None

    def has_slicer(self) -> bool:
        return self._slicer is not None

    def materialize(self) -> np.ndarray:
        if self._cache is None:
            if self.size >= mmap_threshold():
                self._cache = self._materialize_mmap()
            else:
                arr = np.asarray(self._loader())
                self._cache = arr
            self._shape = tuple(int(n) for n in self._cache.shape)
            self._dtype = self._cache.dtype
        return self._cache

    def _materialize_mmap(self) -> np.ndarray:
        """Fill a memmap file, row-chunks via the slicer when possible."""
        import hashlib

        key = f"{self.label}:{self._shape}:{self._dtype}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        path = mmap_dir() / f"{digest}.npy"
        dtype = np.dtype(self._dtype)
        if path.is_file() and path.stat().st_size == int(np.prod(self._shape)) * dtype.itemsize:
            return np.memmap(path, dtype=dtype, mode="r", shape=self._shape)
        mm = np.memmap(path, dtype=dtype, mode="w+", shape=self._shape)
        try:
            if self._slicer is not None and len(self._shape) >= 2:
                step = max(1, min(16, int(self._shape[0])))
                for y0 in range(0, int(self._shape[0]), step):
                    y1 = min(int(self._shape[0]), y0 + step)
                    mm[y0:y1] = np.asarray(self._slicer(slice(y0, y1)), dtype=dtype)
            else:
                mm[:] = np.asarray(self._loader(), dtype=dtype)
            mm.flush()
        except Exception:
            del mm
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return np.asarray(self._loader())
        return np.memmap(path, dtype=dtype, mode="r", shape=self._shape)

    def __array__(self, dtype: Any = None) -> np.ndarray:
        arr = self.materialize()
        return np.asarray(arr, dtype=dtype) if dtype is not None else arr

    def __getitem__(self, item: Any) -> np.ndarray:
        if self._cache is not None:
            return self._cache[item]
        if self._slicer is not None:
            try:
                return np.asarray(self._slicer(item))
            except Exception:
                pass
        return self.materialize()[item]

    def __len__(self) -> int:
        return int(self._shape[0]) if self._shape else 0


def as_array(data: Any) -> np.ndarray:
    if isinstance(data, LazyArray):
        return data.materialize()
    return np.asarray(data)


def sum_lazy_si(lazy: LazyArray, row_chunk: int = 8) -> np.ndarray:
    """Sum a lazy (y, x, energy) cube without a full in-RAM materialize."""
    if lazy.ndim != 3:
        raise ValueError("Spectrum image must be (y, x, energy)")
    sy, _sx, nch = lazy.shape
    acc = np.zeros(int(nch), dtype=np.float64)
    step = max(1, int(row_chunk))
    for y0 in range(0, int(sy), step):
        y1 = min(int(sy), y0 + step)
        slab = np.asarray(lazy[y0:y1], dtype=np.float64)
        acc += slab.sum(axis=(0, 1))
    return acc


def iter_4d_rows(cube: Any, row_chunk: int = 1):
    """Yield ``(y0, y1, slab)`` of a 4D cube, using a slicer when available."""
    if isinstance(cube, LazyArray) and cube.ndim == 4 and cube.has_slicer() and not cube.materialized():
        sy = int(cube.shape[0])
        step = max(1, int(row_chunk))
        for y0 in range(0, sy, step):
            y1 = min(sy, y0 + step)
            yield y0, y1, np.asarray(cube[y0:y1], dtype=np.float64)
        return
    arr = np.asarray(cube, dtype=np.float64)
    if arr.ndim != 4:
        raise ValueError("4D-STEM cube must be (sy, sx, qy, qx)")
    yield 0, arr.shape[0], arr


def h5_loader(path: str | Path, inner: str) -> Loader:
    path = str(path)

    def _load() -> np.ndarray:
        import h5py

        with h5py.File(path, "r") as handle:
            return np.asarray(handle[inner][()])

    return _load


def h5_slicer(path: str | Path, inner: str) -> Callable[..., np.ndarray]:
    """Read a hyperslab from an on-disk HDF5 dataset without the full cube."""
    path = str(path)

    def _slice(item: Any) -> np.ndarray:
        import h5py

        with h5py.File(path, "r") as handle:
            return np.asarray(handle[inner][item])

    return _slice
