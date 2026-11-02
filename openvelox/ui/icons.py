"""Lightweight toolbar icons — no extra asset files (PyInstaller-safe)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygon

CYAN = QColor("#00A3E0")
TEXT = QColor("#E8EEF2")


def _canvas(size: int = 20) -> tuple[QPixmap, QPainter]:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pix, painter


def _stroke_icon(draw, size: int = 20) -> QIcon:
    pix, painter = _canvas(size)
    painter.setPen(QPen(CYAN, 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter, size)
    painter.end()
    return QIcon(pix)


def icon_open() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        p.drawRoundedRect(3, 6, s - 7, s - 10, 2, 2)
        p.drawLine(3, 9, s - 4, 9)

    return _stroke_icon(draw)


def icon_fit() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        p.drawRect(4, 4, s - 8, s - 8)
        p.drawLine(4, 4, 8, 8)
        p.drawLine(s - 4, s - 4, s - 8, s - 8)

    return _stroke_icon(draw)


def icon_fft() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        p.drawLine(3, s - 4, s - 3, s - 4)
        p.drawLine(4, s - 4, 7, 5)
        p.drawLine(7, 5, 10, s - 6)
        p.drawLine(10, s - 6, 14, 7)
        p.drawLine(14, 7, 17, s - 4)

    return _stroke_icon(draw)


def icon_pointer() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        poly = QPolygon([QPoint(5, 3), QPoint(5, s - 4), QPoint(9, s - 8), QPoint(s - 4, s - 4)])
        p.setBrush(CYAN)
        p.drawPolygon(poly)

    return _stroke_icon(draw)


def icon_line() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        p.drawLine(4, s - 5, s - 4, 5)
        p.drawEllipse(3, s - 7, 3, 3)
        p.drawEllipse(s - 7, 3, 3, 3)

    return _stroke_icon(draw)


def icon_roi() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        p.drawRect(4, 5, s - 8, s - 10)

    return _stroke_icon(draw)


def icon_polygon() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        poly = QPolygon([QPoint(4, s - 5), QPoint(6, 5), QPoint(s - 4, 6), QPoint(s - 6, s - 4)])
        p.drawPolygon(poly)

    return _stroke_icon(draw)


def icon_dspacing() -> QIcon:
    def draw(p: QPainter, s: int) -> None:
        p.drawEllipse(3, 3, 5, 5)
        p.drawEllipse(s - 8, s - 8, 5, 5)
        p.drawLine(7, 7, s - 7, s - 7)

    return _stroke_icon(draw)


def icon_for(key: str) -> QIcon:
    table = {
        "open": icon_open,
        "open_sample": icon_open,
        "fit": icon_fit,
        "fft": icon_fft,
        "pointer": icon_pointer,
        "line_profile": icon_line,
        "distance": icon_line,
        "angle": icon_line,
        "d_spacing": icon_dspacing,
        "roi_rect": icon_roi,
        "roi_ellipse": icon_roi,
        "roi_polygon": icon_polygon,
    }
    factory = table.get(key)
    return factory() if factory else QIcon()
