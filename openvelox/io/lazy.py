"""Lazy HDF5-backed arrays so large Velox files are not fully loaded on open."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

Loader = Callable[[], np.ndarray]


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
            arr = np.asarray(self._loader())
            self._cache = arr
            self._shape = tuple(int(n) for n in arr.shape)
            self._dtype = arr.dtype
        return self._cache

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
