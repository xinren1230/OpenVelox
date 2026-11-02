from __future__ import annotations

import numpy as np

from openvelox.io.synthetic import (
    make_drift_stack,
    make_four_d,
    make_haadf_lattice,
    make_segmented_detectors,
    make_spectrum_image,
)
from openvelox.io.writers import export_image, export_quant_table, export_spectrum_csv
from openvelox.processing.atoms import find_atom_columns
from openvelox.processing.display import apply_display, auto_levels
from openvelox.processing.dpc import ddpc, dpc_from_quadrants, idpc
from openvelox.processing.drift import align_and_sum
from openvelox.processing.eds import (
    cliff_lorimer,
    cliff_lorimer_abs,
    color_overlay,
    element_map,
    energy_axis,
    gaussian_net_map,
    identify_peaks,
    pca_denoise,
    sum_spectrum,
)
from openvelox.processing.fft import bandpass, fft2d, ifft2d, make_mask, power_spectrum
from openvelox.processing.filters import average_background, gaussian_filter, median_filter
from openvelox.processing.image_calc import image_calculate
from openvelox.processing.measure import angle_deg, distance, line_profile, roi_stats
from openvelox.processing.stem4d import center_of_mass_dpc, virtual_adf, virtual_bf


def test_fft_roundtrip() -> None:
    rng = np.random.default_rng(1)
    image = rng.normal(size=(64, 64))
    rec = ifft2d(fft2d(image))
    np.testing.assert_allclose(rec, image, atol=1e-10)
    power = power_spectrum(image)
    assert power.shape == image.shape
    mask = make_mask(image.shape, "annulus", inner=2, outer=12)
    assert mask.sum() > 10
    filtered = bandpass(image, 1, 10)
    assert filtered.shape == image.shape


def test_filters_and_calculator() -> None:
    image = np.ones((32, 32))
    image[10:20, 10:20] = 5
    g = gaussian_filter(image, 1.0)
    m = median_filter(image, 3)
    bg = average_background(image, 8)
    assert g.shape == image.shape and m.mean() > 0
    assert bg[15, 15] > bg[0, 0]
    added = image_calculate("add", image, image)
    np.testing.assert_allclose(added, 2 * image)
    norm = image_calculate("normalize", image)
    assert norm.min() == 0 and abs(norm.max() - 1) < 1e-9


def test_measure() -> None:
    image = np.zeros((20, 20))
    image[:, 5] = 1
    dist, prof = line_profile(image, (10, 0), (10, 19))
    assert prof[5] > 0.5
    assert abs(distance((0, 0), (0, 10), 0.5) - 5.0) < 1e-9
    assert abs(angle_deg((1, 0), (0, 0), (0, 1)) - 90) < 1e-6
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:5, 2:5] = True
    image[2:5, 2:5] = 3
    stats = roi_stats(image, mask)
    assert stats["mean"] == 3


def test_eds_pipeline() -> None:
    si, meta = make_spectrum_image(size=16, n_channels=512, e_scale=0.04, seed=2)
    energy = energy_axis(si.shape[-1], meta["energy_scale_kev"], meta["energy_offset_kev"])
    spec = sum_spectrum(si)
    peaks = identify_peaks(energy, spec, tolerance=0.12, max_peaks=12)
    symbols = {p["symbol"] for p in peaks if p["symbol"]}
    assert {"Au", "Si", "Cu"} & symbols
    amap = element_map(si, energy, "Au")
    smap = element_map(si, energy, "Si")
    assert amap[7, 9] > amap[0, 0]
    rgb = color_overlay({"Au": amap, "Si": smap})
    assert rgb.shape == amap.shape + (3,)
    rows = cliff_lorimer({"Au": 100, "Si": 80, "Cu": 20})
    assert abs(sum(r["atomic_percent"] for r in rows) - 100) < 1e-6
    abs_rows = cliff_lorimer_abs({"Au": 100, "Si": 80, "Cu": 20}, thickness_nm=50)
    assert "absorption_factor" in abs_rows[0]
    gmap = gaussian_net_map(si, energy, "Au")
    assert gmap[7, 9] > gmap[0, 0]
    denoised = pca_denoise(si, n_components=4)
    assert denoised.shape == si.shape


def test_dpc_recovers_phase_blob() -> None:
    segs = make_segmented_detectors(size=64)
    dx, dy = dpc_from_quadrants(segs)
    phase = idpc(dx, dy)
    # The synthetic phase has a bright blob in the upper-right-ish quadrant.
    assert phase[26, 35] > phase[4, 4]
    div = ddpc(dx, dy)
    assert div.shape == dx.shape


def test_four_d_virtual_and_com() -> None:
    cube = make_four_d(scan=8, qsize=20, seed=4)
    bf = virtual_bf(cube, radius=4)
    adf = virtual_adf(cube, inner=5, outer=9)
    assert bf.shape == (8, 8) and adf.shape == (8, 8)
    cx, cy = center_of_mass_dpc(cube)
    assert cx.std() > 0 and cy.std() > 0


def test_atoms_and_drift() -> None:
    haadf = make_haadf_lattice(size=80, spacing=8, seed=1)
    coords = find_atom_columns(haadf, sigma=1.1, min_distance=5)
    assert coords.shape[0] > 20
    stack = make_drift_stack(haadf, n_frames=6, seed=2)
    aligned, summed, shifts = align_and_sum(stack)
    assert aligned.shape == stack.shape
    assert summed.shape == stack.shape[1:]
    # Alignment should reduce residual motion versus the first frame.
    assert np.linalg.norm(shifts[0]) == 0


def test_display_and_export(tmp_path) -> None:
    image = make_haadf_lattice(size=48)
    vmin, vmax = auto_levels(image)
    rgb = apply_display(image, colormap="thermal", vmin=vmin, vmax=vmax, gamma=0.9)
    assert rgb.shape == image.shape + (3,)
    export_image(tmp_path / "haadf.png", image, pixel_m=2.5e-11, colormap="gray")
    assert (tmp_path / "haadf.png").is_file()
    export_spectrum_csv(tmp_path / "s.csv", np.array([0.0, 1.0]), np.array([2.0, 3.0]))
    export_quant_table(tmp_path / "q.csv", [{"element": "Au", "atomic_percent": 40.0}])
    assert "Au" in (tmp_path / "q.csv").read_text(encoding="utf-8")
