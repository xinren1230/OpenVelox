from __future__ import annotations

from openvelox.io.lazy import LazyArray
from openvelox.io.velox_emd import read_emd
from openvelox.models import DatasetKind


def test_public_si_spectrum_stream(public_si_emd) -> None:
    exp = read_emd(public_si_emd, lazy=True)
    assert exp.metadata.get("velox") is True
    images = [ds for ds in exp.datasets if ds.kind in {DatasetKind.IMAGE, DatasetKind.STACK}]
    assert images
    assert any(isinstance(ds.data, LazyArray) and not ds.data.materialized() for ds in images)
    haadf = next((ds for ds in exp.datasets if "haadf" in ds.name.lower()), None)
    assert haadf is not None
    assert haadf.metadata.get("high_tension_kv") == 300
    arr = haadf.materialize()
    assert arr.ndim in {2, 3}
    assert arr.shape[-2] == 16 and arr.shape[-1] == 16

    si = next(ds for ds in exp.datasets if ds.kind is DatasetKind.SPECTRUM_IMAGE)
    assert isinstance(si.data, LazyArray)
    assert si.data.materialized() is False
    cube = si.materialize()
    assert cube.shape[:2] == (16, 16)
    assert cube.shape[-1] == 4096
    assert cube.sum() > 1000


def test_public_tem_stack_lazy(public_stack_emd) -> None:
    exp = read_emd(public_stack_emd, lazy=True)
    assert exp.datasets
    stack = exp.datasets[0]
    assert stack.kind is DatasetKind.STACK
    assert isinstance(stack.data, LazyArray)
    arr = stack.materialize()
    assert arr.ndim == 3
    assert arr.shape == (2, 3, 3)


def test_public_dpc_titles(public_dpc_emd) -> None:
    exp = read_emd(public_dpc_emd, lazy=True)
    names = {ds.name for ds in exp.datasets}
    # Display labels such as DF4-A / iDPC should survive the ImageDisplay walk.
    assert any("DF4" in n or "DPC" in n or "iDPC" in n for n in names)
    for ds in exp.datasets:
        img = ds.image2d()
        assert img.ndim == 2
        assert img.size > 0


def test_public_eels_and_eds_stream(public_eels_emd) -> None:
    exp = read_emd(public_eels_emd, lazy=True)
    kinds = {ds.kind for ds in exp.datasets}
    assert DatasetKind.SPECTRUM_IMAGE in kinds
    eels = [ds for ds in exp.datasets if ds.detector == "EELS"]
    assert eels
    cube = eels[0].materialize()
    assert cube.ndim == 3
    assert cube.shape[0] == 16 and cube.shape[1] == 20
    streams = [ds for ds in exp.datasets if "stream" in ds.name.lower() or ds.detector.startswith("UltraX")]
    assert streams
    si = next(ds for ds in exp.datasets if ds.name.startswith("EDS SI"))
    rec = si.materialize()
    assert rec.shape[:2] == (16, 20)
    assert rec.sum() >= 0
