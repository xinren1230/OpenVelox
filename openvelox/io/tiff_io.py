"""TIFF / TIF reader (including ImageJ-style stacks)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import tifffile

from openvelox.models import Axis, Dataset, DatasetKind, ExperimentFile


def read_tiff(path: str | Path) -> ExperimentFile:
    path = Path(path)
    with tifffile.TiffFile(path) as tif:
        series = tif.series[0]
        data = series.asarray()
        tags = {}
        try:
            page = tif.pages[0]
            tags = {tag.name: tag.value for tag in page.tags.values()}
        except Exception:
            tags = {}
        meta: dict[str, Any] = {}
        res = tags.get("XResolution")
        unit = tags.get("ResolutionUnit")
        if isinstance(res, tuple) and res[1]:
            # TIFF resolution is pixels per unit
            try:
                px_per = float(res[0]) / float(res[1])
                if px_per > 0:
                    # unit 3 = centimeter
                    if unit == 3:
                        meta["pixel_size_m"] = 0.01 / px_per
                    elif unit == 2:  # inch
                        meta["pixel_size_m"] = 0.0254 / px_per
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        desc = tags.get("ImageDescription")
        if isinstance(desc, bytes):
            desc = desc.decode("utf-8", errors="replace")
        software = tags.get("Software")
        if isinstance(software, bytes):
            software = software.decode("utf-8", errors="replace")
        ij = getattr(tif, "imagej_metadata", None) or {}
        if isinstance(ij, dict) and ij.get("spacing") is not None:
            try:
                meta["pixel_size_m"] = float(ij["spacing"])
            except (TypeError, ValueError):
                pass
        blob = "\n".join(str(x) for x in (desc, software) if x)
        for part in blob.replace(";", "\n").replace("\r", "\n").split("\n"):
            low = part.lower().strip()
            if low.startswith("spacing=") or low.startswith("pixel_m="):
                try:
                    meta["pixel_size_m"] = float(part.split("=", 1)[1])
                except ValueError:
                    pass
        if "pixel_size_m" not in meta:
            meta["pixel_size_m"] = 1e-9
        meta["pixel_size_nm"] = float(meta["pixel_size_m"]) * 1e9

    kind = DatasetKind.IMAGE
    if data.ndim == 3:
        kind = DatasetKind.STACK
    elif data.ndim == 1:
        kind = DatasetKind.SPECTRUM
    px = float(meta["pixel_size_m"])
    if data.ndim == 2:
        axes = [Axis("y", data.shape[0], px, units="m"), Axis("x", data.shape[1], px, units="m")]
    elif data.ndim == 3:
        axes = [
            Axis("frame", data.shape[0], 1.0, units="frame"),
            Axis("y", data.shape[1], px, units="m"),
            Axis("x", data.shape[2], px, units="m"),
        ]
    else:
        axes = [Axis(f"a{i}", n) for i, n in enumerate(data.shape)]
    ds = Dataset(
        name=path.stem,
        kind=kind,
        data=data,
        axes=axes,
        metadata=meta,
        source_path=str(path),
        group_id="0",
    )
    return ExperimentFile(path=str(path), name=path.name, datasets=[ds])


def write_tiff(path: str | Path, image: np.ndarray, pixel_m: float = 1e-9) -> None:
    path = Path(path)
    image = np.asarray(image)
    # ImageJ description carries spacing in meters for our reader.
    # ImageJ-style description carries spacing. Skip TIFF resolution tags for
    # TEM-scale pixels (they overflow the rational encoder).
    tifffile.imwrite(
        path,
        image,
        software=f"OpenVelox;pixel_m={pixel_m}",
        description=f"OpenVelox\nspacing={pixel_m}\nunit=m\n",
    )
