"""Workspace report export: PDF (Pillow), HTML, and a minimal PPTX."""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from openvelox.processing.display import apply_display


def _font(size: int = 12):
    for path in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ):
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default()
    except OSError:
        return None


def _to_rgb(image: np.ndarray) -> Image.Image:
    arr = np.asarray(image)
    if arr.ndim == 3 and arr.shape[-1] in {3, 4}:
        rgb = arr[..., :3]
        if rgb.dtype != np.uint8:
            peak = float(np.nanmax(rgb)) or 1.0
            rgb = np.clip(rgb / peak * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(rgb, mode="RGB")
    if arr.ndim != 2:
        arr = np.reshape(arr, (arr.shape[0], -1)) if arr.size else np.zeros((8, 8))
    painted = apply_display(np.asarray(arr, dtype=np.float64), colormap="gray")
    return Image.fromarray(painted, mode="RGB")


def _blank_page(width: int = 900, height: int = 640) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    page = Image.new("RGB", (width, height), (16, 22, 28))
    return page, ImageDraw.Draw(page)


def render_report_pages(model: dict) -> list[Image.Image]:
    """Turn a report model into RGB pages (title, images, spectrum, table)."""
    pages: list[Image.Image] = []
    title = str(model.get("title") or "OpenVelox report")
    subtitle = str(model.get("subtitle") or "")
    page, draw = _blank_page()
    font_lg = _font(22)
    font = _font(13)
    draw.text((36, 40), title[:80], fill=(0, 163, 224), font=font_lg)
    if subtitle:
        draw.text((36, 80), subtitle[:120], fill=(232, 238, 242), font=font)
    meta = model.get("metadata") or []
    y = 130
    for line in meta[:16]:
        draw.text((36, y), str(line)[:90], fill=(180, 190, 200), font=font)
        y += 22
    pages.append(page)

    for name, image in list(model.get("images") or [])[:8]:
        page, draw = _blank_page()
        draw.text((36, 20), str(name)[:70], fill=(0, 163, 224), font=font)
        thumb = _to_rgb(image)
        thumb.thumbnail((820, 540))
        page.paste(thumb, (40, 56))
        pages.append(page)

    spec = model.get("spectrum")
    if spec is not None:
        x, yv = spec
        x = np.asarray(x, dtype=np.float64).ravel()
        yv = np.asarray(yv, dtype=np.float64).ravel()
        if x.size and yv.size:
            page, draw = _blank_page()
            draw.text((36, 20), "Spectrum", fill=(0, 163, 224), font=font)
            plot = _draw_spectrum(x, yv, 820, 480)
            page.paste(plot, (40, 70))
            pages.append(page)

    rows = list(model.get("quant") or [])
    if rows:
        page, draw = _blank_page()
        draw.text((36, 20), "Quantification", fill=(0, 163, 224), font=font)
        headers = ["element", "atomic_percent", "weight_percent", "intensity", "k_factor"]
        draw.text((36, 70), "  ".join(headers), fill=(244, 197, 66), font=font)
        y = 100
        for row in rows[:18]:
            line = "  ".join(f"{row.get(k, '—')}" if not isinstance(row.get(k), float) else f"{row.get(k):.3g}" for k in headers)
            draw.text((36, y), line[:100], fill=(232, 238, 242), font=font)
            y += 22
        pages.append(page)
    return pages or [_blank_page()[0]]


def _draw_spectrum(x: np.ndarray, y: np.ndarray, w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), (10, 14, 18))
    draw = ImageDraw.Draw(img)
    n = min(int(x.size), int(y.size), w)
    if n < 2:
        return img
    xs = np.linspace(0, n - 1, n)
    yy = y[:n]
    ymin, ymax = float(yy.min()), float(yy.max())
    if ymax <= ymin:
        ymax = ymin + 1.0
    pts = []
    for i in range(n):
        px = int(i * (w - 1) / (n - 1))
        py = int((h - 8) - (yy[int(xs[i])] - ymin) / (ymax - ymin) * (h - 16))
        pts.append((px, py))
    draw.line(pts, fill=(0, 163, 224), width=2)
    return img


