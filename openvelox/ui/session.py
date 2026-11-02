"""Persist an OpenVelox workspace (files, k-factors, window chrome)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SESSION_VERSION = 3


def dataset_ref(dataset) -> dict[str, str]:
    return {
        "name": getattr(dataset, "name", ""),
        "source_path": getattr(dataset, "source_path", "") or "",
        "kind": getattr(getattr(dataset, "kind", None), "value", "") or "",
    }


def save_session(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    data = {"version": SESSION_VERSION, **payload}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_session(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid session file")
    return data
