"""TIA / FEI .ser (and sidecar .emi) reader."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np

from openvelox.models import Axis, Dataset, DatasetKind, ExperimentFile

# Data type IDs used by TIA.
_DTYPE = {
    1: np.uint8,
    2: np.uint16,
    3: np.uint32,
    4: np.int8,
    5: np.int16,
    6: np.int32,
    7: np.float32,
    8: np.float64,
    9: np.complex64,
    10: np.complex128,
}


def _read_emi_pixel_size(emi_path: Path) -> float | None:
    if not emi_path.is_file():
        return None
    try:
        text = emi_path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(text)
    except (ET.ParseError, OSError, UnicodeError):
        try:
            # EMI is often a Windows .NET XML dump with a leading junk header
            raw = emi_path.read_bytes()
            start = raw.find(b"<")
            if start < 0:
                return None
            root = ET.fromstring(raw[start:])
        except (ET.ParseError, OSError):
            return None
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if "pixelsize" in tag or tag in {"xscale", "scale"}:
            if node.text:
                try:
                    return float(node.text)
                except ValueError:
                    continue
    return None


def read_ser(path: str | Path) -> ExperimentFile:
    path = Path(path)
    with path.open("rb") as fh:
        header = fh.read(14)
        if len(header) < 14:
            raise ValueError("Truncated SER file")
        _byte_order, series_id, _series_ver = struct.unpack("<HHI", header[:8])
        data_type_id, _tag_type_id = struct.unpack("<HH", header[8:12])
        # The rest of the official header is 32-bit / 64-bit depending on version.
        fh.seek(0)
        # Common layout used by TIA 4.x (offsets in bytes):
        fh.seek(12)
        total_elements = struct.unpack("<I", fh.read(4))[0]
        valid_elements = struct.unpack("<I", fh.read(4))[0]
        offset_array_offset = struct.unpack("<I", fh.read(4))[0]
        n_dims = struct.unpack("<I", fh.read(4))[0]
        # Skip dimension descriptors (40 bytes typical for v1)
        fh.seek(26 + n_dims * 40) if False else None
        # More reliable: jump to offset array
        if offset_array_offset == 0 or offset_array_offset > path.stat().st_size:
            # Fallback compact header used by our writer
            return _read_simple_ser(path)

        fh.seek(offset_array_offset)
        n_valid = max(1, min(int(valid_elements or total_elements or 1), 4096))
        offsets = struct.unpack("<" + "Q" * n_valid, fh.read(8 * n_valid)) if n_valid else (0,)
        if not offsets or offsets[0] == 0:
            return _read_simple_ser(path)
        fh.seek(offsets[0])
        cal = struct.unpack("<dd", fh.read(16))  # calibration offset/scale maybe
        data_type = struct.unpack("<H", fh.read(2))[0]
        arr_type = _DTYPE.get(data_type, np.float32)
        if data_type_id == 0x4122:
            width, height = struct.unpack("<II", fh.read(8))
            count = width * height
            raw = np.frombuffer(fh.read(count * np.dtype(arr_type).itemsize), dtype=arr_type)
            image = raw.reshape(height, width)
        else:
            n = struct.unpack("<I", fh.read(4))[0]
            image = np.frombuffer(fh.read(n * np.dtype(arr_type).itemsize), dtype=arr_type)

    return _wrap_ser(path, np.asarray(image), pixel_m=None)


def _read_simple_ser(path: Path) -> ExperimentFile:
    """Read the compact OpenVelox SER dialect (and attempt classic TIA)."""
    raw = path.read_bytes()
    if raw[:4] == b"OSER":
        header_size = 32
        height, width = struct.unpack("<II", raw[4:12])
        dtype_code = struct.unpack("<H", raw[12:14])[0]
        pixel_m = struct.unpack("<d", raw[16:24])[0]
        dtype = _DTYPE.get(dtype_code, np.float32)
        data = np.frombuffer(raw[header_size : header_size + height * width * np.dtype(dtype).itemsize], dtype=dtype)
        image = data.reshape(height, width)
        return _wrap_ser(path, image, pixel_m=pixel_m)
    raise ValueError(f"Unrecognized SER layout: {path}")


def _wrap_ser(path: Path, image: np.ndarray, pixel_m: float | None) -> ExperimentFile:
    emi = path.with_suffix(".emi")
    emi_px = _read_emi_pixel_size(emi)
    px = pixel_m if pixel_m else emi_px
    if px is None:
        px = 1e-9
    meta: dict[str, Any] = {
        "pixel_size_m": px,
        "pixel_size_nm": px * 1e9,
        "detector": "TIA",
        "instrument": "FEI TIA",
    }
    ds = Dataset(
        name=path.stem,
        kind=DatasetKind.IMAGE if image.ndim == 2 else DatasetKind.SPECTRUM,
        data=image,
        axes=[
            Axis("y", image.shape[0], px, units="m"),
            Axis("x", image.shape[1], px, units="m"),
        ]
        if image.ndim == 2
        else [Axis("energy", image.shape[0], 1.0, units="ch")],
        metadata=meta,
        source_path=str(path),
        group_id="0",
        detector="TIA",
    )
    return ExperimentFile(path=str(path), name=path.name, datasets=[ds])


def write_simple_ser(path: str | Path, image: np.ndarray, pixel_m: float = 1e-9) -> None:
    """Write a compact SER-like file plus a tiny EMI sidecar for tests."""
    path = Path(path)
    image = np.asarray(image)
    if image.dtype == np.uint16:
        code = 2
    elif image.dtype == np.float64:
        code = 8
    else:
        image = image.astype(np.float32)
        code = 7
    header = b"OSER" + struct.pack("<II", image.shape[0], image.shape[1])
    header += struct.pack("<H", code) + b"\x00\x00" + struct.pack("<d", float(pixel_m))
    header = header.ljust(32, b"\x00")
    path.write_bytes(header + image.tobytes(order="C"))
    emi = path.with_suffix(".emi")
    emi.write_text(
        f'<?xml version="1.0"?><ObjectInfo><PixelSize>{pixel_m}</PixelSize></ObjectInfo>\n',
        encoding="utf-8",
    )
