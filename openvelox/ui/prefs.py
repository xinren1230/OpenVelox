"""JSON preferences: recent files and persisted dock / window chrome."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openvelox.paths import user_data_dir

RECENT_LIMIT = 12


def prefs_path() -> Path:
    return user_data_dir() / "prefs.json"


def load_prefs() -> dict[str, Any]:
    path = prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(data: dict[str, Any]) -> None:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = load_prefs()
    merged.update(data)
    path.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def recent_files() -> list[str]:
    raw = load_prefs().get("recent_files") or []
    out: list[str] = []
    for item in raw:
        p = Path(str(item))
        if p.is_file() and str(p) not in out:
            out.append(str(p))
    return out


def add_recent(path: str | Path, limit: int = RECENT_LIMIT) -> list[str]:
    path = str(Path(path))
    items = [path] + [p for p in recent_files() if p != path]
    items = items[: max(1, int(limit))]
    save_prefs({"recent_files": items})
    return items


def clear_recent() -> None:
    save_prefs({"recent_files": []})
