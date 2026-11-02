"""Dispatch file loading across EMD, TIA SER, DM3/DM4, TIFF and optional HyperSpy."""

from __future__ import annotations

from pathlib import Path

from openvelox.io.dm import read_dm
from openvelox.io.ser import read_ser
from openvelox.io.tiff_io import read_tiff
from openvelox.io.velox_emd import is_emd, read_emd
from openvelox.models import ExperimentFile

SUPPORTED_SUFFIXES = {".emd", ".ser", ".emi", ".dm3", ".dm4", ".tif", ".tiff"}


def load_path(path: str | Path) -> ExperimentFile:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".emi":
        ser = path.with_suffix(".ser")
        if ser.is_file():
            return read_ser(ser)
        raise ValueError(f"EMI sidecar without a matching .ser: {path}")
    if suffix == ".emd" or is_emd(path):
        try:
            experiment = read_emd(path)
            if experiment.datasets:
                return experiment
        except Exception:
            hs = _try_hyperspy(path)
            if hs is not None:
                return hs
            raise
        hs = _try_hyperspy(path)
        if hs is not None:
            return hs
        return experiment
    if suffix == ".ser":
        try:
            return read_ser(path)
        except Exception:
            hs = _try_hyperspy(path)
            if hs is not None:
                return hs
            ncem = _try_ncempy(path)
            if ncem is not None:
                return ncem
            raise
    if suffix in {".dm3", ".dm4"}:
        try:
            return read_dm(path)
        except Exception:
            hs = _try_hyperspy(path)
            if hs is not None:
                return hs
            ncem = _try_ncempy(path)
            if ncem is not None:
                return ncem
            raise
    if suffix in {".tif", ".tiff"}:
        return read_tiff(path)
    hs = _try_hyperspy(path)
    if hs is not None:
        return hs
    raise ValueError(f"Unsupported file type: {path}")


def load_experiment(path: str | Path) -> ExperimentFile:
    return load_path(path)


def _try_hyperspy(path: Path) -> ExperimentFile | None:
    try:
        import hyperspy.api as hs  # type: ignore
    except Exception:
        return None
    try:
        loaded = hs.load(str(path), lazy=False)
    except Exception:
        return None
    signals = loaded if isinstance(loaded, (list, tuple)) else [loaded]
    from openvelox.models import Axis, Dataset, DatasetKind

    datasets = []
    for i, sig in enumerate(signals):
        try:
            data = sig.data
            name = str(getattr(sig, "metadata", {}).get("General", {}).get("title", "") or f"signal_{i}")
            axes = []
            for ax in getattr(sig, "axes_manager", []):
                axes.append(
                    Axis(
                        name=str(getattr(ax, "name", "axis") or "axis"),
                        size=int(ax.size),
                        scale=float(getattr(ax, "scale", 1.0) or 1.0),
                        offset=float(getattr(ax, "offset", 0.0) or 0.0),
                        units=str(getattr(ax, "units", "") or ""),
                    )
                )
            ndim = data.ndim
            if ndim == 4:
                kind = DatasetKind.FOUR_D
            elif ndim == 3 and any("eV" in (a.units or "") or "energy" in a.name.lower() for a in axes):
                kind = DatasetKind.SPECTRUM_IMAGE
            elif ndim == 3:
                kind = DatasetKind.STACK
            elif ndim == 1:
                kind = DatasetKind.SPECTRUM
            else:
                kind = DatasetKind.IMAGE
            datasets.append(
                Dataset(
                    name=name or path.stem,
                    kind=kind,
                    data=data,
                    axes=axes,
                    metadata={"source": "hyperspy"},
                    source_path=str(path),
                    group_id=str(i),
                )
            )
        except Exception:
            continue
    if not datasets:
        return None
    return ExperimentFile(path=str(path), name=path.name, datasets=datasets, metadata={"reader": "hyperspy"})


def _try_ncempy(path: Path) -> ExperimentFile | None:
    try:
        import ncempy.io as nio  # type: ignore
    except Exception:
        return None
    try:
        suffix = path.suffix.lower()
        if suffix in {".dm3", ".dm4"}:
            result = nio.dm.dmReader(str(path))
        elif suffix == ".ser":
            result = nio.ser.serReader(str(path))
        elif suffix == ".emd":
            result = nio.emd.emdReader(str(path))
        else:
            return None
        data = result.get("data")
        if data is None:
            return None
        from openvelox.models import Axis, Dataset, DatasetKind

        px = 1e-9
        pixel_unit = result.get("pixelUnit", ["m", "m"])
        pixel_size = result.get("pixelSize", [1.0, 1.0])
        if pixel_size:
            px = float(pixel_size[0])
            unit = str(pixel_unit[0]) if pixel_unit else "m"
            if unit == "nm":
                px *= 1e-9
        kind = DatasetKind.STACK if data.ndim == 3 else DatasetKind.IMAGE
        axes = (
            [Axis("y", data.shape[0], px, units="m"), Axis("x", data.shape[1], px, units="m")]
            if data.ndim == 2
            else [Axis(f"a{i}", n, 1.0) for i, n in enumerate(data.shape)]
        )
        ds = Dataset(
            name=path.stem,
            kind=kind,
            data=data,
            axes=axes,
            metadata={"source": "ncempy", "pixel_size_m": px},
            source_path=str(path),
            group_id="0",
        )
        return ExperimentFile(path=str(path), name=path.name, datasets=[ds], metadata={"reader": "ncempy"})
    except Exception:
        return None
