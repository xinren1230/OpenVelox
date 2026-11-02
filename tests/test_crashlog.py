from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from openvelox.crashlog import (
    install,
    log_path,
    report_exception,
    safe_print,
    safe_write,
    widget_alive,
)
from openvelox.paths import is_frozen, resource_path, user_data_dir


def test_safe_write_and_print_tolerate_none() -> None:
    safe_write(None, "should not raise")
    safe_print("hello", file=None)
    old = sys.stderr
    try:
        sys.stderr = None
        safe_print("still ok")
        report_exception(RuntimeError("boom"), where="unit")
    finally:
        sys.stderr = old


def test_install_hooks_and_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENVELOX_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("OPENVELOX_NO_DIALOG", "1")
    import openvelox.crashlog as crashlog

    crashlog._LOGGER = None
    crashlog._INSTALLED = False
    install()
    path = log_path()
    assert path.parent == tmp_path
    report_exception(RuntimeError("slot failed"), where="unit")
    text = path.read_text(encoding="utf-8")
    assert "slot failed" in text
    crash = tmp_path / "crash.log"
    assert crash.is_file()


def test_resource_paths_not_frozen() -> None:
    assert is_frozen() is False
    root = resource_path()
    assert root.is_dir()
    data = user_data_dir()
    assert "OpenVelox" in str(data)


def test_widget_alive_none() -> None:
    assert widget_alive(None) is False


def test_display_and_histogram_nan() -> None:
    from openvelox.processing.display import apply_display, auto_levels

    arr = np.full((4, 4), np.nan)
    vmin, vmax = auto_levels(arr)
    rgb = apply_display(arr, vmin=vmin, vmax=vmax)
    assert rgb.shape == (4, 4, 3)
    rgb2 = apply_display(np.zeros((0, 0)))
    assert rgb2.size > 0
