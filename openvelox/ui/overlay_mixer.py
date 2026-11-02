"""Live EDS map layer mixer (Velox-style colour overlay)."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from openvelox.processing.eds import color_overlay

DEFAULT_COLORS = {
    "C": (180, 180, 180),
    "N": (80, 120, 220),
    "O": (220, 40, 40),
    "Si": (80, 200, 80),
    "Cu": (220, 140, 40),
    "Au": (240, 210, 50),
    "Ca": (90, 200, 220),
    "Fe": (90, 200, 220),
}


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            _clear_layout(child)


class OverlayMixer(QWidget):
    mixChanged = Signal(object)

    def __init__(self, translator, parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self.maps: dict[str, np.ndarray] = {}
        self._sliders: dict[str, QSlider] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._hint = QLabel(translator("overlay"))
        self._layout.addWidget(self._hint)

    def set_maps(self, maps: dict[str, np.ndarray]) -> None:
        self.maps = dict(maps)
        # Drop every row except the hint label (index 0).
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif child is not None:
                _clear_layout(child)
        self._sliders.clear()
        for symbol in self.maps:
            row = QHBoxLayout()
            lab = QLabel(symbol)
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 200)
            sl.setValue(100)
            sl.valueChanged.connect(self._emit)
            row.addWidget(lab)
            row.addWidget(sl)
            self._layout.addLayout(row)
            self._sliders[symbol] = sl
        self._emit()

    def mix(self) -> np.ndarray | None:
        if not self.maps:
            return None
        scaled = {}
        for symbol, mmap in self.maps.items():
            gain = (self._sliders[symbol].value() / 100.0) if symbol in self._sliders else 1.0
            scaled[symbol] = np.asarray(mmap, dtype=np.float64) * gain
        return color_overlay(scaled, colors=DEFAULT_COLORS)

    def _emit(self) -> None:
        rgb = self.mix()
        if rgb is not None:
            self.mixChanged.emit(rgb)
