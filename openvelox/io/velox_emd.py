"""Read and write Thermo Fisher Velox-style .emd (HDF5) files."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from openvelox.io.lazy import LazyArray, h5_loader, h5_slicer
from openvelox.io.metadata import flatten_velox_metadata, parse_metadata_payload
from openvelox.io.spectrum_stream import (
    decode_spectrum_stream,
    infer_stream_shape,
    parse_acquisition_settings,
)
from openvelox.models import Axis, Dataset, DatasetKind, ExperimentFile

IMAGE_KINDS = ("Image",)
SI_KINDS = ("SpectrumImage", "SpectrumStream")
FOURD_KINDS = ("FourDSTEM", "Diffraction", "CBED")
STACK_HINTS = ("stack", "series", "frame")


def _read_attr_or_ds(group: h5py.Group | h5py.Dataset, name: str) -> Any:
    if name in group.attrs:
        value = group.attrs[name]
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value
    if isinstance(group, h5py.Group) and name in group:
        node = group[name]
        if isinstance(node, h5py.Dataset):
            data = node[()]
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            if getattr(data, "dtype", None) is not None and data.shape == ():
                item = data[()]
                if isinstance(item, bytes):
                    return item.decode("utf-8", errors="replace")
                return item
            return data
    return None


def _load_metadata(node: h5py.Group) -> dict[str, Any]:
    raw = None
    if "Metadata" in node:
        raw = node["Metadata"][()]
    if raw is None:
        raw = _read_attr_or_ds(node, "Metadata")
    parsed = parse_metadata_payload(raw)
    extra = {}
    for key in ("DisplayName", "Name", "DetectorName"):
        val = _read_attr_or_ds(node, key)
        if val is not None:
            extra[key] = val.decode() if isinstance(val, bytes) else val
    parsed.update(extra)
    return flatten_velox_metadata(parsed)


def _image_frame_slicer(path: str, inner: str, raw_shape: tuple[int, ...]):
    """Map stack ``data[frame]`` onto Velox ``(y, x, frames)`` without a full read."""
    is_velox_stack = (
        len(raw_shape) == 3
        and raw_shape[-1] <= raw_shape[0]
        and raw_shape[-1] <= raw_shape[1]
        and raw_shape[-1] != 1
    )

    def slicer(item: Any) -> np.ndarray:
        import h5py as _h5

        with _h5.File(path, "r") as handle:
            node = handle[inner]
            if is_velox_stack and isinstance(item, (int, np.integer)):
                return np.asarray(node[:, :, int(item)])
            if is_velox_stack and isinstance(item, tuple) and item and isinstance(item[0], (int, np.integer)):
                frame = np.asarray(node[:, :, int(item[0])])
                rest = item[1:]
                return frame[rest] if rest else frame
            return np.asarray(node[item])

    return slicer


def _eels_slicer(path: str, inner: str, raw_shape: tuple[int, ...], out_shape: tuple[int, ...]):
    """Slice transposed Velox EELS ``(columns, channels, rows)`` as ``(y, x, E)``."""
    transposed = (
        len(raw_shape) == 3
        and len(out_shape) == 3
        and raw_shape[1] > raw_shape[0]
        and raw_shape[1] > raw_shape[2]
    )

    def slicer(item: Any) -> np.ndarray:
        import h5py as _h5

        with _h5.File(path, "r") as handle:
            raw = handle[inner]
            if not transposed:
                if raw.ndim == 3:
                    # stored (y, E, x) → logical (y, x, E)
                    if isinstance(item, tuple) and len(item) == 3:
                        y, x, e = item
                        return np.asarray(raw[y, e, x])
                return np.asarray(raw[item])
            # stored (x, E, y) → logical (y, x, E)
            if isinstance(item, tuple) and len(item) == 3:
                y, x, e = item
                return np.asarray(raw[x, e, y])
            arr = np.asarray(raw[()])
            return np.transpose(arr, (2, 0, 1))[item]

    return slicer


def _normalize_image_array(arr: np.ndarray) -> tuple[np.ndarray, DatasetKind]:
    """Velox Image.Data is (y, x) or (y, x, frames). Our stacks are (t, y, x)."""
    arr = np.asarray(arr)
    if arr.dtype.names and {"realFloat", "imagFloat"} <= set(arr.dtype.names):
        arr = np.abs(arr["realFloat"].astype(np.float64) + 1j * arr["imagFloat"].astype(np.float64))
    elif np.iscomplexobj(arr):
        arr = np.abs(arr)
    if arr.ndim == 2:
        return arr, DatasetKind.IMAGE
    if arr.ndim == 3:
        y, x, t = arr.shape
        # Velox: last axis is frames when it is the short axis.
        if t <= y and t <= x and t <= 512:
            if t == 1:
                return arr[:, :, 0], DatasetKind.IMAGE
            return np.moveaxis(arr, -1, 0), DatasetKind.STACK
        return arr, DatasetKind.STACK
    if arr.ndim == 1:
        return arr, DatasetKind.SPECTRUM
    if arr.ndim == 4:
        return arr, DatasetKind.FOUR_D
    return arr, DatasetKind.IMAGE


def _axes_from_meta(shape: tuple[int, ...], meta: dict[str, Any], kind: DatasetKind) -> list[Axis]:
    px = float(meta.get("pixel_size_m") or 1.0)
    unit = str(meta.get("pixel_unit_x") or "m")
    if unit in {"", "1"}:
        unit = "m"
    axes: list[Axis] = []
    if kind is DatasetKind.STACK and len(shape) == 3:
        axes.append(Axis("frame", shape[0], scale=1.0, units="frame"))
        axes.append(Axis("y", shape[1], scale=px, units=unit))
        axes.append(Axis("x", shape[2], scale=px, units=unit))
    elif kind is DatasetKind.SPECTRUM_IMAGE and len(shape) == 3:
        e_scale = float(meta.get("energy_scale_kev", 0.01))
        e_off = float(meta.get("energy_offset_kev", 0.0))
        axes.append(Axis("y", shape[0], scale=px, units=unit))
        axes.append(Axis("x", shape[1], scale=px, units=unit))
        axes.append(Axis("energy", shape[2], scale=e_scale, offset=e_off, units="keV"))
    elif kind is DatasetKind.FOUR_D and len(shape) == 4:
        qx = float(meta.get("reciprocal_scale_mrad", 1.0))
        axes.append(Axis("scan_y", shape[0], scale=px, units=unit))
        axes.append(Axis("scan_x", shape[1], scale=px, units=unit))
        axes.append(Axis("qy", shape[2], scale=qx, units="px"))
        axes.append(Axis("qx", shape[3], scale=qx, units="px"))
    elif kind is DatasetKind.SPECTRUM and len(shape) == 1:
        e_scale = float(meta.get("energy_scale_kev", 0.01))
        e_off = float(meta.get("energy_offset_kev", 0.0))
        axes.append(Axis("energy", shape[0], scale=e_scale, offset=e_off, units="keV"))
    elif len(shape) == 2:
        axes.append(Axis("y", shape[0], scale=px, units=unit))
        axes.append(Axis("x", shape[1], scale=px, units=unit))
    else:
        axes = [Axis(f"axis{i}", n) for i, n in enumerate(shape)]
    return axes


def _kind_for(container: str, name: str, shape: tuple[int, ...], meta: dict[str, Any]) -> DatasetKind:
    c = container.lower()
    n = name.lower()
    if c in {k.lower() for k in SI_KINDS} or "spectrum" in n:
        if len(shape) == 1:
            return DatasetKind.SPECTRUM
        return DatasetKind.SPECTRUM_IMAGE
    if c in {k.lower() for k in FOURD_KINDS} or "4d" in n or "cbed" in n:
        return DatasetKind.FOUR_D
    if len(shape) == 3 and (any(h in n for h in STACK_HINTS) or shape[0] < min(shape[1:])):
        return DatasetKind.STACK
    if len(shape) == 3 and meta.get("energy_scale_kev"):
        return DatasetKind.SPECTRUM_IMAGE
    if len(shape) == 4:
        return DatasetKind.FOUR_D
    if len(shape) == 1:
        return DatasetKind.SPECTRUM
    if len(shape) == 3:
        return DatasetKind.STACK
    return DatasetKind.IMAGE


def _dataset_from_image_group(
    group: h5py.Group,
    source: str,
    uid: str,
    titles: dict[str, str],
) -> Dataset | None:
    if "Data" not in group:
        return None
    node = group["Data"]
    inner = node.name
    raw_shape = tuple(int(n) for n in node.shape)

    def _load(path: str = source, inner_path: str = inner) -> np.ndarray:
        import h5py as _h5

        with _h5.File(path, "r") as handle:
            arr, _kind = _normalize_image_array(handle[inner_path][()])
            return arr

    preview_kind = DatasetKind.IMAGE
    shape = raw_shape
    if len(raw_shape) == 3 and raw_shape[-1] == 1:
        shape = raw_shape[:2]
        preview_kind = DatasetKind.IMAGE
    elif len(raw_shape) == 3 and raw_shape[-1] <= raw_shape[0] and raw_shape[-1] <= raw_shape[1]:
        shape = (raw_shape[2], raw_shape[0], raw_shape[1])
        preview_kind = DatasetKind.STACK
    elif len(raw_shape) == 3:
        preview_kind = DatasetKind.STACK
    data = LazyArray(
        _load,
        shape,
        dtype=node.dtype,
        label=f"image:{uid[:8]}",
        slicer=_image_frame_slicer(source, inner, raw_shape),
    )
    meta = _load_metadata(group)
    name = titles.get(uid) or str(meta.get("display_name") or meta.get("detector") or uid[:8])
    kind = preview_kind
    if "energy_scale_kev" in group.attrs:
        meta["energy_scale_kev"] = float(group.attrs["energy_scale_kev"])
    axes = _axes_from_meta(shape, meta, kind)
    return Dataset(
        name=str(name),
        kind=kind,
        data=data,
        axes=axes,
        metadata=meta,
        source_path=source,
        group_id=uid,
        detector=str(meta.get("detector") or ""),
    )


def _dataset_from_spectrum_group(group: h5py.Group, source: str, uid: str) -> Dataset | None:
    if "Data" not in group:
        return None
    arr = np.asarray(group["Data"][()]).reshape(-1)
    meta = _load_metadata(group)
    name = str(meta.get("display_name") or meta.get("detector") or f"Spectrum {uid[:6]}")
    axes = _axes_from_meta(arr.shape, meta, DatasetKind.SPECTRUM)
    return Dataset(
        name=name,
        kind=DatasetKind.SPECTRUM,
        data=arr,
        axes=axes,
        metadata=meta,
        source_path=source,
        group_id=uid,
        detector=str(meta.get("detector") or "EDS"),
    )


def _haadf_hw(datasets: list[Dataset]) -> tuple[int, int] | None:
    for ds in datasets:
        if "haadf" in ds.name.lower() and len(ds.shape) >= 2:
            return int(ds.shape[-2]), int(ds.shape[-1])
        if ds.kind is DatasetKind.IMAGE and len(ds.shape) == 2:
            # remember first image as weak fallback
            pass
    for ds in datasets:
        if ds.kind is DatasetKind.IMAGE and len(ds.shape) == 2:
            return int(ds.shape[0]), int(ds.shape[1])
    return None


def _collect_display_titles(root: h5py.Group) -> dict[str, str]:
    """Map Image uuid → title from Displays/ImageDisplay when possible."""
    titles: dict[str, str] = {}
    for path in ("Displays/ImageDisplay", "Presentation/Displays/ImageDisplay"):
        if path not in root:
            continue
        grp = root[path]
        if not isinstance(grp, h5py.Group):
            continue
        for key in grp:
            node = grp[key]
            try:
                raw = node[()]
                parsed = parse_metadata_payload(raw)
            except Exception:
                continue
            display = parsed.get("display") if isinstance(parsed.get("display"), dict) else {}
            title = parsed.get("title") or display.get("label") or parsed.get("id")
            data = str(parsed.get("data") or parsed.get("dataPath") or "")
            uid = data.rstrip("/").split("/")[-1] if data else ""
            if title and uid:
                titles[uid] = str(title)
            elif title:
                titles[key] = str(title)
    return titles


def _stream_datasets(
    stream_root: h5py.Group,
    source: str,
    fallback_hw: tuple[int, int] | None,
    energy_meta: dict[str, Any],
) -> list[Dataset]:
    datasets: list[Dataset] = []
    loaders = []
    common_shape: tuple[int, int, int] | None = None
    common_meta: dict[str, Any] = dict(energy_meta)

    for uid in stream_root:
        child = stream_root[uid]
        if not isinstance(child, h5py.Group) or "Data" not in child:
            continue
        settings = {}
        if "AcquisitionSettings" in child:
            settings = parse_acquisition_settings(child["AcquisitionSettings"][()])
        stream_shape = child["Data"].shape
        flt = child["FrameLocationTable"][()] if "FrameLocationTable" in child else None
        # Peek only the gate-pulse count lazily via a tiny read of the table + settings.
        # Full stream decode is deferred.
        meta = _load_metadata(child)
        meta.update({k: v for k, v in energy_meta.items() if k not in meta})
        n_channels = int(float(settings.get("bincount") or meta.get("n_channels") or 4096))
        inner = child["Data"].name
        flt_path = child["FrameLocationTable"].name if "FrameLocationTable" in child else None
        acq_snapshot = dict(settings)

        def _make_loader(
            inner_path: str = inner,
            flt_inner: str | None = flt_path,
            acq: dict[str, Any] = acq_snapshot,
            fb: tuple[int, int] | None = fallback_hw,
            nch: int = n_channels,
        ) -> Any:
            def _load() -> np.ndarray:
                from openvelox.processing.cache import memoize_array

                def _decode() -> np.ndarray:
                    import h5py as _h5

                    with _h5.File(source, "r") as handle:
                        stream = np.asarray(handle[inner_path][()]).reshape(-1)
                        offsets = None
                        if flt_inner and flt_inner in handle:
                            offsets = np.asarray(handle[flt_inner][()]).reshape(-1)
                        h, w, ch, _nf = infer_stream_shape(stream, offsets, acq, fallback_hw=fb)
                        return decode_spectrum_stream(
                            stream,
                            height=h,
                            width=w,
                            n_channels=ch or nch,
                            frame_offsets=offsets,
                            sum_frames=True,
                        )

                return memoize_array((source, inner_path, "spectrum-stream"), _decode)

            return _load

        raster = settings.get("RasterScanDefinition") or {}
        sw = int(float(raster.get("Width") or 0))
        sh = int(float(raster.get("Height") or 0))
        if fallback_hw and sw and sh:
            if (sh, sw) == fallback_hw:
                h, w = fallback_hw
            elif (sw, sh) == (128, 128):
                # Common Velox prune: settings keep the original raster.
                h, w = fallback_hw
            else:
                h, w = sh, sw
        elif fallback_hw:
            h, w = fallback_hw
        elif sw and sh:
            h, w = sh, sw
        else:
            h, w = 16, 16
        shape = (h, w, n_channels)
        common_shape = shape
        common_meta = meta
        lazy = LazyArray(_make_loader(), shape, dtype=np.uint32, label=f"stream:{uid[:8]}")
        loaders.append(lazy)
        name = str(meta.get("display_name") or meta.get("detector") or f"EDS stream {uid[:6]}")
        axes = _axes_from_meta(shape, meta, DatasetKind.SPECTRUM_IMAGE)
        datasets.append(
            Dataset(
                name=name,
                kind=DatasetKind.SPECTRUM_IMAGE,
                data=lazy,
                axes=axes,
                metadata=meta,
                source_path=source,
                group_id=uid,
                detector=str(meta.get("detector") or "Super-X"),
            )
        )

    if len(loaders) > 1 and common_shape is not None:
        def _sum_all(parts: list[LazyArray] = loaders) -> np.ndarray:
            acc = None
            for part in parts:
                arr = np.asarray(part.materialize(), dtype=np.uint32)
                acc = arr if acc is None else acc + arr
            return acc if acc is not None else np.zeros(common_shape, dtype=np.uint32)

        summed = LazyArray(_sum_all, common_shape, dtype=np.uint32, label="eds-sum")
        axes = _axes_from_meta(common_shape, common_meta, DatasetKind.SPECTRUM_IMAGE)
        datasets.insert(
            0,
            Dataset(
                name="EDS SI (stream)",
                kind=DatasetKind.SPECTRUM_IMAGE,
                data=summed,
                axes=axes,
                metadata=dict(common_meta),
                source_path=source,
                group_id="sum",
                detector="Super-X",
            ),
        )
    return datasets


def _walk_data(root: h5py.Group, source: str) -> list[Dataset]:
    datasets: list[Dataset] = []
    data_root = root.get("Data")
    if data_root is None:
        for key, node in root.items():
            if isinstance(node, h5py.Group) and "data" in node:
                arr = np.asarray(node["data"][()])
                meta = flatten_velox_metadata(parse_metadata_payload(_read_attr_or_ds(node, "metadata")))
                kind = _kind_for("Image", key, arr.shape, meta)
                datasets.append(
                    Dataset(
                        name=key,
                        kind=kind,
                        data=arr,
                        axes=_axes_from_meta(arr.shape, meta, kind),
                        metadata=meta,
                        source_path=source,
                        group_id=key,
                    )
                )
        return datasets

    titles = _collect_display_titles(root)
    energy_meta: dict[str, Any] = {}

    if "Image" in data_root:
        for uid, child in data_root["Image"].items():
            if not isinstance(child, h5py.Group):
                continue
            ds = _dataset_from_image_group(child, source, uid, titles)
            if ds is not None:
                datasets.append(ds)
                for key in ("energy_scale_kev", "energy_offset_kev", "takeoff_rad"):
                    if key in ds.metadata:
                        energy_meta.setdefault(key, ds.metadata[key])

    if "Spectrum" in data_root:
        for uid, child in data_root["Spectrum"].items():
            if isinstance(child, h5py.Group):
                ds = _dataset_from_spectrum_group(child, source, uid)
                if ds is not None:
                    datasets.append(ds)

    # Dense SpectrumImage cubes (our dialect / some converters). Skip Velox compressed blobs.
    if "SpectrumImage" in data_root:
        for uid, child in data_root["SpectrumImage"].items():
            if not isinstance(child, h5py.Group) or "Data" not in child:
                continue
            node = child["Data"]
            if node.dtype == np.uint8 and node.ndim <= 2:
                continue  # Velox compressed SI blob — use SpectrumStream instead
            ds = _dataset_from_group(child, "SpectrumImage", source, uid)
            if ds is not None:
                datasets.append(ds)

    if "FourDSTEM" in data_root or "Diffraction" in data_root:
        for container in ("FourDSTEM", "Diffraction", "CBED"):
            if container not in data_root:
                continue
            for uid, child in data_root[container].items():
                if isinstance(child, h5py.Group):
                    ds = _dataset_from_group(child, container, source, uid)
                    if ds is not None:
                        datasets.append(ds)

    if "EelsSpectrumImage" in data_root:
        for uid, child in data_root["EelsSpectrumImage"].items():
            if not isinstance(child, h5py.Group) or "Data" not in child:
                continue
            inner = child["Data"].name
            raw_shape = tuple(int(n) for n in child["Data"].shape)

            def _eels_load(path: str = source, inner_path: str = inner) -> np.ndarray:
                import h5py as _h5

                with _h5.File(path, "r") as handle:
                    raw = np.asarray(handle[inner_path][()])
                # Velox EELS Data is (columns, channels, rows) → (rows, columns, channels)
                if raw.ndim == 3 and raw.shape[1] > raw.shape[0] and raw.shape[1] > raw.shape[2]:
                    return np.transpose(raw, (2, 0, 1))
                if raw.ndim == 3:
                    return np.moveaxis(raw, 1, -1)
                return raw

            if len(raw_shape) == 3 and raw_shape[1] > raw_shape[0] and raw_shape[1] > raw_shape[2]:
                shape = (raw_shape[2], raw_shape[0], raw_shape[1])
            elif len(raw_shape) == 3:
                shape = (raw_shape[0], raw_shape[2], raw_shape[1])
            else:
                shape = raw_shape
            data = LazyArray(
                _eels_load,
                shape,
                dtype=child["Data"].dtype,
                label=f"eels:{uid[:8]}",
                slicer=_eels_slicer(source, inner, raw_shape, shape),
            )
            meta = _load_metadata(child)
            axes = _axes_from_meta(shape, meta, DatasetKind.SPECTRUM_IMAGE)
            datasets.append(
                Dataset(
                    name="EELS SI",
                    kind=DatasetKind.SPECTRUM_IMAGE,
                    data=data,
                    axes=axes,
                    metadata=meta,
                    source_path=source,
                    group_id=uid,
                    detector="EELS",
                )
            )

    if "SpectrumStream" in data_root:
        datasets.extend(
            _stream_datasets(
                data_root["SpectrumStream"],
                source,
                fallback_hw=_haadf_hw(datasets),
                energy_meta=energy_meta,
            )
        )

    # Operations / Features — record names only when they wrap Image-like Data
    for extra in ("Operations", "Features"):
        if extra not in root:
            continue
        node = root[extra]
        if not isinstance(node, h5py.Group):
            continue
        for uid, child in node.items():
            if isinstance(child, h5py.Group) and "Data" in child and isinstance(child["Data"], h5py.Dataset):
                if child["Data"].ndim >= 2 and child["Data"].size < 50_000_000:
                    ds = _dataset_from_group(child, extra, source, uid)
                    if ds is not None:
                        ds.name = f"{extra}: {ds.name}"
                        datasets.append(ds)

    return datasets


def _dataset_from_group(
    group: h5py.Group,
    container: str,
    source: str,
    uid: str,
) -> Dataset | None:
    data_node = None
    if "Data" in group:
        data_node = group["Data"]
    else:
        for key in group:
            node = group[key]
            if isinstance(node, h5py.Dataset) and node.ndim >= 1 and key not in {"Metadata"}:
                data_node = node
                break
    if data_node is None or not isinstance(data_node, h5py.Dataset):
        return None
    inner = data_node.name
    raw_shape = tuple(int(n) for n in data_node.shape)

    def _load(path: str = source, inner_path: str = inner, cont: str = container) -> np.ndarray:
        import h5py as _h5

        with _h5.File(path, "r") as handle:
            arr = np.asarray(handle[inner_path][()])
            if cont in {"Image", "Operations", "Features"}:
                arr, _ = _normalize_image_array(arr)
            return arr

    data = LazyArray(
        _load,
        raw_shape,
        dtype=data_node.dtype,
        label=f"{container}:{uid[:8]}",
        slicer=h5_slicer(source, inner),
    )
    meta = _load_metadata(group)
    name = (
        str(meta.get("display_name") or "")
        or str(group.attrs.get("DisplayName", "") or "")
        or str(meta.get("detector") or "")
        or uid[:8]
    )
    kind = _kind_for(container, name, raw_shape, meta)
    if "energy_scale_kev" in group.attrs:
        meta["energy_scale_kev"] = float(group.attrs["energy_scale_kev"])
    if "energy_offset_kev" in group.attrs:
        meta["energy_offset_kev"] = float(group.attrs["energy_offset_kev"])
    axes = _axes_from_meta(raw_shape, meta, kind)
    return Dataset(
        name=str(name),
        kind=kind,
        data=data,
        axes=axes,
        metadata=meta,
        source_path=source,
        group_id=uid,
        detector=str(meta.get("detector") or ""),
    )


_KIND_ORDER = {
    DatasetKind.IMAGE: 0,
    DatasetKind.STACK: 1,
    DatasetKind.SPECTRUM: 2,
    DatasetKind.SPECTRUM_IMAGE: 3,
    DatasetKind.FOUR_D: 4,
}


def _uniquify_names(datasets: list[Dataset]) -> list[Dataset]:
    seen: dict[str, int] = {}
    for ds in datasets:
        key = ds.name
        n = seen.get(key, 0) + 1
        seen[key] = n
        if n > 1:
            ds.name = f"{key} ({n})"
    return datasets


def _sort_datasets(datasets: list[Dataset]) -> list[Dataset]:
    return _uniquify_names(sorted(datasets, key=lambda ds: (_KIND_ORDER.get(ds.kind, 9), ds.name.lower())))


def _read_version(handle: h5py.File) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for key in handle.attrs:
        val = handle.attrs[key]
        info[key] = val.decode() if isinstance(val, bytes) else val
    if "Version" in handle:
        raw = handle["Version"][()]
        parsed = parse_metadata_payload(raw)
        info.update(parsed)
        info["velox"] = str(parsed.get("format", "")).lower() == "velox" or "version" in parsed
    elif str(info.get("Format", "")).lower() == "velox":
        info["velox"] = True
    return info


def read_emd(path: str | Path, lazy: bool = True) -> ExperimentFile:
    path = Path(path)
    with h5py.File(path, "r") as handle:
        file_meta = _read_version(handle)
        datasets = _sort_datasets(_walk_data(handle, str(path)))
        if "ExperimentalMetadata" in handle:
            file_meta["ExperimentalMetadata"] = parse_metadata_payload(
                _read_attr_or_ds(handle, "ExperimentalMetadata")
            )
    if not lazy:
        for ds in datasets:
            ds.materialize()
    return ExperimentFile(path=str(path), name=path.name, datasets=datasets, metadata=file_meta)


def _velox_leaf(value: Any, typ: str) -> dict[str, Any]:
    return {"type": typ, "value": str(value)}


def build_velox_metadata(
    *,
    display_name: str,
    detector: str,
    hv_v: float,
    mag: float,
    pixel_m: float,
    dwell_s: float,
    instrument: str = "Talos F200X",
    camera_length_m: float = 0.115,
    convergence_rad: float = 0.021,
    beam_type: str = "STEM",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guid = str(uuid.uuid4())
    meta = {
        "Acquisition": {
            "AcquisitionDatetime": {"DateTime": "2026-11-01T10:00:00"},
            "BeamType": beam_type,
            "SourceType": "FEG",
            "DwellTime": _velox_leaf(dwell_s, "float64"),
        },
        "BinaryResult": {
            "PixelSize": {
                "width": _velox_leaf(pixel_m, "float64"),
                "height": _velox_leaf(pixel_m, "float64"),
            },
            "PixelUnitX": "m",
            "PixelUnitY": "m",
            "Offset": {
                "x": _velox_leaf(0.0, "float64"),
                "y": _velox_leaf(0.0, "float64"),
            },
        },
        "Optics": {
            "AccelerationVoltage": _velox_leaf(hv_v, "float64"),
            "Magnification": _velox_leaf(mag, "float64"),
            "CameraLength": _velox_leaf(camera_length_m, "float64"),
            "ConvergenceAngle": _velox_leaf(convergence_rad, "float64"),
            "Defocus": _velox_leaf(0.0, "float64"),
            "BeamCurrent": _velox_leaf(5e-11, "float64"),
            "SpotIndex": _velox_leaf(5, "int32"),
            "OperatingMode": "STEM",
            "ProbeMode": "Microprobe",
            "C2Aperture": _velox_leaf(50e-6, "float64"),
            "LastMeasuredScreenCurrent": _velox_leaf(1.2e-10, "float64"),
        },
        "Scan": {
            "DwellTime": _velox_leaf(dwell_s, "float64"),
            "ScanRotation": _velox_leaf(0.0, "float64"),
            "FrameTime": _velox_leaf(dwell_s * 512 * 512, "float64"),
            "MainsLock": False,
        },
        "Stage": {
            "Position": {
                "x": _velox_leaf(0.0, "float64"),
                "y": _velox_leaf(0.0, "float64"),
                "z": _velox_leaf(0.0, "float64"),
            },
            "AlphaTilt": _velox_leaf(0.0, "float64"),
            "BetaTilt": _velox_leaf(0.0, "float64"),
            "HolderType": "Single Tilt",
        },
        "Sample": {
            "SampleId": "OpenVelox demo",
            "Description": "Au particle on SiNx / C",
        },
        "Detectors": {
            "A": {"DetectorName": detector, "Inserted": True},
        },
        "Instrument": {
            "InstrumentId": instrument,
            "InstrumentModel": instrument,
            "Manufacturer": "FEI Company",
            "ControlSoftwareVersion": "OpenVelox 0.5.0",
        },
        "Core": {
            "Guid": guid,
            "MetadataDefinitionVersion": "7.9",
            "MetadataSchemaVersion": "v1.0",
        },
        "CustomProperties": {"DisplayName": _velox_leaf(display_name, "string")},
    }
    if extra:
        meta.update(extra)
    return meta


def write_dataset_group(
    parent: h5py.Group,
    data: np.ndarray,
    metadata: dict[str, Any],
    attrs: dict[str, Any] | None = None,
) -> h5py.Group:
    uid = str(uuid.uuid4())
    grp = parent.create_group(uid)
    grp.create_dataset("Data", data=np.asarray(data), compression="gzip", compression_opts=4)
    grp.create_dataset("Metadata", data=_metadata_slab(metadata))
    display = metadata.get("CustomProperties", {}).get("DisplayName", {})
    if isinstance(display, dict):
        grp.attrs["DisplayName"] = str(display.get("value", ""))
    if attrs:
        for key, value in attrs.items():
            grp.attrs[key] = value
    return grp


def _metadata_slab(metadata: dict[str, Any], width: int = 60000) -> np.ndarray:
    payload = json.dumps(metadata).encode("utf-8")
    slab = np.zeros((width, 1), dtype=np.uint8)
    n = min(len(payload), width)
    slab[:n, 0] = np.frombuffer(payload[:n], dtype=np.uint8)
    return slab


def write_spectrum_stream_group(
    parent: h5py.Group,
    cube: np.ndarray,
    metadata: dict[str, Any],
    *,
    energy_scale_kev: float = 0.01,
    energy_offset_kev: float = 0.0,
) -> h5py.Group:
    from openvelox.io.spectrum_stream import encode_spectrum_stream

    arr = np.asarray(cube)
    if arr.ndim == 3:
        h, w, nch = arr.shape
        n_frames = 1
    elif arr.ndim == 4:
        n_frames, h, w, nch = arr.shape
    else:
        raise ValueError("Spectrum stream cube must be 3-D or 4-D")
    stream, table = encode_spectrum_stream(arr)
    uid = str(uuid.uuid4())
    grp = parent.create_group(uid)
    grp.create_dataset("Data", data=stream.reshape(-1, 1))
    grp.create_dataset("FrameLocationTable", data=table.reshape(-1, 1))
    settings = json.dumps(
        {
            "encoding": "uint16",
            "bincount": str(int(nch)),
            "StreamEncoding": "uint16",
            "RasterScanDefinition": {"Width": str(int(w)), "Height": str(int(h))},
            "Size": str(int(h * w * n_frames * 16)),
        }
    ).encode("utf-8")
    grp.create_dataset("AcquisitionSettings", data=np.array([settings], dtype=object))
    meta = dict(metadata)
    dets = meta.setdefault("Detectors", {})
    dets.setdefault(
        "Detector-6",
        {
            "DetectorName": "SuperXG21",
            "DetectorType": "AnalyticalDetector",
            "Dispersion": str(energy_scale_kev * 1000.0),
            "OffsetEnergy": str(energy_offset_kev * 1000.0),
            "ElevationAngle": "0.314",
        },
    )
    grp.create_dataset("Metadata", data=_metadata_slab(meta, width=max(60000, 1)))
    grp.attrs["energy_scale_kev"] = float(energy_scale_kev)
    grp.attrs["energy_offset_kev"] = float(energy_offset_kev)
    return grp


def is_emd(path: str | Path) -> bool:
    path = Path(path)
    if path.suffix.lower() != ".emd":
        return False
    try:
        return h5py.is_hdf5(path)
    except OSError:
        return False
