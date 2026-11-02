from __future__ import annotations

import numpy as np

from openvelox.io.synthetic import make_spectrum_image, write_synthetic_emd
from openvelox.processing.cache import cache_clear, memoize_array
from openvelox.processing.eds import (
    absorption_factor,
    cliff_lorimer,
    cliff_lorimer_abs,
    energy_axis,
    export_line_scan_csv,
    fit_peak_gaussian,
    gaussian_net_map,
    line_scan,
)
from openvelox.ui.session import load_session, save_session
from openvelox.ui.undo import UndoStack
from openvelox.models import Dataset, DatasetKind


def test_gaussian_net_map_peaks_on_particle() -> None:
    si, meta = make_spectrum_image(size=16, n_channels=512, e_scale=0.04, seed=2)
    energy = energy_axis(si.shape[-1], meta["energy_scale_kev"], meta["energy_offset_kev"])
    amap = gaussian_net_map(si, energy, "Au")
    assert amap.shape == si.shape[:2]
    assert amap[7, 9] > amap[0, 0]
    fit = fit_peak_gaussian(energy, si.sum(axis=(0, 1)), 9.713)
    assert fit["net"] > 0
    assert 9.4 < fit["mu"] < 10.1


def test_absorption_and_editable_k() -> None:
    thin = cliff_lorimer({"Au": 100, "Si": 80}, k_factors={"Au": 2.0, "Si": 1.0})
    thick = cliff_lorimer_abs(
        {"Au": 100, "Si": 80},
        k_factors={"Au": 2.0, "Si": 1.0},
        thickness_nm=80,
        density_g_cm3=10.0,
    )
    assert abs(sum(r["atomic_percent"] for r in thin) - 100) < 1e-6
    assert thick[0]["absorption_factor"] >= 1.0
    assert absorption_factor("Au", thickness_nm=0) == 1.0
    au_thin = next(r["atomic_percent"] for r in thin if r["element"] == "Au")
    au_thick = next(r["atomic_percent"] for r in thick if r["element"] == "Au")
    assert au_thin != au_thick


def test_line_scan_export(tmp_path) -> None:
    si, meta = make_spectrum_image(size=12, n_channels=64, e_scale=0.2, seed=1)
    energy = energy_axis(si.shape[-1], meta["energy_scale_kev"], 0.0)
    scan = line_scan(si, (6, 0), (6, 11))
    path = tmp_path / "scan.csv"
    export_line_scan_csv(path, energy, scan)
    text = path.read_text(encoding="utf-8")
    assert "position_index" in text
    assert text.count("\n") >= 12


def test_session_roundtrip(tmp_path) -> None:
    emd = write_synthetic_emd(tmp_path / "a.emd")
    session = tmp_path / "session.openvelox.json"
    save_session(session, {"files": [str(emd)], "language": "zh", "k_factors": {"Au": 1.9}})
    data = load_session(session)
    assert data["language"] == "zh"
    assert data["k_factors"]["Au"] == 1.9
    assert data["files"][0].endswith("a.emd")


def test_undo_stack() -> None:
    ds = Dataset(name="HAADF", kind=DatasetKind.IMAGE, data=np.ones((8, 8)))
    stack = UndoStack()
    stack.push(ds)
    ds.data = np.zeros((8, 8))
    snap = stack.undo(ds)
    assert snap is not None
    np.testing.assert_array_equal(snap.data, np.ones((8, 8)))
    redo = stack.redo(ds)
    assert redo is not None
    np.testing.assert_array_equal(redo.data, np.zeros((8, 8)))


def test_array_cache() -> None:
    cache_clear()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return np.arange(4)

    a = memoize_array("k", factory)
    b = memoize_array("k", factory)
    assert calls["n"] == 1
    np.testing.assert_array_equal(a, b)
    cache_clear()
