"""Velox-style scale bar length, color, position and drawing helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from openvelox.io.metadata import format_pixel_size


@dataclass
class ScaleBarStyle:
    color: str = "#FFFFFF"
    length_m: float | None = None
    font_size: int = 9
    position: str = "bottom_left"
    thickness: int = 4
    visible: bool = True

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: dict | None) -> "ScaleBarStyle":
        if not data:
            return cls()
        length = data.get("length_m")
        try:
            length_m = float(length) if length not in (None, "", 0, 0.0) else None
        except (TypeError, ValueError):
            length_m = None
        if length_m is not None and length_m <= 0:
            length_m = None
        return cls(
            color=str(data.get("color") or "#FFFFFF"),
            length_m=length_m,
            font_size=int(data.get("font_size") or 9),
            position=str(data.get("position") or "bottom_left"),
            thickness=int(data.get("thickness") or 4),
            visible=bool(data.get("visible", True)),
        )


def parse_color(color: object, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    if isinstance(color, str) and color.startswith("#") and len(color) >= 7:
        raw = color.lstrip("#")
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        return int(color[0]), int(color[1]), int(color[2])
    return default


def nice_length_m(pixel_m: float, target_m: float) -> float:
    if target_m <= 0:
        target_m = float(pixel_m) * 80.0
    exp = int(np.floor(np.log10(target_m))) if target_m > 0 else -9
    best = 10.0**exp
    for step in (1.0, 2.0, 5.0):
        cand = step * 10.0**exp
        if cand <= target_m * 1.35:
            best = cand
    return float(best)


def bar_pixels(pixel_m: float, length_m: float) -> int:
    if pixel_m <= 0 or length_m <= 0:
        return 0
    return max(8, int(round(length_m / pixel_m)))


def choose_bar(pixel_m: float, view_width_data: float, style: ScaleBarStyle | None = None) -> tuple[float, str, int]:
    """Return (length_m, label, length_in_data_pixels)."""
    style = style or ScaleBarStyle()
    if style.length_m and style.length_m > 0:
        length = float(style.length_m)
    else:
        target = float(pixel_m) * max(view_width_data * 0.18, 40.0)
        length = nice_length_m(pixel_m, target)
    return length, format_pixel_size(length), bar_pixels(pixel_m, length)
