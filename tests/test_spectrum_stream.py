from __future__ import annotations

import numpy as np

from openvelox.io.spectrum_stream import (
    PIXEL_END,
    decode_spectrum_stream,
    encode_spectrum_stream,
    infer_stream_shape,
    parse_acquisition_settings,
)
from openvelox.io.synthetic import make_spectrum_image, write_synthetic_emd
from openvelox.io.velox_emd import read_emd, write_spectrum_stream_group
from openvelox.models import DatasetKind
from openvelox.io.lazy import LazyArray


def test_encode_decode_roundtrip() -> None:
    cube = np.zeros((4, 5, 16), dtype=np.uint16)
    cube[1, 2, 3] = 4
    cube[3, 4, 7] = 2
    stream, table = encode_spectrum_stream(cube)
    assert stream.dtype == np.uint16
    assert int(stream[stream != PIXEL_END].size) == 6
    rec = decode_spectrum_stream(stream, height=4, width=5, n_channels=16, frame_offsets=table)
    np.testing.assert_array_equal(rec, cube)


def test_multi_frame_stream_sum() -> None:
    frames = np.zeros((2, 3, 3, 8), dtype=np.uint16)
    frames[0, 0, 0, 1] = 3
    frames[1, 2, 2, 1] = 5
    stream, table = encode_spectrum_stream(frames)
    summed = decode_spectrum_stream(stream, height=3, width=3, n_channels=8, frame_offsets=table)
    assert summed[0, 0, 1] == 3
    assert summed[2, 2, 1] == 5
    stacked = decode_spectrum_stream(
        stream, height=3, width=3, n_channels=8, frame_offsets=table, sum_frames=False
    )
    assert stacked.shape == (2, 3, 3, 8)
    assert stacked[1, 2, 2, 1] == 5


def test_infer_shape_prefers_image_over_stale_128() -> None:
    cube = np.zeros((16, 16, 32), dtype=np.uint16)
    cube[0, 0, 1] = 1
    stream, table = encode_spectrum_stream(cube)
    settings = {
        "bincount": "4096",
        "RasterScanDefinition": {"Width": "128", "Height": "128"},
    }
    h, w, ch, nf = infer_stream_shape(stream, table, settings, fallback_hw=(16, 16))
    assert (h, w) == (16, 16)
    assert ch == 4096
    assert nf >= 1


def test_parse_acquisition_settings_bytes() -> None:
    raw = np.array([b'{"bincount": "512", "RasterScanDefinition": {"Width": "8", "Height": "8"}}'])
    parsed = parse_acquisition_settings(raw)
    assert parsed["bincount"] == "512"


def test_synthetic_includes_lazy_stream(tmp_path) -> None:
    path = write_synthetic_emd(tmp_path / "demo.emd")
    exp = read_emd(path, lazy=True)
    streams = [ds for ds in exp.datasets if "stream" in ds.name.lower() or ds.group_id != ""]
    si = [ds for ds in exp.datasets if ds.kind is DatasetKind.SPECTRUM_IMAGE]
    assert si
    lazy_si = next(ds for ds in si if isinstance(ds.data, LazyArray))
    assert lazy_si.data.materialized() is False
    cube = lazy_si.materialize()
    assert cube.ndim == 3
    assert cube.sum() >= 0


def test_write_stream_group_roundtrip(tmp_path) -> None:
    import h5py

    si, _meta = make_spectrum_image(size=8, n_channels=64, e_scale=0.04, seed=3)
    cube = np.clip(si, 0, 4).astype(np.uint16)
    path = tmp_path / "stream.emd"
    with h5py.File(path, "w") as handle:
        handle.create_dataset("Version", data=np.array([b'{"format": "Velox"}'], dtype=object))
        root = handle.create_group("Data/SpectrumStream")
        write_spectrum_stream_group(root, cube, {"CustomProperties": {"DisplayName": {"type": "string", "value": "SI"}}})
    exp = read_emd(path, lazy=True)
    assert exp.datasets
    rec = exp.datasets[0].materialize()
    assert rec.shape[0] == 8 and rec.shape[1] == 8
    assert rec.sum() == cube.sum()
