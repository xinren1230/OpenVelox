#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --clean packaging/openvelox.spec
echo "Built dist/OpenVelox/OpenVelox"
