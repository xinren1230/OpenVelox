<p align="center"><img src="openvelox/resources/logo.png" width="120"></p>

# OpenVelox

[中文说明](README.zh-CN.md) · License: GPL-3.0

OpenVelox is a free, open-source alternative to Thermo Fisher Velox for viewing and analysing TEM/STEM data on Windows.

**Opens:** Velox `.emd` (incl. EDS SpectrumStream), TIA `.ser/.emi`, DigitalMicrograph `.dm3/.dm4`, TIFF.

**Does:** image display & contrast/LUTs, multi-panel linked views, metadata, FFT with masks and d-spacing, filters & background subtraction, drift-corrected frame integration (DCFI), measurements & annotations with scale bar export, EDS peak ID / Cliff-Lorimer quantification / maps / line scans, 4D-STEM virtual BF/ADF/ABF, CoM/DPC/iDPC, reports (PDF/HTML/PPTX) and session save.

## Install (one click)

1. Download **OpenVelox-Setup-0.5.0.exe** from [Releases](https://github.com/xinren1230/OpenVelox/releases/latest).
2. Double-click it and follow the installer. No Python or admin rights needed.
3. Start OpenVelox from the Start menu or desktop, then drag a data file into the window.

## Quick use

- **Open:** `Ctrl+O` or drag & drop. Double-click an item in the experiment browser to view it.
- **Measure:** `L` line, `D` distance, `R` region; `Esc` back to pointer.
- **FFT:** `Ctrl+F`, draw a mask, apply inverse FFT; click two spots for d-spacing.
- **EDS:** open a spectrum image, pick elements, choose background, read wt.%/at.%, show maps.
- **Export:** `Ctrl+E` image with scale bar, `Ctrl+Shift+R` report.

Logs: `%LOCALAPPDATA%\OpenVelox\logs`. Please attach them when opening an issue.

## Run from source

```
pip install -r requirements.txt
python -m openvelox
```

Built on PySide6, pyqtgraph, HyperSpy/RosettaSciIO, ncempy, py4DSTEM and Atomap.
