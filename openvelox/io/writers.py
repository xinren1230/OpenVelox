"""Export images, spectra and quantification tables."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from openvelox.processing.display import apply_display
from openvelox.processing.scalebar import ScaleBarStyle, choose_bar, parse_color


def export_spectrum_csv(path: str | Path, energy_kev: np.ndarray, counts: np.ndarray) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["energy_keV", "counts"])
        for e, c in zip(np.asarray(energy_kev).ravel(), np.asarray(counts).ravel()):
            writer.writerow([f"{float(e):.6f}", f"{float(c):.6f}"])


def export_map_csv(path: str | Path, array: np.ndarray, name: str = "intensity") -> None:
    path = Path(path)
    arr = np.asarray(array)
    if arr.ndim != 2:
        raise ValueError("Map export expects a 2-D array")
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([name])
        for row in arr:
            writer.writerow([f"{float(v):.6g}" for v in row])


def export_quant_table(path: str | Path, rows: list[dict[str, object]]) -> None:
    path = Path(path)
    if not rows:
        path.write_text("element,atomic_percent,intensity,k_factor\n", encoding="utf-8")
        return
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def export_image(
    path: str | Path,
    image: np.ndarray,
    *,
    pixel_m: float | None = None,
    colormap: str = "gray",
    vmin: float | None = None,
    vmax: float | None = None,
    gamma: float = 1.0,
    brightness: float = 1.0,
    invert: bool = False,
    scale_bar: bool = True,
    scale_bar_style: ScaleBarStyle | dict | None = None,
    annotations: list[dict] | None = None,
    title: str | None = None,
) -> None:
    path = Path(path)
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("export_image expects a 2-D image")
    rgb = apply_display(
        arr,
        colormap=colormap,
        vmin=vmin,
        vmax=vmax,
        gamma=gamma,
        brightness=brightness,
        invert=invert,
    )
    pil = Image.fromarray(rgb, mode="RGB")
    if annotations:
        _draw_annotations(pil, annotations)
    if title:
        _draw_title(pil, title)
    style = scale_bar_style if isinstance(scale_bar_style, ScaleBarStyle) else ScaleBarStyle.from_mapping(scale_bar_style)
    if scale_bar and style.visible and pixel_m and pixel_m > 0:
        _draw_scale_bar(pil, float(pixel_m), style, titled=bool(title))
    suffix = path.suffix.lower()
    if suffix in {".tif", ".tiff"}:
        pil.save(path, format="TIFF")
    else:
        pil.save(path, format="PNG")


def export_overlay(
    path: str | Path,
    image: np.ndarray,
    *,
    pixel_m: float | None = None,
    colormap: str = "gray",
    vmin: float | None = None,
    vmax: float | None = None,
    gamma: float = 1.0,
    brightness: float = 1.0,
    invert: bool = False,
    scale_bar_style: ScaleBarStyle | dict | None = None,
    annotations: list[dict] | None = None,
    title: str | None = None,
) -> None:
    """Burn measurements, annotations and the styled scale bar into a PNG/TIFF."""
    export_image(
        path,
        image,
        pixel_m=pixel_m,
        colormap=colormap,
        vmin=vmin,
        vmax=vmax,
        gamma=gamma,
        brightness=brightness,
        invert=invert,
        scale_bar=True,
        scale_bar_style=scale_bar_style,
        annotations=annotations,
        title=title,
    )


def batch_export_images(
    directory: str | Path,
    items: list[tuple[str, np.ndarray, dict]],
) -> list[Path]:
    """Write each ``(stem, image, export_image kwargs)`` into ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, image, kwargs in items:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem) or "image"
        dest = directory / f"{safe}.png"
        export_image(dest, image, **kwargs)
        written.append(dest)
    return written


def _load_font(size: int):
    size = max(8, int(size))
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    )
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default()
    except OSError:
        return None


def _annot_color(item: dict, default: tuple[int, int, int] = (255, 224, 80)) -> tuple[int, int, int]:
    return parse_color(item.get("color"), default)


def _xy(point) -> tuple[float, float]:
    """Accept (row, col) or (x, y) pairs stored as two numbers."""
    return float(point[1]), float(point[0])


def _draw_title(pil: Image.Image, title: str) -> None:
    draw = ImageDraw.Draw(pil)
    font = _load_font(10)
    draw.rectangle([0, 0, pil.size[0], 16], fill=(8, 12, 16))
    draw.text((6, 2), title[:80], fill=(0, 163, 224), font=font)


def _draw_annotations(pil: Image.Image, annotations: list[dict]) -> None:
    draw = ImageDraw.Draw(pil)
    font = _load_font(10)
    for item in annotations:
        kind = str(item.get("kind") or "text")
        color = _annot_color(item)
        width = max(1, int(item.get("width") or 2))
        if kind == "line":
            p0 = item.get("p0") or (0, 0)
            p1 = item.get("p1") or (0, 0)
            x0, y0 = _xy(p0)
            x1, y1 = _xy(p1)
            draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
        elif kind == "rect":
            box = item.get("box") or (0, 0, 4, 4)
            draw.rectangle(box, outline=color, width=1)
        elif kind == "ellipse":
            box = item.get("box") or (0, 0, 4, 4)
            draw.ellipse(box, outline=color, width=1)
        elif kind == "polygon":
            pts = item.get("points") or []
            if len(pts) >= 3:
                draw.polygon([(float(p[0]), float(p[1])) for p in pts], outline=color)
        elif kind == "angle":
            p0 = item.get("p0") or (0, 0)
            vertex = item.get("vertex") or (0, 0)
            p1 = item.get("p1") or (0, 0)
            pts = [_xy(p0), _xy(vertex), _xy(p1)]
            draw.line(pts, fill=color, width=width)
        else:
            x = float(item.get("x") or 0)
            y = float(item.get("y") or 0)
            draw.text((x, y), str(item.get("text") or ""), fill=color, font=font)


def _draw_scale_bar(
    pil: Image.Image,
    pixel_m: float,
    style: ScaleBarStyle | None = None,
    titled: bool = False,
) -> None:
    style = style or ScaleBarStyle()
    if not style.visible:
        return
    w, h = pil.size
    _length, label, bar_px = choose_bar(pixel_m, float(w), style)
    color = parse_color(style.color)
    thickness = max(1, int(style.thickness))
    margin = max(8, w // 40)
    pos = style.position
    top = pos.startswith("top")
    right = pos.endswith("right")
    if right:
        x1 = w - margin
        x0 = x1 - bar_px
    else:
        x0 = margin
        x1 = x0 + bar_px
    if top:
        y0 = (22 if titled else margin) + 2
    else:
        y0 = h - margin - thickness
    draw = ImageDraw.Draw(pil)
    draw.rectangle([x0, y0, x1, y0 + thickness], fill=color)
    font = _load_font(style.font_size)
    text_y = y0 + thickness + 1 if top else y0 - max(12, int(style.font_size) + 2)
    draw.text((x0, text_y), label, fill=color, font=font)
