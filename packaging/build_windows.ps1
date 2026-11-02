# One-command Windows build (run from the repo root in PowerShell).
# Prerequisites: Python 3.10+ on PATH.
$ErrorActionPreference = "Stop"
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean packaging/openvelox.spec
Write-Host "Built dist/OpenVelox/OpenVelox.exe"
Write-Host "For a portable build, zip dist/OpenVelox."
Write-Host "For the GitHub installer, copy a one-file OpenVelox.exe to the repo root and run:"
Write-Host "  iscc packaging/openvelox.iss"
Write-Host "That writes dist/OpenVelox-Setup-0.6.0.exe"
