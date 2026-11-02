"""Frozen-exe and user-data path helpers (PyInstaller onefile / onedir)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def meipass() -> Path | None:
    raw = getattr(sys, "_MEIPASS", None)
    return Path(raw) if raw else None


def resource_root() -> Path:
    """Directory that contains bundled `samples/` and package data."""
    frozen = meipass()
    if frozen is not None:
        return frozen
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)


def window_icon_path() -> Path:
    """``openvelox/resources/openvelox.ico`` from ``sys._MEIPASS`` or the package dir."""
    rel = Path("openvelox") / "resources" / "openvelox.ico"
    frozen = meipass()
    if frozen is not None:
        preferred = frozen / rel
        if preferred.is_file():
            return preferred
        alt = frozen / "resources" / "openvelox.ico"
        if alt.is_file():
            return alt
        return preferred
    return Path(__file__).resolve().parent / "resources" / "openvelox.ico"


def write_placeholder_ico(path: str | Path) -> Path:
    """Write a simple Thermo-cyan plate icon. Caller must ensure the path is free."""
    from PIL import Image, ImageDraw

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 256
    image = Image.new("RGBA", (size, size), (14, 28, 38, 255))
    draw = ImageDraw.Draw(image)
    margin = 16
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=36,
        fill=(8, 17, 24, 255),
        outline=(0, 163, 224, 255),
        width=10,
    )
    cx = cy = size // 2
    radius = 84
    draw.ellipse(
        [cx - radius, cy - radius + 6, cx + radius, cy + radius + 6],
        outline=(0, 163, 224, 255),
        width=12,
    )
    draw.line([(72, 88), (128, 188), (184, 88)], fill=(232, 238, 242, 255), width=16)
    image.save(dest, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    return dest


def ensure_window_icon(path: str | Path | None = None) -> Path | None:
    """Return the window icon, generating a placeholder ICO only when missing."""
    dest = Path(path) if path is not None else window_icon_path()
    if dest.is_file():
        return dest
    try:
        return write_placeholder_ico(dest)
    except OSError:
        return None


def user_data_dir() -> Path:
    override = os.environ.get("OPENVELOX_DATA_DIR")
    if override:
        folder = Path(override)
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "OpenVelox"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "OpenVelox"
    return Path.home() / ".local" / "share" / "OpenVelox"


def log_dir() -> Path:
    override = os.environ.get("OPENVELOX_LOG_DIR")
    folder = Path(override) if override else user_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def bundled_sample_emd() -> Path | None:
    cand = resource_path("samples", "synthetic_velox.emd")
    return cand if cand.is_file() else None


def writable_dir(preferred: Path) -> Path:
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return preferred
    except OSError:
        fallback = user_data_dir() / preferred.name
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