def export_report_pdf(path: str | Path, model: dict) -> Path:
    path = Path(path)
    pages = render_report_pages(model)
    first, rest = pages[0], pages[1:]
    first.save(path, format="PDF", save_all=bool(rest), append_images=rest)
    return path


def export_report_html(path: str | Path, model: dict) -> Path:
    path = Path(path)
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>",
        escape(str(model.get("title") or "OpenVelox report")),
        "</title><style>body{font-family:DejaVu Sans,sans-serif;background:#101214;color:#E8EEF2}"
        "img{max-width:100%;background:#000} table{border-collapse:collapse} td,th{padding:4px 8px;border:1px solid #2C3944}</style></head><body>",
        f"<h1>{escape(str(model.get('title') or 'OpenVelox report'))}</h1>",
    ]
    for line in model.get("metadata") or []:
        parts.append(f"<p>{escape(str(line))}</p>")
    for name, image in list(model.get("images") or [])[:8]:
        buf = io.BytesIO()
        _to_rgb(image).save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        parts.append(f"<h2>{escape(str(name))}</h2><img src='data:image/png;base64,{b64}'/>")
    rows = list(model.get("quant") or [])
    if rows:
        parts.append("<h2>Quantification</h2><table><tr><th>El</th><th>at.%</th><th>wt.%</th></tr>")
        for row in rows:
            parts.append(
                f"<tr><td>{escape(str(row.get('element','')))}</td>"
                f"<td>{float(row.get('atomic_percent') or 0):.2f}</td>"
                f"<td>{float(row.get('weight_percent') or 0):.2f}</td></tr>"
            )
        parts.append("</table>")
    parts.append("</body></html>")
    path.write_text("".join(parts), encoding="utf-8")
    return path


def export_report_pptx(path: str | Path, model: dict) -> Path:
    """Minimal PPTX: one slide per rendered page (no python-pptx dependency)."""
    path = Path(path)
    pages = render_report_pages(model)
    images: list[bytes] = []
    for page in pages:
        buf = io.BytesIO()
        page.save(buf, format="PNG")
        images.append(buf.getvalue())
    _write_minimal_pptx(path, images)
    return path


def export_report(path: str | Path, model: dict) -> Path:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".html":
        return export_report_html(path, model)
    if suffix == ".pptx":
        return export_report_pptx(path, model)
    if suffix != ".pdf":
        path = path.with_suffix(".pdf")
    return export_report_pdf(path, model)


def _write_minimal_pptx(path: Path, images: list[bytes]) -> None:
    if not images:
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (16, 22, 28)).save(buf, format="PNG")
        images = [buf.getvalue()]
    slides_override = []
    rels = []
    sld_ids = []
    for i in range(len(images)):
        n = i + 1
        slides_override.append(
            f'<Override PartName="/ppt/slides/slide{n}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        )
        rels.append(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{n}.xml"/>')
        sld_ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>')
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        + "".join(slides_override)
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        "</Relationships>"
    )
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f"<p:sldIdLst>{''.join(sld_ids)}</p:sldIdLst>"
        '<p:sldSz cx="9144000" cy="6858000"/>'
        "</p:presentation>"
    )
    pres_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("ppt/presentation.xml", presentation)
        zf.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        for i, png in enumerate(images, start=1):
            zf.writestr(f"ppt/media/image{i}.png", png)
            zf.writestr(f"ppt/slides/slide{i}.xml", _slide_xml(i))
            zf.writestr(
                f"ppt/slides/_rels/slide{i}.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image{i}.png"/>'
                "</Relationships>",
            )


def _slide_xml(index: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
        "<p:grpSpPr/>"
        "<p:pic><p:nvPicPr><p:cNvPr id=\"2\" name=\"image\"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>"
        "<p:blipFill><a:blip r:embed=\"rId1\"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>"
        "<p:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"9144000\" cy=\"6858000\"/></a:xfrm>"
        "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom></p:spPr></p:pic>"
        "</p:spTree></p:cSld></p:sld>"
    )
