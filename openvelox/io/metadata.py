"""Helpers for Thermo Fisher / Velox nested metadata JSON."""

from __future__ import annotations

import json
import math
from typing import Any


def unwrap(value: Any) -> Any:
    """Unwrap Velox ``{"type": "...", "value": "..."}`` leaves."""
    if isinstance(value, dict):
        if "value" in value and "type" in value and len(value) <= 3:
            raw = value["value"]
            typ = str(value.get("type", "")).lower()
            if typ in {"float", "float32", "float64", "double"}:
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    return raw
            if typ in {"int", "int32", "int64", "uint16", "uint32"}:
                try:
                    return int(float(raw))
                except (TypeError, ValueError):
                    return raw
            if typ in {"bool", "boolean"}:
                return str(raw).lower() in {"1", "true", "yes"}
            return raw
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v) for v in value]
    return value


def parse_metadata_payload(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return unwrap(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if hasattr(raw, "dtype"):  # numpy array (Velox uint8 JSON slab)
        import numpy as np

        arr = np.asarray(raw)
        if arr.dtype == object:
            raw = arr.reshape(-1)[0]
            return parse_metadata_payload(raw)
        if arr.ndim >= 2:
            arr = arr[:, 0]
        raw = bytes(arr.ravel().astype("uint8", copy=False)).split(b"\x00", 1)[0]
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            return unwrap(json.loads(text))
        except json.JSONDecodeError:
            return {"raw": text}
    return {"raw": raw}


def _dig(meta: dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = meta
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def flatten_velox_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Pull the fields a TEM user expects to see in the property pane."""
    meta = unwrap(meta)
    out: dict[str, Any] = {}

    hv = _dig(meta, "Optics", "AccelerationVoltage")
    if hv is not None:
        try:
            out["high_tension_v"] = float(hv)
            out["high_tension_kv"] = float(hv) / 1000.0
        except (TypeError, ValueError):
            pass

    mag = _dig(meta, "Optics", "Magnification")
    stem_mag = _dig(meta, "CustomProperties", "StemMagnification")
    if mag is not None:
        out["magnification"] = mag
    elif stem_mag is not None:
        out["magnification"] = stem_mag

    dwell = _dig(meta, "Scan", "DwellTime")
    if dwell is None:
        dwell = _dig(meta, "Acquisition", "DwellTime")
    if dwell is not None:
        out["dwell_time_s"] = dwell

    px = _dig(meta, "BinaryResult", "PixelSize", "width")
    py = _dig(meta, "BinaryResult", "PixelSize", "height")
    if px is not None:
        try:
            out["pixel_size_m"] = float(px)
            out["pixel_size_nm"] = float(px) * 1e9
        except (TypeError, ValueError):
            pass
    if py is not None:
        try:
            out["pixel_size_y_m"] = float(py)
        except (TypeError, ValueError):
            pass

    out["pixel_unit_x"] = _dig(meta, "BinaryResult", "PixelUnitX", default="m")
    out["pixel_unit_y"] = _dig(meta, "BinaryResult", "PixelUnitY", default="m")

    instrument = _dig(meta, "Instrument", "InstrumentModel") or _dig(
        meta, "Instrument", "InstrumentId"
    )
    if instrument:
        out["instrument"] = instrument
    maker = _dig(meta, "Instrument", "Manufacturer")
    if maker:
        out["manufacturer"] = maker

    cl = _dig(meta, "Optics", "CameraLength")
    if cl is not None:
        out["camera_length_m"] = cl
    conv = _dig(meta, "Optics", "ConvergenceAngle") or _dig(meta, "Optics", "BeamConvergence")
    if conv is not None:
        out["convergence_rad"] = conv

    defocus = _dig(meta, "Optics", "Defocus")
    if defocus is not None:
        out["defocus_m"] = defocus
    beam_i = _dig(meta, "Optics", "BeamCurrent")
    if beam_i is not None:
        out["beam_current_a"] = beam_i
    spot = _dig(meta, "Optics", "SpotIndex") or _dig(meta, "Optics", "Spot")
    if spot is not None:
        out["spot_index"] = spot
    mode = _dig(meta, "Optics", "OperatingMode") or _dig(meta, "Optics", "IlluminationMode")
    if mode:
        out["operating_mode"] = mode
    probe = _dig(meta, "Optics", "ProbeMode")
    if probe:
        out["probe_mode"] = probe
    c2 = _dig(meta, "Optics", "C2Aperture") or _dig(meta, "Optics", "CondenserAperture")
    if c2 is not None:
        out["c2_aperture_m"] = c2
    screen_i = _dig(meta, "Optics", "LastMeasuredScreenCurrent")
    if screen_i is not None:
        out["screen_current_a"] = screen_i

    rot = _dig(meta, "Scan", "ScanRotation")
    if rot is not None:
        out["scan_rotation_rad"] = rot
    frame_t = _dig(meta, "Scan", "FrameTime")
    if frame_t is not None:
        out["frame_time_s"] = frame_t
    mains = _dig(meta, "Scan", "MainsLock")
    if mains is not None:
        out["mains_lock"] = mains

    acquired = (
        _dig(meta, "Acquisition", "AcquisitionDatetime", "DateTime")
        or _dig(meta, "Acquisition", "AcquisitionStartDatetime", "DateTime")
        or _dig(meta, "Acquisition", "AcquisitionDateTime")
    )
    if acquired:
        out["acquisition_datetime"] = acquired
    source = _dig(meta, "Acquisition", "SourceType")
    if source:
        out["source_type"] = source
    n_frames = _dig(meta, "Acquisition", "NumberOfFrames") or _dig(meta, "BinaryResult", "NumberOfFrames")
    if n_frames is not None:
        out["n_frames"] = n_frames
    binning = _dig(meta, "Acquisition", "Binning") or _dig(meta, "BinaryResult", "Binning")
    if binning is not None:
        out["binning"] = binning

    for axis, key in (("x", "stage_x_m"), ("y", "stage_y_m"), ("z", "stage_z_m")):
        pos = _dig(meta, "Stage", "Position", axis)
        if pos is not None:
            out[key] = pos
    alpha = _dig(meta, "Stage", "AlphaTilt")
    if alpha is not None:
        out["alpha_tilt_rad"] = alpha
    beta = _dig(meta, "Stage", "BetaTilt")
    if beta is not None:
        out["beta_tilt_rad"] = beta
    holder = _dig(meta, "Stage", "HolderType")
    if holder:
        out["holder"] = holder

    sample = _dig(meta, "Sample", "SampleId") or _dig(meta, "Sample", "SampleName")
    if sample:
        out["sample_id"] = sample
    sample_desc = _dig(meta, "Sample", "Description")
    if sample_desc:
        out["sample_description"] = sample_desc

    offset_x = _dig(meta, "BinaryResult", "Offset", "x")
    offset_y = _dig(meta, "BinaryResult", "Offset", "y")
    if offset_x is not None:
        out["offset_x_m"] = offset_x
    if offset_y is not None:
        out["offset_y_m"] = offset_y

    br_det = _dig(meta, "BinaryResult", "Detector")
    if br_det:
        out["detector"] = str(br_det)
        out["display_name"] = str(br_det)

    det = _dig(meta, "Detectors")
    if isinstance(det, dict):
        names = []
        for _k, val in det.items():
            if isinstance(val, dict) and val.get("DetectorName"):
                names.append(str(val["DetectorName"]))
                if str(val.get("DetectorType", "")).lower() == "analyticaldetector":
                    try:
                        disp = float(val.get("Dispersion") or 0)
                        off = float(val.get("OffsetEnergy") or 0)
                        if disp:
                            out.setdefault("energy_scale_kev", disp / 1000.0)
                            out.setdefault("energy_offset_kev", off / 1000.0)
                        if val.get("ElevationAngle") is not None:
                            out.setdefault("takeoff_rad", float(val["ElevationAngle"]))
                    except (TypeError, ValueError):
                        pass
            elif isinstance(val, str):
                names.append(val)
        if names:
            out.setdefault("detector", names[0])
            out["detectors"] = names
    display = _dig(meta, "CustomProperties", "DisplayName")
    if display:
        out["display_name"] = display

    beam = _dig(meta, "Acquisition", "BeamType")
    if beam:
        out["beam_type"] = beam

    for key, value in meta.items():
        if key not in out and not isinstance(value, (dict, list)):
            out[key] = value

    out["_raw"] = meta
    return out


def format_coord(index: float, pixel_m: float | None) -> str:
    """Pixel index plus a calibrated length, e.g. ``12 (3.00 nm)``."""
    idx = int(round(index))
    if not pixel_m or pixel_m <= 0:
        return str(idx)
    return f"{idx} ({format_pixel_size(idx * float(pixel_m))})"


def format_pixel_size(meters: float | None) -> str:
    if meters is None:
        return "—"
    try:
        m = float(meters)
    except (TypeError, ValueError):
        return "—"
    if m <= 0:
        return "—"
    if m >= 1e-6:
        return f"{m * 1e6:.3g} µm"
    if m >= 1e-9:
        return f"{m * 1e9:.3g} nm"
    if m >= 1e-12:
        return f"{m * 1e12:.3g} pm"
    return f"{m:.3e} m"


def format_hv(volts: float | None) -> str:
    if volts is None:
        return "—"
    try:
        v = float(volts)
    except (TypeError, ValueError):
        return "—"
    if v >= 1000:
        return f"{v / 1000.0:.3g} kV"
    return f"{v:.3g} V"


def format_dwell(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if s >= 1:
        return f"{s:.3g} s"
    if s >= 1e-3:
        return f"{s * 1e3:.3g} ms"
    if s >= 1e-6:
        return f"{s * 1e6:.3g} µs"
    return f"{s * 1e9:.3g} ns"


def format_current(amps: float | None) -> str:
    if amps is None:
        return "—"
    try:
        a = float(amps)
    except (TypeError, ValueError):
        return "—"
    mag = abs(a)
    if mag >= 1e-3:
        return f"{a * 1e3:.3g} mA"
    if mag >= 1e-6:
        return f"{a * 1e6:.3g} µA"
    if mag >= 1e-9:
        return f"{a * 1e9:.3g} nA"
    return f"{a * 1e12:.3g} pA"


def format_length(meters: float | None) -> str:
    if meters is None:
        return "—"
    try:
        m = float(meters)
    except (TypeError, ValueError):
        return "—"
    mag = abs(m)
    if mag >= 1:
        return f"{m:.3g} m"
    if mag >= 1e-3:
        return f"{m * 1e3:.3g} mm"
    if mag >= 1e-6:
        return f"{m * 1e6:.3g} µm"
    return format_pixel_size(m)


def format_mrad(radians: float | None) -> str:
    if radians is None:
        return "—"
    try:
        return f"{float(radians) * 1e3:.3g} mrad"
    except (TypeError, ValueError):
        return "—"


def format_degrees(radians: float | None) -> str:
    if radians is None:
        return "—"
    try:
        return f"{float(radians) * 180.0 / math.pi:.3g}°"
    except (TypeError, ValueError):
        return "—"


def format_metadata_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "—"
        return f"{value:.6g}"
    if isinstance(value, (dict, list)):
        return ""
    return str(value)


def walk_metadata_tree(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested Velox JSON into ``(dotted.path, display)`` rows."""
    rows: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key in obj:
            path = f"{prefix}.{key}" if prefix else str(key)
            val = obj[key]
            if isinstance(val, (dict, list)):
                rows.extend(walk_metadata_tree(val, path))
            else:
                rows.append((path, format_metadata_value(val)))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            path = f"{prefix}[{i}]"
            if isinstance(val, (dict, list)):
                rows.extend(walk_metadata_tree(val, path))
            else:
                rows.append((path, format_metadata_value(val)))
    elif prefix:
        rows.append((prefix, format_metadata_value(obj)))
    return rows


def acquisition_sections(metadata: dict[str, Any], *, extra: dict[str, Any] | None = None) -> list[tuple[str, list[tuple[str, str]]]]:
    """Grouped property rows for the Velox-style acquisition inspector."""
    m = dict(metadata or {})
    if extra:
        for key, value in extra.items():
            m.setdefault(key, value)
    raw = m.get("_raw") if isinstance(m.get("_raw"), dict) else {}

    def pick(*keys: str, default: Any = None) -> Any:
        for key in keys:
            if m.get(key) not in (None, ""):
                return m[key]
        return default

    sections: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "acquisition",
            [
                ("acquired", str(pick("acquisition_datetime") or "—")),
                ("beam_type", str(pick("beam_type") or "—")),
                ("source_type", str(pick("source_type") or "—")),
                ("n_frames", format_metadata_value(pick("n_frames"))),
                ("binning", format_metadata_value(pick("binning"))),
            ],
        ),
        (
            "optics",
            [
                ("hv", format_hv(pick("high_tension_v"))),
                ("mag", format_metadata_value(pick("magnification"))),
                ("operating_mode", str(pick("operating_mode") or "—")),
                ("probe_mode", str(pick("probe_mode") or "—")),
                ("spot", format_metadata_value(pick("spot_index"))),
                ("camera_length", format_length(pick("camera_length_m"))),
                ("convergence", format_mrad(pick("convergence_rad"))),
                ("defocus", format_length(pick("defocus_m"))),
                ("beam_current", format_current(pick("beam_current_a"))),
                ("screen_current", format_current(pick("screen_current_a"))),
                ("aperture_c2", format_length(pick("c2_aperture_m"))),
            ],
        ),
        (
            "scan",
            [
                ("dwell", format_dwell(pick("dwell_time_s"))),
                ("frame_time", format_dwell(pick("frame_time_s"))),
                ("scan_rotation", format_degrees(pick("scan_rotation_rad"))),
            ],
        ),
        (
            "stage",
            [
                ("stage_x", format_length(pick("stage_x_m"))),
                ("stage_y", format_length(pick("stage_y_m"))),
                ("stage_z", format_length(pick("stage_z_m"))),
                ("alpha_tilt", format_degrees(pick("alpha_tilt_rad"))),
                ("beta_tilt", format_degrees(pick("beta_tilt_rad"))),
                ("holder", str(pick("holder") or "—")),
            ],
        ),
        (
            "instrument",
            [
                ("instrument", str(pick("instrument") or "—")),
                ("manufacturer", str(pick("manufacturer") or "—")),
            ],
        ),
        (
            "detector",
            [
                ("detector", str(pick("detector", "display_name") or "—")),
                ("detectors", ", ".join(pick("detectors") or []) if isinstance(pick("detectors"), list) else str(pick("detectors") or "—")),
            ],
        ),
        (
            "calibration",
            [
                ("pixel_size", format_pixel_size(pick("pixel_size_m"))),
                ("pixel_unit_x", str(pick("pixel_unit_x") or "m")),
                ("offset", f"{format_length(pick('offset_x_m'))}, {format_length(pick('offset_y_m'))}"),
            ],
        ),
        (
            "sample",
            [
                ("sample", str(pick("sample_id") or "—")),
                ("sample_description", str(pick("sample_description") or "—")),
            ],
        ),
    ]
    if raw:
        sections.append(("all_metadata", walk_metadata_tree(raw)))
    return sections


def acquisition_row_count(metadata: dict[str, Any]) -> int:
    return sum(len(rows) for _title, rows in acquisition_sections(metadata))
