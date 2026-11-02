#!/usr/bin/env python3
"""Measure OpenVelox import time and whether heavy modules load at startup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAVY = ("scipy", "skimage", "hyperspy", "py4DSTEM", "reportlab", "pptx")


def _run(code: str) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return subprocess.check_output([sys.executable, "-c", code], env=env, text=True)


def main() -> int:
    print("OpenVelox 0.6.0 import probe (fresh process each row)")
    print("0.5.0 baseline (pre-lazy): main_window 1.184 s, scipy=True")
    print()
    snippets = {
        "openvelox": "import time,sys; t=time.perf_counter(); import openvelox; "
        "print(f'{time.perf_counter()-t:.3f}'); "
        "print(','.join(m for m in ('scipy','skimage','hyperspy','py4DSTEM','reportlab','pptx') if m in sys.modules))",
        "app+splash": "import time,sys,os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "t=time.perf_counter(); import openvelox.app, openvelox.ui.splash; "
        "print(f'{time.perf_counter()-t:.3f}'); "
        "print(','.join(m for m in ('scipy','skimage','hyperspy','py4DSTEM','reportlab','pptx') if m in sys.modules))",
        "main_window": "import time,sys,os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "t=time.perf_counter(); import openvelox.ui.main_window; "
        "print(f'{time.perf_counter()-t:.3f}'); "
        "print(','.join(m for m in ('scipy','skimage','hyperspy','py4DSTEM','reportlab','pptx') if m in sys.modules))",
    }
    for name, code in snippets.items():
        out = _run(code).strip().splitlines()
        elapsed = out[0] if out else "?"
        loaded = out[1] if len(out) > 1 else ""
        print(f"{name:12} {elapsed:>8}s   heavy={loaded or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
