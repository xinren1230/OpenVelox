"""Minimal DigitalMicrograph .dm3 / .dm4 reader."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np

from openvelox.models import Axis, Dataset, DatasetKind, ExperimentFile

_SIMPLE = {
    2: ("h", 2, np.int16),
    3: ("i", 4, np.int32),
    4: ("H", 2, np.uint16),
    5: ("I", 4, np.uint32),
    6: ("f", 4, np.float32),
    7: ("d", 8, np.float64),
    8: ("B", 1, np.int8),
    9: ("b", 1, np.int8),
    10: ("B", 1, np.int8),
    11: ("Q", 8, np.uint64),
    12: ("q", 8, np.int64),
}


class _DMReader:
    def __init__(self, fh: BinaryIO) -> None:
        self.fh = fh
        version = struct.unpack(">I", fh.read(4))[0]
        if version not in (3, 4):
            raise ValueError(f"Unsupported DM version {version}")
        self.version = version
        self.size_fmt = ">Q" if version == 4 else ">I"
        self.size_t = 8 if version == 4 else 4
        _root_size = struct.unpack(self.size_fmt, fh.read(self.size_t))[0]
        endian = struct.unpack(">I", fh.read(4))[0]
        self.le = bool(endian)
        self.endian = "<" if self.le else ">"

    def _u(self, fmt: str) -> Any:
        raw = self.fh.read(struct.calcsize(fmt))
        return struct.unpack(fmt, raw)[0]

    def _read_name(self) -> str:
        n = self._u(">H")
        if n == 0:
            return ""
        return self.fh.read(n).decode("latin1", errors="replace")

    def _read_tag_group(self) -> dict[str, Any]:
        self.fh.read(2)  # sorted + open
        n_tags = self._u(self.size_fmt)
        out: dict[str, Any] = {}
        unnamed = 0
        for _ in range(int(n_tags)):
            kind = self._u(">B")
            name = self._read_name() or f"unnamed_{unnamed}"
            if not name.startswith("unnamed"):
                pass
            else:
                unnamed += 1
            if self.version == 4:
                self.fh.read(self.size_t)  # tag size
            if kind == 20:
                out[name] = self._read_tag_group()
            elif kind == 21:
                out[name] = self._read_tag_entry()
            else:
                break
        return out

    def _read_tag_entry(self) -> Any:
        delim = self.fh.read(4)
        if delim != b"%%%%":
            raise ValueError("Corrupt DM tag (missing %%%%)")
        n_info = int(self._u(self.size_fmt))
        info = [int(self._u(self.size_fmt)) for _ in range(n_info)]
        return self._read_data(info)

    def _read_data(self, info: list[int]) -> Any:
        if not info:
            return None
        tag = info[0]
        if tag == 15:
            return self._read_struct(info)
        if tag == 20:
            return self._read_array(info)
        if tag in _SIMPLE:
            fmt, _size, _np = _SIMPLE[tag]
            return self._u(self.endian + fmt)
        if tag == 18:  # string
            n = info[1] if len(info) > 1 else 0
            return self.fh.read(n).decode("latin1", errors="replace")
        return None

    def _read_struct(self, info: list[int]) -> dict[str, Any]:
        # 15, name_len, n_fields, (name_len, type)* , then values
        idx = 2
        n_fields = info[idx] if len(info) > idx else 0
        idx += 1
        types: list[int] = []
        for _ in range(n_fields):
            idx += 1  # name length
            if idx < len(info):
                types.append(info[idx])
                idx += 1
        values = []
        for t in types:
            if t in _SIMPLE:
                fmt, _s, _np = _SIMPLE[t]
                values.append(self._u(self.endian + fmt))
            else:
                values.append(None)
        return {f"f{i}": v for i, v in enumerate(values)}

    def _read_array(self, info: list[int]) -> Any:
        # 20, etype, ..., length
        if len(info) < 3:
            return np.array([])
        etype = info[1]
        length = int(info[-1])
        if etype in _SIMPLE:
            _fmt, size, dtype = _SIMPLE[etype]
            buf = self.fh.read(size * length)
            arr = np.frombuffer(buf, dtype=dtype)
            if not self.le:
                arr = arr.byteswap().newbyteorder()
            return arr
        if etype == 15:
            # array of structs — skip payload if possible
            return np.array([])
        return np.array([])

    def parse(self) -> dict[str, Any]:
        return self._read_tag_group()


def _find_image_dicts(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if not isinstance(node, dict):
        return found
    if "ImageData" in node:
        found.append(node)
    for value in node.values():
        found.extend(_find_image_dicts(value))
    return found


def _image_from_tags(tags: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    candidates = _find_image_dicts(tags)
    if not candidates:
        raise ValueError("No ImageData in DM file")
    image = candidates[-1]
    data_grp = image["ImageData"]
    raw = np.asarray(data_grp.get("Data"))
    dims = data_grp.get("Dimensions") or {}
    shape: list[int] = []
    if isinstance(dims, dict):
        def _dim_key(item: str) -> int:
            digits = "".join(ch for ch in str(item) if ch.isdigit())
            return int(digits) if digits else 0

        keys = sorted(dims.keys(), key=_dim_key)
        shape = [int(dims[k]) for k in keys]
    # Gatan Dimensions[0] = x (width), Dimensions[1] = y (height), x-fastest.
    if len(shape) == 2 and raw.size == shape[0] * shape[1]:
        arr = raw.reshape(shape[1], shape[0])
    elif len(shape) == 3 and raw.size == int(np.prod(shape)):
        arr = raw.reshape(shape[2], shape[1], shape[0])
    else:
        arr = raw
    meta: dict[str, Any] = {}
    calib = data_grp.get("Calibrations") or {}
    dim_cal = calib.get("Dimension") if isinstance(calib, dict) else None
    scale = 1.0
    units = "px"
    if isinstance(dim_cal, dict):
        first = next(iter(dim_cal.values()), None)
        if isinstance(first, dict):
            scale = float(first.get("Scale", 1.0) or 1.0)
            units = str(first.get("Units", "px") or "px")
    meta["pixel_size_m"] = _dm_unit_to_m(scale, units)
    meta["pixel_unit_x"] = "m" if meta["pixel_size_m"] != scale else units
    img_tags = image.get("ImageTags") or {}
    meta.update(_flatten_dm_tags(img_tags))
    return np.asarray(arr), meta


def _dm_unit_to_m(scale: float, units: str) -> float:
    u = units.strip().lower()
    if u in {"m", "meter", "metres"}:
        return scale
    if u in {"nm", "nanometer", "nanometre"}:
        return scale * 1e-9
    if u in {"µm", "um", "micron", "micrometer"}:
        return scale * 1e-6
    if u in {"å", "a", "angstrom", "ang"}:
        return scale * 1e-10
    if u in {"pm"}:
        return scale * 1e-12
    return scale


def _flatten_dm_tags(tags: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(tags, dict):
        return out
    for key, value in tags.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten_dm_tags(value, name + "/"))
        elif not isinstance(value, np.ndarray):
            out[name] = value
    # Common microscope paths
    for path, dest in (
        ("Microscope Info/Voltage", "high_tension_v"),
        ("Microscope Info/Magnification", "magnification"),
        ("Acquisition/Parameters/High Level/Analog Dwell", "dwell_time_s"),
    ):
        if path in out:
            try:
                out[dest] = float(out[path])
            except (TypeError, ValueError):
                out[dest] = out[path]
    return out


def read_dm(path: str | Path) -> ExperimentFile:
    path = Path(path)
    with path.open("rb") as fh:
        tags = _DMReader(fh).parse()
    arr, meta = _image_from_tags(tags)
    kind = DatasetKind.STACK if arr.ndim == 3 else DatasetKind.IMAGE
    if arr.ndim == 1:
        kind = DatasetKind.SPECTRUM
    px = float(meta.get("pixel_size_m") or 1.0)
    if arr.ndim == 2:
        axes = [Axis("y", arr.shape[0], px, units="m"), Axis("x", arr.shape[1], px, units="m")]
    elif arr.ndim == 3:
        axes = [
            Axis("frame", arr.shape[0], 1.0, units="frame"),
            Axis("y", arr.shape[1], px, units="m"),
            Axis("x", arr.shape[2], px, units="m"),
        ]
    else:
        axes = [Axis("energy", arr.shape[0], 1.0, units="ch")]
    ds = Dataset(
        name=path.stem,
        kind=kind,
        data=arr,
        axes=axes,
        metadata=meta,
        source_path=str(path),
        group_id="0",
    )
    return ExperimentFile(path=str(path), name=path.name, datasets=[ds])


def write_simple_dm3(path: str | Path, image: np.ndarray, scale_m: float = 1e-9) -> None:
    """Write a tiny little-endian DM3 (ImageList only) for tests."""
    image = np.asarray(image)
    if image.ndim != 2:
        raise ValueError("write_simple_dm3 only supports 2-D images")
    # Use a well-tested approach: write via a compact builder
    from openvelox.io._dm_write import write_dm3

    write_dm3(path, image, scale_m)
