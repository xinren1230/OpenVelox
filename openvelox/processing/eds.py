"""EDS: sum spectra, peak ID, window maps, overlay, Cliff-Lorimer, PCA, line scans."""

from __future__ import annotations

from typing import Iterable

import numpy as np

from openvelox.processing.xray_lines import (
    K_FACTORS_VS_SI,
    atomic_mass,
    family_children,
    match_peak,
    preferred_line,
)


def energy_axis(n: int, scale: float = 0.01, offset: float = 0.0) -> np.ndarray:
    return offset + np.arange(n, dtype=np.float64) * scale


def sum_spectrum(si: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    from openvelox.io.lazy import LazyArray, sum_lazy_si

    if mask is None and isinstance(si, LazyArray) and si.has_slicer() and not si.materialized():
        return sum_lazy_si(si)
    cube = np.asarray(si, dtype=np.float64)
    if cube.ndim != 3:
        raise ValueError("Spectrum image must be (y, x, energy)")
    if mask is None:
        return cube.sum(axis=(0, 1))
    m = np.asarray(mask, dtype=bool)
    if m.shape != cube.shape[:2]:
        raise ValueError("Mask shape must match spatial dimensions")
    return cube[m].sum(axis=0)


def snip_background(spectrum: np.ndarray, iterations: int = 24) -> np.ndarray:
    """SNIP-like background estimate on a 1-D spectrum."""
    spec = np.asarray(spectrum, dtype=np.float64)
    if spec.size == 0:
        return spec.copy()
    spec = np.clip(spec, 0, None)
    work = np.log(np.log(spec + 1.0) + 1.0)
    for p in range(1, iterations + 1):
        padded = np.pad(work, p, mode="edge")
        left = padded[:-2 * p]
        right = padded[2 * p:]
        mid = work
        work = np.minimum(mid, 0.5 * (left + right))
    bg = np.exp(np.exp(work) - 1.0) - 1.0
    return np.clip(bg, 0, None)


def linear_background(spectrum: np.ndarray, energy: np.ndarray | None = None) -> np.ndarray:
    """Straight-line continuum between the first and last 5 % of channels."""
    spec = np.asarray(spectrum, dtype=np.float64)
    if spec.size == 0:
        return spec.copy()
    n = int(spec.size)
    win = max(3, n // 20)
    left = float(np.median(spec[:win]))
    right = float(np.median(spec[-win:]))
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    bg = left + (right - left) * t
    return np.clip(np.minimum(bg, spec), 0, None)


def velox_background(
    spectrum: np.ndarray,
    energy: np.ndarray | None = None,
    *,
    iterations: int = 40,
) -> np.ndarray:
    """Velox-like continuum: SNIP seed, then ``a + b/E + c E`` on trough channels."""
    spec = np.asarray(spectrum, dtype=np.float64)
    if spec.size == 0:
        return spec.copy()
    seed = snip_background(spec, iterations=iterations)
    if energy is None:
        e = np.arange(spec.size, dtype=np.float64) * 0.01 + 0.05
    else:
        e = np.clip(np.asarray(energy, dtype=np.float64), 0.05, None)
        if e.size != spec.size:
            e = np.linspace(float(e[0]) if e.size else 0.05, float(e[-1]) if e.size else 20.0, spec.size)
    resid = spec - seed
    mask = resid <= np.percentile(resid, 45)
    if int(mask.sum()) < 8:
        return seed
    design = np.column_stack([np.ones(int(mask.sum())), 1.0 / e[mask], e[mask]])
    coef, *_ = np.linalg.lstsq(design, spec[mask], rcond=None)
    bg = coef[0] + coef[1] / e + coef[2] * e
    return np.clip(np.minimum(np.maximum(bg, 0.0), spec), 0, None)


def spectrum_background(
    spectrum: np.ndarray,
    energy: np.ndarray | None = None,
    method: str = "snip",
    **kwargs,
) -> np.ndarray:
    """Linear / SNIP / Velox-like background under a 1-D EDS spectrum."""
    kind = str(method or "snip").lower()
    if kind in {"linear", "line"}:
        return linear_background(spectrum, energy)
    if kind in {"velox", "physical", "continuum"}:
        return velox_background(spectrum, energy, iterations=int(kwargs.get("iterations") or 40))
    return snip_background(spectrum, iterations=int(kwargs.get("iterations") or 24))


def deconvolve_families(peaks: list[dict[str, object]]) -> list[dict[str, object]]:
    """Re-assign Kb/Lb satellites to the parent element instead of a second ID."""
    out = [dict(p) for p in peaks]
    ordered = sorted(out, key=lambda p: float(p.get("counts") or 0), reverse=True)
    primaries: dict[str, str] = {}
    for peak in ordered:
        cands = list(peak.get("candidates") or [])
        assigned = False
        for symbol, line, e0, _delta in cands:
            parent = primaries.get(str(symbol))
            if parent and str(line) in family_children(parent):
                peak["symbol"] = symbol
                peak["line"] = line
                peak["line_energy"] = e0
                peak["family"] = True
                assigned = True
                break
        if assigned:
            continue
        if not cands:
            peak["family"] = False
            continue

        def _score(item: tuple) -> tuple:
            symbol, line, _e0, delta = item
            rank = {"Ka": 0, "La": 1, "Ma": 2, "Kb": 3, "Lb": 4}.get(str(line), 5)
            already = 8 if symbol in primaries else 0
            return (already, rank, float(delta))

        symbol, line, e0, _delta = sorted(cands, key=_score)[0]
        peak["symbol"] = symbol
        peak["line"] = line
        peak["line_energy"] = e0
        peak["family"] = bool(str(line) in family_children(primaries.get(str(symbol), "")))
        if str(line) in {"Ka", "La", "Ma"} and str(symbol) not in primaries:
            primaries[str(symbol)] = str(line)
    out.sort(key=lambda p: float(p.get("energy_kev") or 0))
    return out


def identify_peaks(
    energy: np.ndarray,
    spectrum: np.ndarray,
    *,
    prominence: float | None = None,
    distance: int = 6,
    tolerance: float = 0.08,
    max_peaks: int = 16,
    bg_method: str = "snip",
    deconvolve: bool = True,
) -> list[dict[str, object]]:
    spec = np.asarray(spectrum, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64)
    if spec.size == 0 or energy.size == 0:
        return []
    bg = spectrum_background(spec, energy, method=bg_method)
    net = np.clip(spec - bg, 0, None)
    work = net if float(net.max(initial=0.0)) > 0 else spec
    if prominence is None:
        prominence = max(float(np.percentile(work, 85) - np.percentile(work, 40)), work.max() * 0.04)
    from scipy.signal import find_peaks

    peaks, props = find_peaks(work, prominence=prominence, distance=distance)
    order = np.argsort(props["prominences"])[::-1][:max_peaks]
    results = []
    for idx in peaks[order]:
        e = float(energy[idx])
        hits = match_peak(e, tolerance=tolerance)
        best = hits[0] if hits else None
        results.append(
            {
                "channel": int(idx),
                "energy_kev": e,
                "counts": float(spec[idx]),
                "net": float(net[idx]) if idx < net.size else float(spec[idx]),
                "symbol": best[0] if best else None,
                "line": best[1] if best else None,
                "line_energy": best[2] if best else None,
                "candidates": hits[:4],
                "family": False,
                "label": f"{best[0]} {best[1]}".strip() if best else f"{e:.2f} keV",
            }
        )
    if deconvolve:
        results = deconvolve_families(results)
    for row in results:
        if row.get("symbol"):
            row["label"] = f"{row['symbol']} {row.get('line') or ''}".strip()
        else:
            row["label"] = f"{float(row['energy_kev']):.2f} keV"
    results.sort(key=lambda r: r["energy_kev"])  # type: ignore[arg-type, return-value]
    return results


def _window_slice(energy: np.ndarray, center: float, half: float) -> slice:
    lo = float(center - half)
    hi = float(center + half)
    idx = np.where((energy >= lo) & (energy <= hi))[0]
    if idx.size == 0:
        ch = int(np.argmin(np.abs(energy - center)))
        return slice(ch, ch + 1)
    return slice(int(idx[0]), int(idx[-1]) + 1)


def element_map(
    si: np.ndarray,
    energy: np.ndarray,
    symbol: str,
    *,
    half_window: float = 0.08,
    background: bool = True,
    bg_half: float = 0.06,
    bg_gap: float = 0.12,
) -> np.ndarray:
    cube = np.asarray(si, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64)
    pref = preferred_line(symbol, emax=float(energy.max() if energy.size else 20))
    if pref is None:
        cube = np.asarray(si, dtype=np.float64)
        return np.zeros(cube.shape[:2], dtype=np.float64)
    _name, e0 = pref
    sl = _window_slice(energy, e0, half_window)
    peak = cube[:, :, sl].sum(axis=-1)
    if not background:
        return peak
    left = _window_slice(energy, e0 - half_window - bg_gap, bg_half)
    right = _window_slice(energy, e0 + half_window + bg_gap, bg_half)
    n_peak = max(sl.stop - sl.start, 1)
    n_bg = max((left.stop - left.start) + (right.stop - right.start), 1)
    bg = cube[:, :, left].sum(axis=-1) + cube[:, :, right].sum(axis=-1)
    return peak - bg * (n_peak / n_bg)


def color_overlay(
    maps: dict[str, np.ndarray],
    colors: dict[str, tuple[int, int, int]] | None = None,
) -> np.ndarray:
    if not maps:
        raise ValueError("No maps to overlay")
    default = {
        "C": (180, 180, 180),
        "N": (80, 120, 220),
        "O": (220, 40, 40),
        "Si": (80, 200, 80),
        "Cu": (220, 140, 40),
        "Au": (240, 210, 50),
        "Fe": (90, 200, 220),
        "Ti": (180, 80, 200),
    }
    palette = colors or {}
    first = next(iter(maps.values()))
    rgb = np.zeros(first.shape + (3,), dtype=np.float64)
    leftovers = [
        (255, 80, 80),
        (80, 220, 80),
        (80, 140, 255),
        (255, 220, 40),
        (255, 80, 220),
        (40, 220, 220),
    ]
    i = 0
    for symbol, mmap in maps.items():
        arr = np.asarray(mmap, dtype=np.float64)
        arr = np.clip(arr, 0, None)
        if arr.max() > 0:
            hi = float(np.percentile(arr, 99.5))
            arr = np.clip(arr / (hi + 1e-12), 0.0, 1.0)
        color = palette.get(symbol) or default.get(symbol) or leftovers[i % len(leftovers)]
        i += 1
        rgb += arr[..., None] * (np.array(color, dtype=np.float64) / 255.0)
    peak = float(rgb.max())
    if peak > 1.0:
        rgb = rgb / peak
    rgb = np.clip(rgb, 0, 1)
    return (rgb * 255).astype(np.uint8)


def cliff_lorimer(
    intensities: dict[str, float],
    k_factors: dict[str, float] | None = None,
) -> list[dict[str, object]]:
    """Thin-film Cliff–Lorimer: ``C_i / C_Si = k_i * I_i / I_Si`` as weight fraction."""
    ktab = dict(K_FACTORS_VS_SI)
    if k_factors:
        ktab.update(k_factors)
    weights: dict[str, float] = {}
    for symbol, intensity in intensities.items():
        k = float(ktab.get(symbol, 1.5))
        weights[symbol] = max(float(intensity), 0.0) * k
    wtot = sum(weights.values()) or 1.0
    moles = {symbol: w / atomic_mass(symbol) for symbol, w in weights.items()}
    ntot = sum(moles.values()) or 1.0
    rows = []
    for symbol, w in weights.items():
        rows.append(
            {
                "element": symbol,
                "atomic_percent": 100.0 * moles[symbol] / ntot,
                "weight_percent": 100.0 * w / wtot,
                "intensity": float(intensities[symbol]),
                "k_factor": float(ktab.get(symbol, 1.5)),
            }
        )
    rows.sort(key=lambda r: r["atomic_percent"], reverse=True)
    return rows


def pca_denoise(si: np.ndarray, n_components: int = 8) -> np.ndarray:
    cube = np.asarray(si, dtype=np.float64)
    if cube.ndim != 3:
        raise ValueError("Spectrum image must be (y, x, energy)")
    if cube.size == 0:
        return cube
    y, x, e = cube.shape
    mat = cube.reshape(y * x, e)
    mean = mat.mean(axis=0, keepdims=True)
    centered = mat - mean
    # Economy SVD
    u, s, vt = np.linalg.svd(centered, full_matrices=False)
    n = max(1, min(int(n_components), u.shape[1]))
    recon = (u[:, :n] * s[:n]) @ vt[:n] + mean
    return recon.reshape(y, x, e)


def line_scan(si: np.ndarray, p0: tuple[int, int], p1: tuple[int, int], n: int | None = None) -> np.ndarray:
    """Extract spectra along a line → (n_points, energy)."""
    cube = np.asarray(si, dtype=np.float64)
    y0, x0 = p0
    y1, x1 = p1
    length = int(np.hypot(y1 - y0, x1 - x0)) + 1
    n = n or max(length, 2)
    ys = np.linspace(y0, y1, n)
    xs = np.linspace(x0, x1, n)
    out = np.zeros((n, cube.shape[-1]), dtype=np.float64)
    for i, (yy, xx) in enumerate(zip(ys, xs)):
        yi = int(np.clip(round(yy), 0, cube.shape[0] - 1))
        xi = int(np.clip(round(xx), 0, cube.shape[1] - 1))
        out[i] = cube[yi, xi]
    return out


def integrate_windows(
    spectrum: np.ndarray,
    energy: np.ndarray,
    symbols: Iterable[str],
    *,
    bg_method: str = "snip",
    half_window: float = 0.08,
) -> dict[str, float]:
    spec = np.asarray(spectrum, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64)
    out: dict[str, float] = {}
    bg = spectrum_background(spec, energy, method=bg_method)
    net = spec - bg
    for symbol in symbols:
        pref = preferred_line(symbol, emax=float(energy.max() if energy.size else 20))
        if pref is None:
            continue
        sl = _window_slice(energy, pref[1], half_window)
        out[symbol] = float(net[sl].sum())
    return out


def line_scan_element_profile(
    scan: np.ndarray,
    energy: np.ndarray,
    symbol: str,
    *,
    bg_method: str = "snip",
) -> np.ndarray:
    """Net window intensity of ``symbol`` at each point of an EDS line scan."""
    cube = np.asarray(scan, dtype=np.float64)
    if cube.ndim != 2:
        raise ValueError("Line scan must be (position, energy)")
    energy = np.asarray(energy, dtype=np.float64)
    pref = preferred_line(symbol, emax=float(energy.max() if energy.size else 20))
    if pref is None:
        return np.zeros(cube.shape[0], dtype=np.float64)
    sl = _window_slice(energy, pref[1], 0.08)
    out = np.zeros(cube.shape[0], dtype=np.float64)
    for i, spec in enumerate(cube):
        bg = spectrum_background(spec, energy, method=bg_method)
        out[i] = float((spec - bg)[sl].sum())
    return out


def make_element_maps(
    si: np.ndarray,
    energy: np.ndarray,
    symbols: Iterable[str],
    *,
    mode: str = "window",
) -> dict[str, np.ndarray]:
    """Window or Gaussian-net maps for each symbol."""
    out: dict[str, np.ndarray] = {}
    kind = str(mode or "window").lower()
    for symbol in symbols:
        if kind in {"gauss", "gaussian", "net"}:
            out[str(symbol)] = gaussian_net_map(si, energy, str(symbol))
        else:
            out[str(symbol)] = element_map(si, energy, str(symbol))
    return out


def smooth_spectrum(spectrum: np.ndarray, size: int = 5) -> np.ndarray:
    from scipy.ndimage import uniform_filter1d

    return uniform_filter1d(np.asarray(spectrum, dtype=np.float64), size=max(1, int(size)))


def fit_peak_gaussian(
    energy: np.ndarray,
    spectrum: np.ndarray,
    center: float,
    half_window: float = 0.18,
) -> dict[str, float]:
    """Fit ``A * exp(-(E-mu)^2 / (2 sig^2)) + B + C*E`` around ``center``."""
    e = np.asarray(energy, dtype=np.float64)
    y = np.asarray(spectrum, dtype=np.float64)
    mask = (e >= center - half_window) & (e <= center + half_window)
    if mask.sum() < 5:
        return {"amplitude": 0.0, "mu": center, "sigma": half_window / 2.5, "net": 0.0}
    ee, yy = e[mask], y[mask]
    bg = np.linspace(yy[0], yy[-1], yy.size)
    net = np.clip(yy - bg, 0, None)
    weights = net + 1e-6
    mu = float(np.average(ee, weights=weights))
    var = float(np.average((ee - mu) ** 2, weights=weights))
    sigma = max(np.sqrt(max(var, 1e-8)), (ee[1] - ee[0]) * 0.6)
    gauss = np.exp(-((ee - mu) ** 2) / (2 * sigma**2))
    # amplitude from linear LS against the gaussian (bg already subtracted)
    denom = float(np.dot(gauss, gauss)) or 1.0
    amp = float(np.dot(gauss, net) / denom)
    return {
        "amplitude": amp,
        "mu": mu,
        "sigma": sigma,
        "net": float(amp * sigma * np.sqrt(2 * np.pi) / max(ee[1] - ee[0], 1e-9)),
    }


def gaussian_net_map(
    si: np.ndarray,
    energy: np.ndarray,
    symbol: str,
    *,
    half_window: float = 0.18,
) -> np.ndarray:
    """Net-count map: fit the line on the sum spectrum, then scale each pixel."""
    cube = np.asarray(si, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64)
    pref = preferred_line(symbol, emax=float(energy.max() if energy.size else 20))
    if pref is None:
        return np.zeros(cube.shape[:2], dtype=np.float64)
    _name, e0 = pref
    summed = cube.sum(axis=(0, 1))
    fit = fit_peak_gaussian(energy, summed, e0, half_window=half_window)
    sigma = max(fit["sigma"], 1e-4)
    gauss = np.exp(-((energy - fit["mu"]) ** 2) / (2 * sigma**2))
    # Linear LS per pixel: A = (G·y) / (G·G), then net area.
    g2 = float(np.dot(gauss, gauss)) or 1.0
    de = float(energy[1] - energy[0]) if energy.size > 1 else 0.01
    # Subtract a local linear background per pixel using window edges.
    sl = _window_slice(energy, fit["mu"], half_window)
    g_win = gauss[sl]
    g2w = float(np.dot(g_win, g_win)) or 1.0
    patch = cube[:, :, sl]
    left = patch[:, :, :1]
    right = patch[:, :, -1:]
    t = np.linspace(0, 1, patch.shape[-1], dtype=np.float64)
    bg = left + (right - left) * t
    net = np.clip(patch - bg, 0, None)
    amp = (net * g_win).sum(axis=-1) / g2w
    return amp * sigma * np.sqrt(2 * np.pi) / max(de, 1e-9)


# Very rough mass-absorption coefficients (cm^2/g) at the preferred K/L line.
_MU_RHO = {
    "C": 2500,
    "N": 1800,
    "O": 1200,
    "Al": 90,
    "Si": 65,
    "Ti": 110,
    "Fe": 70,
    "Cu": 50,
    "Au": 120,
    "Pt": 115,
}


def absorption_factor(
    symbol: str,
    *,
    thickness_nm: float,
    density_g_cm3: float = 5.0,
    takeoff_rad: float = 0.35,
) -> float:
    """Thin-film absorption correction ``1 / f(χ)`` (Philibert-like, first order)."""
    mu = float(_MU_RHO.get(symbol, 80.0))
    chi = mu / max(np.sin(takeoff_rad), 0.05)
    t_cm = max(float(thickness_nm), 0.0) * 1e-7
    arg = chi * density_g_cm3 * t_cm
    if arg < 1e-8:
        return 1.0
    # Transmission averaged through a slab: (1-exp(-arg))/arg
    trans = (1.0 - np.exp(-arg)) / arg
    return float(1.0 / max(trans, 1e-6))


def cliff_lorimer_abs(
    intensities: dict[str, float],
    k_factors: dict[str, float] | None = None,
    *,
    thickness_nm: float = 0.0,
    density_g_cm3: float = 5.0,
    takeoff_rad: float = 0.35,
) -> list[dict[str, object]]:
    corrected = {}
    for symbol, intensity in intensities.items():
        fac = absorption_factor(
            symbol, thickness_nm=thickness_nm, density_g_cm3=density_g_cm3, takeoff_rad=takeoff_rad
        )
        corrected[symbol] = float(intensity) * fac
    rows = cliff_lorimer(corrected, k_factors=k_factors)
    for row in rows:
        row["absorption_factor"] = absorption_factor(
            str(row["element"]),
            thickness_nm=thickness_nm,
            density_g_cm3=density_g_cm3,
            takeoff_rad=takeoff_rad,
        )
        row["thickness_nm"] = thickness_nm
    return rows


def export_line_scan_csv(path, energy: np.ndarray, scan: np.ndarray) -> None:
    import csv
    from pathlib import Path

    path = Path(path)
    energy = np.asarray(energy).ravel()
    scan = np.asarray(scan)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["position_index", *[f"{e:.4f}keV" for e in energy]])
        for i, row in enumerate(scan):
            w.writerow([i, *[f"{float(v):.6g}" for v in row]])
