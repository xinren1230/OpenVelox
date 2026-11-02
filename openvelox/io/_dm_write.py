"""Write a compact little-endian DM3 that OpenVelox can read back."""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

import numpy as np

_TYPE = {
    np.dtype("int16"): 2,
    np.dtype("int32"): 3,
    np.dtype("uint16"): 4,
    np.dtype("uint32"): 5,
    np.dtype("float32"): 6,
    np.dtype("float64"): 7,
    np.dtype("int8"): 8,
}


def _pack_be(fmt: str, *vals: object) -> bytes:
    return struct.pack(">" + fmt, *vals)


def _write_name(name: str) -> bytes:
    raw = name.encode("latin1")
    return _pack_be("H", len(raw)) + raw


def _write_entry(name: str, info: list[int], payload: bytes) -> bytes:
    body = b"%%%%" + _pack_be("I", len(info))
    for item in info:
        body += _pack_be("I", item)
    body += payload
    return _pack_be("B", 21) + _write_name(name) + body


def _write_group(name: str, children: bytes, n_tags: int) -> bytes:
    inner = _pack_be("BBI", 0, 0, n_tags) + children
    if name == "":
        return inner
    return _pack_be("B", 20) + _write_name(name) + inner


def _int_entry(name: str, value: int) -> bytes:
    return _write_entry(name, [3], struct.pack("<i", int(value)))


def _float_entry(name: str, value: float) -> bytes:
    return _write_entry(name, [7], struct.pack("<d", float(value)))


def _str_entry(name: str, value: str) -> bytes:
    raw = value.encode("latin1")
    return _write_entry(name, [18, len(raw)], raw)


def write_dm3(path: str | Path, image: np.ndarray, scale_m: float = 1e-9) -> None:
    image = np.ascontiguousarray(image)
    if image.ndim != 2:
        raise ValueError("Only 2-D images are supported")
    height, width = image.shape
    arr = image
    if arr.dtype not in {np.dtype("uint16"), np.dtype("float32"), np.dtype("float64"), np.dtype("int32")}:
        arr = arr.astype(np.float32)
    tag_type = _TYPE[arr.dtype]
    payload = arr.tobytes(order="C")

    dim_children = _int_entry("0", width) + _int_entry("1", height)
    dims = _write_group("Dimensions", dim_children, 2)

    calib_dim0 = _write_group(
        "0",
        _float_entry("Scale", scale_m) + _str_entry("Units", "m"),
        2,
    )
    calib_dim = _write_group("Dimension", calib_dim0, 1)
    calib = _write_group("Calibrations", calib_dim, 1)

    data_entry = _write_entry("Data", [20, tag_type, arr.size], payload)
    image_data = _write_group("ImageData", data_entry + dims + calib, 3)
    image_tags = _write_group(
        "ImageTags",
        _write_group(
            "Microscope Info",
            _float_entry("Voltage", 200000.0) + _float_entry("Magnification", 320000.0),
            2,
        ),
        1,
    )
    image0 = _write_group("0", image_data + image_tags, 2)
    image_list = _write_group("ImageList", image0, 1)
    root_inner = _pack_be("BBI", 0, 0, 1) + image_list

    header = _pack_be("I", 3) + _pack_be("I", len(root_inner)) + _pack_be("I", 1)
    Path(path).write_bytes(header + root_inner)
