"""In-memory experiment / dataset model used by I/O and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from openvelox.io.lazy import LazyArray, as_array


class DatasetKind(str, Enum):
    IMAGE = "image"
    STACK = "stack"
    SPECTRUM = "spectrum"
    SPECTRUM_IMAGE = "spectrum_image"
    FOUR_D = "four_d"


@dataclass
class Axis:
    name: str
    size: int
    scale: float = 1.0
    offset: float = 0.0
    units: str = "px"

    def coordinates(self) -> np.ndarray:
        return self.offset + np.arange(self.size, dtype=np.float64) * self.scale

    def label(self) -> str:
        return f"{self.name} ({self.units})" if self.units else self.name


@dataclass
class Dataset:
    name: str
    kind: DatasetKind
    data: Any
    axes: list[Axis] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    group_id: str = ""
    detector: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DatasetKind):
            self.kind = DatasetKind(self.kind)
        if not isinstance(self.data, LazyArray):
            self.data = np.asarray(self.data)
        if not self.axes:
            self.axes = [
                Axis(name=f"axis{i}", size=int(n)) for i, n in enumerate(self.shape)
            ]

    def materialize(self) -> np.ndarray:
        arr = as_array(self.data)
        self.data = arr
        return arr

    @property
    def shape(self) -> tuple[int, ...]:
        if isinstance(self.data, LazyArray):
            return self.data.shape
        return tuple(int(n) for n in np.asarray(self.data).shape)

    def pixel_size_m(self) -> float:
        for ax in self.axes:
            if ax.units in {"m", "meter", "metres"} and ax.scale > 0:
                return float(ax.scale)
            if ax.units in {"nm", "nanometer"}:
                return float(ax.scale) * 1e-9
            if ax.units in {"µm", "um", "micron"}:
                return float(ax.scale) * 1e-6
            if ax.units in {"Å", "A", "angstrom"}:
                return float(ax.scale) * 1e-10
        meta = self.metadata
        for key in ("pixel_size_m", "PixelSize", "pixel_size"):
            if key in meta:
                try:
                    return float(meta[key])
                except (TypeError, ValueError):
                    continue
        return 1.0

    def is_large(self, max_pixels: int = 512 * 512) -> bool:
        """True when a full materialize would stall the first paint."""
        shape = self.shape
        if self.kind is DatasetKind.SPECTRUM_IMAGE and len(shape) == 3:
            return int(shape[0]) * int(shape[1]) > max_pixels or int(shape[2]) > 2048
        if self.kind is DatasetKind.FOUR_D and len(shape) == 4:
            return int(shape[0]) * int(shape[1]) > 32 * 32 or int(shape[2]) * int(shape[3]) > 128 * 128
        if self.kind is DatasetKind.STACK and len(shape) == 3:
            return int(shape[1]) * int(shape[2]) > max_pixels
        if len(shape) == 2:
            return int(shape[0]) * int(shape[1]) > max_pixels
        return False

    def image2d(self, index: int = 0, preview: bool = False, max_side: int = 1024) -> np.ndarray:
        """Best 2-D view for the image canvas.

        ``preview=True`` uses spatial / spectral stride so large SI and 4D
        cubes can paint before the full cube is in RAM. Stack frames prefer
        ``data[index]`` (HDF5 slicer) over materializing the series.
        """
        from openvelox.processing.preview import downsample2d, preview_sum_si, preview_virtual_bf, stride_for

        if self.kind is DatasetKind.STACK and len(self.shape) == 3:
            index = int(np.clip(index, 0, self.shape[0] - 1))
            try:
                frame = np.asarray(self.data[index], dtype=np.float64)
                if frame.ndim == 2:
                    return downsample2d(frame, max_side) if preview else frame
            except Exception:
                pass

        if preview and self.kind is DatasetKind.SPECTRUM_IMAGE and len(self.shape) == 3:
            try:
                if isinstance(self.data, LazyArray) and not self.data.materialized() and self.data.has_slicer():
                    step = stride_for(self.shape[:2], max_side)
                    chunk = np.asarray(self.data[::step, ::step, ::4], dtype=np.float64)
                    return np.asarray(chunk.sum(axis=-1), dtype=np.float64)
            except Exception:
                pass

        if preview and self.kind is DatasetKind.FOUR_D and len(self.shape) == 4:
            try:
                if isinstance(self.data, LazyArray) and not self.data.materialized() and self.data.has_slicer():
                    step = stride_for(self.shape[:2], min(max_side, 256))
                    chunk = np.asarray(self.data[::step, ::step], dtype=np.float64)
                    return preview_virtual_bf(chunk, max_side=min(max_side, 256))
            except Exception:
                pass

        arr = np.asarray(self.materialize(), dtype=np.float64)
        if arr.ndim == 2:
            return downsample2d(arr, max_side) if preview else arr
        if self.kind is DatasetKind.STACK and arr.ndim == 3:
            index = int(np.clip(index, 0, arr.shape[0] - 1))
            frame = arr[index]
            return downsample2d(frame, max_side) if preview else frame
        if self.kind is DatasetKind.SPECTRUM_IMAGE and arr.ndim == 3:
            return preview_sum_si(arr, max_side=max_side) if preview else arr.sum(axis=-1)
        if self.kind is DatasetKind.FOUR_D and arr.ndim == 4:
            if preview:
                return preview_virtual_bf(arr, max_side=min(max_side, 256))
            cy, cx = arr.shape[2] // 2, arr.shape[3] // 2
            yy, xx = np.ogrid[: arr.shape[2], : arr.shape[3]]
            mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= (max(arr.shape[2], arr.shape[3]) / 6) ** 2
            return arr[:, :, mask].sum(axis=-1)
        if arr.ndim == 1:
            return arr.reshape(1, -1)
        return arr.reshape(arr.shape[0], -1)

    def n_frames(self) -> int:
        if self.kind is DatasetKind.STACK and len(self.shape) >= 3:
            return int(self.shape[0])
        return 1

    def display_name(self) -> str:
        det = self.detector or self.metadata.get("detector", "")
        if det and det not in self.name:
            return f"{self.name} [{det}]"
        return self.name


@dataclass
class ExperimentFile:
    path: str
    name: str
    datasets: list[Dataset] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
