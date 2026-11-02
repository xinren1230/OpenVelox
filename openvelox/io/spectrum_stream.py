"""Thermo Fisher Velox SpectrumStream codec.

Velox stores EDS spectrum images as a sparse uint16 event stream
(FEI / HyperSpy / RosettaSciIO convention):

* values ``< 65535`` are energy-channel hits in the current pixel
* ``65535`` (gate pulse) advances to the next pixel in raster order (x fastest)
* ``FrameLocationTable`` gives the first stream index of each frame
* ``AcquisitionSettings`` JSON supplies ``bincount`` and raster size

Pruned files often keep a stale 128×128 raster in settings while the
actual image (and the number of gate pulses) is smaller — we always
prefer the gate-pulse / image-derived shape.
"""

from __future__ import annotations

from typing import Any

import numpy as np

PIXEL_END = 65535


def decode_spectrum_stream(
    stream: np.ndarray,
    *,
    height: int,
    width: int,
    n_channels: int,
    frame_offsets: np.ndarray | None = None,
    first_frame: int = 0,
    last_frame: int | None = None,
    sum_frames: bool = True,
) -> np.ndarray:
    """Return ``(y, x, energy)`` or ``(frame, y, x, energy)`` counts."""
    stream = np.asarray(stream).reshape(-1)
    height, width, n_channels = int(height), int(width), int(n_channels)
    n_pixels = height * width
    if n_pixels <= 0 or n_channels <= 0:
        raise ValueError("Invalid spectrum-stream geometry")

    if frame_offsets is not None and len(np.asarray(frame_offsets).reshape(-1)) >= 2:
        offs = np.asarray(frame_offsets, dtype=np.int64).reshape(-1)
        n_frames = max(1, offs.size)
        last = n_frames if last_frame is None else min(int(last_frame), n_frames)
        first = max(0, int(first_frame))
        cubes = []
        for f in range(first, last):
            start = int(offs[f])
            end = int(offs[f + 1]) if f + 1 < offs.size else int(stream.size)
            start = max(0, min(start, stream.size))
            end = max(start, min(end, stream.size))
            cubes.append(_accumulate(stream[start:end], height, width, n_channels))
        if not cubes:
            return np.zeros((height, width, n_channels), dtype=np.uint32)
        if sum_frames or len(cubes) == 1:
            out = np.zeros((height, width, n_channels), dtype=np.uint32)
            for cube in cubes:
                out += cube
            return out
        return np.stack(cubes, axis=0)

    cube, n_seen = _accumulate(stream, height, width, n_channels, return_pixels=True)
    if sum_frames:
        return cube
    n_frames = max(1, int(np.ceil(n_seen / max(n_pixels, 1))))
    stacked = np.zeros((n_frames, height, width, n_channels), dtype=np.uint32)
    stacked[0] = cube
    return stacked


def _accumulate(
    stream: np.ndarray,
    height: int,
    width: int,
    n_channels: int,
    return_pixels: bool = False,
) -> np.ndarray | tuple[np.ndarray, int]:
    if stream.size == 0:
        empty = np.zeros((height, width, n_channels), dtype=np.uint32)
        return (empty, 0) if return_pixels else empty
    is_end = stream == PIXEL_END
    pixel_of = np.cumsum(is_end, dtype=np.int64) - is_end.astype(np.int64)
    events = ~is_end
    channels = stream[events].astype(np.int64, copy=False)
    pixels = pixel_of[events]
    n_pixels = height * width
    valid = (channels >= 0) & (channels < n_channels) & (pixels >= 0) & (pixels < n_pixels)
    flat = np.zeros((n_pixels, n_channels), dtype=np.uint32)
    if np.any(valid):
        np.add.at(flat, (pixels[valid], channels[valid]), 1)
    cube = flat.reshape(height, width, n_channels)
    if return_pixels:
        return cube, int(is_end.sum())
    return cube


def infer_stream_shape(
    stream: np.ndarray,
    frame_offsets: np.ndarray | None,
    settings: dict[str, Any],
    fallback_hw: tuple[int, int] | None = None,
) -> tuple[int, int, int, int]:
    """Return ``(height, width, n_channels, n_frames)``."""
    stream = np.asarray(stream).reshape(-1)
    n_channels = int(settings.get("bincount") or settings.get("BinCount") or 4096)
    raster = settings.get("RasterScanDefinition") or {}
    set_w = int(float(raster.get("Width") or raster.get("width") or 0))
    set_h = int(float(raster.get("Height") or raster.get("height") or 0))

    n_ends = int((stream == PIXEL_END).sum())
    if frame_offsets is not None and len(np.asarray(frame_offsets).reshape(-1)) >= 1:
        n_frames = max(1, int(np.asarray(frame_offsets).reshape(-1).size))
        # A table of N offsets usually means N frames (last frame runs to EOF).
    else:
        n_frames = 1

    if fallback_hw:
        fh, fw = fallback_hw
        if fh * fw * n_frames == n_ends or fh * fw == n_ends:
            return fh, fw, n_channels, max(1, n_ends // max(fh * fw, 1))

    if n_frames > 1 and n_ends % n_frames == 0:
        per = n_ends // n_frames
        side = int(round(np.sqrt(per)))
        if side * side == per:
            return side, side, n_channels, n_frames
        if fallback_hw and fallback_hw[0] * fallback_hw[1] == per:
            return fallback_hw[0], fallback_hw[1], n_channels, n_frames

    if set_w and set_h and set_w * set_h * n_frames == n_ends:
        return set_h, set_w, n_channels, n_frames
    if set_w and set_h and set_w * set_h == n_ends:
        return set_h, set_w, n_channels, 1

    if n_ends > 0:
        side = int(round(np.sqrt(n_ends / max(n_frames, 1))))
        if side * side * n_frames == n_ends:
            return side, side, n_channels, n_frames
        side = int(round(np.sqrt(n_ends)))
        if side * side == n_ends:
            return side, side, n_channels, 1

    if fallback_hw:
        return fallback_hw[0], fallback_hw[1], n_channels, n_frames
    if set_w and set_h:
        return set_h, set_w, n_channels, max(1, n_frames)
    return 1, 1, n_channels, 1


def encode_spectrum_stream(cube: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pack ``(y, x, e)`` or ``(f, y, x, e)`` into a Velox stream + frame table."""
    arr = np.asarray(cube)
    if arr.ndim == 3:
        arr = arr[None, ...]
    if arr.ndim != 4:
        raise ValueError("cube must be (y,x,e) or (frame,y,x,e)")
    events: list[int] = []
    offsets = [0]
    for frame in arr:
        for iy in range(frame.shape[0]):
            for ix in range(frame.shape[1]):
                spec = frame[iy, ix]
                chans = np.flatnonzero(spec)
                for ch in chans:
                    count = int(min(int(spec[ch]), 255))
                    if count > 0:
                        events.extend([int(ch)] * count)
                events.append(PIXEL_END)
        offsets.append(len(events))
    stream = np.asarray(events, dtype=np.uint16)
    table = np.asarray(offsets[:-1], dtype=np.uint64)
    return stream, table


def parse_acquisition_settings(raw: Any) -> dict[str, Any]:
    import json

    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, np.ndarray):
        raw = raw.reshape(-1)[0]
    if isinstance(raw, (bytes, bytearray, np.bytes_)):
        raw = bytes(raw).decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return {}
