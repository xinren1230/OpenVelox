# Changelog

All notable changes to OpenVelox are documented here. Versions follow the public GitHub release numbers.

## 0.6.0 — 2026-11-02

Startup, expression calculator, Super-X / DF mixing, and lazy large-data I/O.

- **Startup:** splash before the main window; SciPy / scikit-image / HyperSpy / py4DSTEM / reportlab / pptx load only when used. PyInstaller **onedir** and onefile share the same resource lookup (`sys._MEIPASS` or the package dir — no onefile-temp assumptions).
- **Image calculator:** expressions `A+B`, `A-B`, `A*B`, `A/B` (safe divide), ratios, constants, `abs` / `log` / `sqrt`. Shape checks. Result is a new image with the source calibration.
- **Super-X mixer:** weight per-detector EDS streams; the sum spectrum and maps update live. DF4-A–D (segmented STEM) mix the same way.
- **Large 4D / SI:** HDF5 slicers plus optional `numpy.memmap`; virtual detectors and SI sums walk the cube in row chunks.
- Tests: `tests/test_round6.py`. Import probe: `python scripts/measure_import.py`.

---

## 0.5.0 — 2026-11-02

Public release on [github.com/xinren1230/OpenVelox](https://github.com/xinren1230/OpenVelox). License is **GPL-3.0**. Author: **Xinren Chen**. Windows installer: `OpenVelox-Setup-0.5.0.exe` (Inno Setup, `packaging/openvelox.iss`).

### 4D-STEM and reporting (parity round 5)

- Virtual **BF / ADF / ABF** detectors (disk or annulus; px or mrad).
- Center-of-mass DPC, iDPC, and dDPC; DF4 quadrants or 4D CoM fallback.
- Diffraction calibration: relativistic λ(HV), q in Å⁻¹/px, pattern rotation.
- Detector cartoon on the 4D-STEM pane.
- Report export: **PDF / HTML / PPTX** (`File → Export report`).
- Session format **v3**: files, k-factors, chrome, tile layout, linked views, diffraction.
- Main toolbar `objectName=mainToolbar` so `QMainWindow.saveState()` no longer warns.

### EDS (parity round 4)

- Peak ID with Ka/Kb · La/Lb family labels after linear / SNIP / Velox-like background.
- Cliff–Lorimer wt.% from `k · I`, at.% via atomic weight; editable k vs Si.
- Window or Gaussian-net elemental maps, colour overlay mixer.
- Interactive line-scan path and ROI spectra.

### Measurement and annotation (parity round 3)

- Distance, angle, rectangle / ellipse / polygon area, ROI histogram.
- FFT d-spacing (DC→spot or Bragg pair).
- Scale-bar styling and overlay export.

### Image processing (parity round 2)

- FFT masks (circle / annulus / rect), invert, soft edge, iFFT, live preview.
- DCFI (first / previous / mean reference, high-pass, max-shift, overlap crop).
- Average / rolling-ball / plane / constant background; LUT library + histogram window/level.

### Workspace (parity round 1)

- Experiment browser with thumbnails and filter.
- Full Velox acquisition metadata tree.
- Linked multi-panel layouts 1×1 … 2×3.

### Packaging and docs

- Version **0.5.0** in the package, About box, and synthetic EMD writer.
- Bilingual README (`README.md`, `README.zh-CN.md`).
- Fresh offscreen screenshot gallery under `docs/screenshots/`.
- `LICENSE` is the GNU GPL v3. `.gitignore` excludes `.venv`, `build`, `dist`, `*.exe`, `__pycache__`.

### Still partial vs Velox

- Image calculator: four arithmetic ops + invert / normalize (no expression editor).
- Super-X / SpectrumStream: sparse decode + per-detector SI (no live multi-detector mixer).

---

## 0.3.0

Internal source snapshot that the 0.5.0 parity work started from: Velox EMD / SER / DM / TIFF readers, lazy arrays, SpectrumStream codec, bilingual UI, synthetic sample, PyInstaller spec.
