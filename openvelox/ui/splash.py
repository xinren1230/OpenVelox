"""Lightweight splash shown before the heavy MainWindow import."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen


def make_splash(message: str = "OpenVelox") -> QSplashScreen:
    pix = QPixmap(420, 200)
    pix.fill(QColor("#0E1C26"))
    painter = QPainter(pix)
    painter.setPen(QColor("#00A3E0"))
    painter.setFont(QFont("DejaVu Sans", 22))
    painter.drawText(pix.rect().adjusted(0, -16, 0, -16), Qt.AlignmentFlag.AlignCenter, "OpenVelox")
    painter.setPen(QColor("#E8EEF2"))
    painter.setFont(QFont("DejaVu Sans", 10))
    painter.drawText(pix.rect().adjusted(0, 36, 0, 36), Qt.AlignmentFlag.AlignCenter, message)
    painter.end()
    splash = QSplashScreen(pix)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return splash
