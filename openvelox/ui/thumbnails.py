"""Dataset thumbnails for the experiment browser (Qt icons only)."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap

from openvelox.models import Dataset, DatasetKind
from openvelox.processing.preview import thumbnail_array

KIND_COLOR = {
    DatasetKind.IMAGE: "#00A3E0",
    DatasetKind.STACK: "#7CDB6A",
    DatasetKind.SPECTRUM: "#F4C542",
    DatasetKind.SPECTRUM_IMAGE: "#E07A5F",
    DatasetKind.FOUR_D: "#C084FC",
}


def pixmap_from_array(image: np.ndarray, size: int = 48) -> QPixmap:
    thumb = thumbnail_array(image, size=size)
    if thumb.ndim != 2 or thumb.size == 0:
        pix = QPixmap(size, size)
        pix.fill(QColor("#101214"))
        return pix
    h, w = int(thumb.shape[0]), int(thumb.shape[1])
    src = np.ascontiguousarray(thumb)
    qimg = QImage(src.data, w, h, w, QImage.Format.Format_Grayscale8)
    qimg = qimg.copy()
    pix = QPixmap.fromImage(qimg)
    if pix.width() != size or pix.height() != size:
        pix = pix.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    canvas = QPixmap(size, size)
    canvas.fill(QColor("#101214"))
    painter = QPainter(canvas)
    x = max(0, (size - pix.width()) // 2)
    y = max(0, (size - pix.height()) // 2)
    painter.drawPixmap(x, y, pix)
    painter.end()
    return canvas


def kind_icon(kind: DatasetKind, size: int = 48) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(QColor("#101214"))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(KIND_COLOR.get(kind, "#8A96A0")))
    painter.setBrush(QColor(KIND_COLOR.get(kind, "#8A96A0")))
    margin = max(4, size // 6)
    painter.drawRoundedRect(margin, margin, size - 2 * margin, size - 2 * margin, 4, 4)
    painter.end()
    return QIcon(pix)


def icon_from_array(image: np.ndarray, size: int = 48) -> QIcon:
    return QIcon(pixmap_from_array(image, size=size))


def dataset_thumbnail(dataset: Dataset, size: int = 48) -> QIcon:
    try:
        if dataset.kind is DatasetKind.SPECTRUM:
            arr = np.asarray(dataset.data)
            if hasattr(arr, "shape") and arr.ndim == 1:
                return icon_from_array(arr, size=size)
        preview = dataset.image2d(preview=True, max_side=max(size, 64))
        return icon_from_array(preview, size=size)
    except Exception:
        return kind_icon(dataset.kind, size=size)
