"""Small process-wide cache for decoded streams and display rasters."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Hashable

import numpy as np


@lru_cache(maxsize=32)
def _cached_key(key: Hashable) -> Hashable:
    return key


_STORE: dict[Hashable, np.ndarray] = {}


def cache_get(key: Hashable) -> np.ndarray | None:
    arr = _STORE.get(key)
    return None if arr is None else arr


def cache_put(key: Hashable, array: np.ndarray) -> np.ndarray:
    _STORE[key] = array
    return array


def cache_clear() -> None:
    _STORE.clear()


def memoize_array(key: Hashable, factory) -> np.ndarray:
    hit = cache_get(key)
    if hit is not None:
        return hit
    arr = np.asarray(factory())
    return cache_put(key, arr)
