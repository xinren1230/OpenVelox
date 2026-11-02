# OpenVelox ↔ Thermo Fisher Velox parity

OpenVelox 0.6.0 is an independent open-source TEM/STEM analysis app
([github.com/xinren1230/OpenVelox](https://github.com/xinren1230/OpenVelox),
GPL-3.0, author Xinren Chen). The goal is to match **Thermo Fisher Velox**
workflows closely enough that a microscopist can open the same `.emd` session
and do the same inspection, processing, EDS, and 4D-STEM steps without hunting
for a missing pane.

This file is the living checklist. Status values:

| Status | Meaning |
| --- | --- |
| **done** | Shipped in this tree and covered by tests |
| **partial** | Present but narrower than Velox |
| **planned** | Scheduled for a later round — do not implement until that round |
| **out of scope** | Microscope control / licensing / proprietary GPU paths |

OpenVelox is **not affiliated with Thermo Fisher Scientific**.

---

## Round 1 — workspace

| Velox feature | Status | OpenVelox |
| --- | --- | --- |
| Experiment / data browser | **done** | Left dock: file → kind groups → datasets |
| Dataset thumbnails | **done** | 40 px preview (image / SI / 4D / spectrum sparkline) |
| Filter / search in browser | **done** | Name, kind, detector filter box |
| Click inspects, double-click opens | **done** | Click updates metadata; double-click opens a view |
| Full acquisition metadata | **done** | Optics / Scan / Stage / Instrument / Detector / Calibration / Sample + raw tree |
| Metadata search | **done** | Filter box on the Info tab |
| Key Velox fields (HV, mag, dwell, CL, α/β, beam current, …) | **done** | Flattened from Velox JSON leaves |
| Multi-panel layouts 1×1 / 1×2 / 2×1 / 2×2 / 1×3 / 2×3 | **done** | View → Layout |
| Linked zoom / pan | **done** | View → Synchronize zoom; pixel-size-aware range copy |
| Active panel highlight | **done** | Cyan frame on the focused tile |
| Window icon | **done** | `openvelox/resources/openvelox.ico` (MEIPASS / package; placeholder only if missing) |

Later rounds must not regress these.

---

## Round 2 — image processing

| Velox feature | Status | OpenVelox |
| --- | --- | --- |
| FFT power spectrum | **done** | Log power, DC notch, thermal LUT |
| FFT masks (circle / annulus / rect) + invert | **done** | Draggable ROI on the FFT + numeric radii + invert |
| Soft-edge mask | **done** | Gaussian feather before iFFT |
| iFFT reconstruction | **done** | Apply + optional live preview tab |
| Mask overlay on FFT | **done** | Cyan translucent overlay |
| DCFI / drift-corrected frame integration | **done** | first / previous / mean reference, mean or sum, high-pass correlation, max-shift reject, overlap crop, drift-magnitude plot |
| Align and sum | **done** | Kept as DCFI(sum, no crop) |
| Background subtraction | **done** | Average, rolling ball, plane, constant percentile |
| Contrast / brightness / gamma | **done** | Sliders + histogram window/level region linked to the image |
| LUT / colormap library | **done** | gray / gray_inv / thermal / fire / ice / glow / green / red / bone + scientific set; invert; load ImageJ `.lut` or CSV |
| Unsharp / Sobel / high-pass / median / Wiener | **done** | Unchanged |
| Image calculator | **done** | Expressions: A±B, A*B, A/B (safe), ratios, constants, abs/log/sqrt |

Later rounds must not regress these.

---

## Round 3 — measurement & annotation

| Velox feature | Status | OpenVelox |
| --- | --- | --- |
| Distance | **done** | Two-click; calibrated label + line overlay |
| Angle | **done** | Three-click; stored as an overlay |
| Area / ROI stats | **done** | Rect / ellipse / polygon; n, mean, calibrated area |
| Line profile + FWHM | **done** | Adjustable width (unchanged) |
| ROI intensity histogram | **done** | Display dock; masked bins from the active ROI |
| d-spacing from FFT | **done** | Two clicks: DC→spot `d=1/|g|`, spot–spot `d=2/|Δg|` |
| Annotations | **done** | Line / angle / rect / ellipse / polygon / text stay on the canvas |
| Scale bar styling | **done** | Color, length lock, font, position, thickness, hide |
| Overlay / annotation export | **done** | PNG/TIFF burns annotations + styled scale bar (`File → Export overlay`) |

---

## Round 4 — EDS

| Velox feature | Status | OpenVelox |
| --- | --- | --- |
| Periodic table picker | **done** | Click-to-select; auto-filled from peak ID |
| Auto peak ID / element labels | **done** | Background-subtracted find_peaks + Ka/Kb, La/Lb family deconvolution |
| Peak labels on spectrum | **done** | Line name + staggered labels; family lines in muted gold |
| Background models | **done** | Linear / SNIP / Velox-like (`a + b/E + cE`) on the EDS dock |
| Cliff–Lorimer + k-factors | **done** | Editable k vs Si; wt.% from `k·I`, at.% via atomic weight |
| Absorption correction | **done** | Thin-film path-length factor (unchanged) |
| Element maps | **done** | Window or Gaussian net-count from the map-mode combo |
| Color overlay mixer | **done** | Per-element opacity sliders on the last map set |
| Line scans | **done** | Drawn line-profile path, else mid-row; elemental profile + CSV |
| ROI spectra | **done** | Rect / ellipse / polygon sum + background + peak labels |
| Super-X / SpectrumStream | **done** | Per-detector SI + live Super-X / DF4 weight mixer |

---

## Round 5 — 4D-STEM & reporting (this release)

| Velox feature | Status | OpenVelox |
| --- | --- | --- |
| Virtual BF / ADF | **done** | Disk / annulus; px or mrad (camera length + detector pixel) |
| Virtual ABF | **done** | Inner/outer bright-field ring + detector cartoon |
| DPC / iDPC / dDPC | **done** | DF4 quadrants, or 4D CoM fallback; cartoon cross-hairs |
| Center of mass | **done** | Per-probe CoM, optional rotation / q scaling, iDPC + dDPC |
| Diffraction calibration | **done** | q (Å⁻¹/px) from CL + λ(HV), pattern rotation |
| Report export | **done** | PDF / HTML / PPTX (`File → Export report`) with images, spectrum, quant |
| Session save / restore | **done** | Files, k-factors, chrome, language, layout tiles, sync, diffraction |

Still narrower than Velox: Super-X family deconvolution of every detector line, microscope control.

---

## Round 6 — calculator, Super-X mixer, startup (this release)

| Velox feature | Status | OpenVelox |
| --- | --- | --- |
| Image calculator expressions | **done** | A/B, ratios, constants, abs/log/sqrt; calibration copied |
| Super-X detector mix | **done** | Per-detector weights; live sum spectrum + maps |
| Segmented STEM mix | **done** | DF4-A–D (HAADF/DF) weighted sum |
| Fast open / large 4D & SI | **done** | Lazy HDF5 slicer + optional memmap; row-wise virtual detectors |
| Startup | **done** | Splash, lazy SciPy / HyperSpy / py4DSTEM; PyInstaller onedir + onefile |

---

## Final status

Rounds 1–6 are implemented. Remaining extras, not blockers:

| Item | Why it stays partial |
| --- | --- |
| Super-X family deconvolution | Peak ID is on the mixed sum, not per-detector line families |

---

## Always-on product requirements

- Tests for every new feature; `QT_QPA_PLATFORM=offscreen python -m pytest` green
- PyInstaller onedir/onefile-compatible on Windows (Python 3.12, PySide6):
  resolve resources from `sys._MEIPASS` or the package dir — no onefile-temp assumptions
- `requirements.txt` lists runtime + pytest; optional scientific extras stay in `pyproject.toml`

---

## Roadmap

1. **Round 1:** browser thumbnails, acquisition metadata, linked multi-panel layouts
2. **Round 2:** FFT masks/IFFT, DCFI, background models, contrast/gamma/LUTs
3. **Round 3:** distance/angle/area, FFT d-spacing, histogram, scale-bar styling, overlay export
4. **Round 4:** element ID, peak labels, background models, Cliff–Lorimer, maps, line scans
5. **Round 5 (done):** virtual BF/ADF/ABF/DPC/iDPC, CoM, diffraction calibration, report export, session
6. **Round 6 (done):** expression calculator, Super-X / DF mixer, lazy startup, mmap 4D/SI
