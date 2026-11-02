from __future__ import annotations

from pathlib import Path

import numpy as np

from openvelox.io.dm import read_dm, write_simple_dm3
from openvelox.io.readers import load_path
from openvelox.io.ser import read_ser, write_simple_ser
from openvelox.io.synthetic import write_synthetic_emd
from openvelox.io.tiff_io import read_tiff, write_tiff
from openvelox.io.velox_emd import read_emd
from openvelox.models import DatasetKind


def test_synthetic_emd_roundtrip(tmp_path: Path) -> None:
    path = write_synthetic_emd(tmp_path / "demo.emd")
    exp = read_emd(path)
    names = {ds.name for ds in exp.datasets}
    assert "HAADF" in names
    assert "BF" in names
    assert "EDS SI" in names
    assert "4D-STEM" in names
    assert {"DF4-A", "DF4-B", "DF4-C", "DF4-D"} <= names
    haadf = next(ds for ds in exp.datasets if ds.name == "HAADF")
    assert haadf.kind is DatasetKind.IMAGE
    assert haadf.data.ndim == 2
    assert haadf.metadata.get("high_tension_kv") == 200
    assert haadf.pixel_size_m() > 0
    si = next(ds for ds in exp.datasets if ds.name == "EDS SI")
    assert si.kind is DatasetKind.SPECTRUM_IMAGE
    assert si.shape[-1] >= 64
    fourd = next(ds for ds in exp.datasets if ds.kind is DatasetKind.FOUR_D)
    assert fourd.shape[0] >= 2
    stack = next(ds for ds in exp.datasets if ds.kind is DatasetKind.STACK)
    assert len(stack.shape) == 3
    # Large cubes stay lazy until viewed.
    from openvelox.io.lazy import LazyArray

    assert isinstance(haadf.data, LazyArray)
    assert haadf.data.materialized() is False
    assert haadf.materialize().ndim == 2


def test_load_path_dispatch(tmp_path: Path) -> None:
    path = write_synthetic_emd(tmp_path / "a.emd")
    exp = load_path(path)
    assert exp.datasets


def test_tiff_roundtrip(tmp_path: Path) -> None:
    image = (np.arange(64 * 48).reshape(64, 48) % 1000).astype(np.uint16)
    path = tmp_path / "frame.tif"
    write_tiff(path, image, pixel_m=2.5e-11)
    exp = read_tiff(path)
    assert exp.datasets[0].data.shape == image.shape
    np.testing.assert_array_equal(exp.datasets[0].data, image)
    assert abs(exp.datasets[0].metadata["pixel_size_m"] - 2.5e-11) / 2.5e-11 < 0.05


def test_ser_roundtrip(tmp_path: Path) -> None:
    image = np.linspace(0, 1, 40 * 30, dtype=np.float32).reshape(40, 30)
    path = tmp_path / "tia.ser"
    write_simple_ser(path, image, pixel_m=1.2e-10)
    exp = read_ser(path)
    np.testing.assert_allclose(exp.datasets[0].data, image, rtol=1e-5)
    assert abs(exp.datasets[0].pixel_size_m() - 1.2e-10) < 1e-14


def test_dm3_roundtrip(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    image = rng.integers(0, 4000, size=(36, 48), dtype=np.uint16)
    path = tmp_path / "frame.dm3"
    write_simple_dm3(path, image, scale_m=5e-11)
    exp = read_dm(path)
    assert exp.datasets[0].data.shape == image.shape
    np.testing.assert_array_equal(exp.datasets[0].data, image)
    assert abs(exp.datasets[0].metadata["pixel_size_m"] - 5e-11) < 1e-15
    assert exp.datasets[0].metadata.get("high_tension_v") == 200000.0
