"""Live Super-X / DF4 segment weight sliders (Layers dock)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from openvelox.models import Dataset


class DetectorMixer(QWidget):
    mixChanged = Signal(object)

    def __init__(self, translator, parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self._groups: dict[str, list[Dataset]] = {"superx": [], "df4": []}
        self._sliders: dict[tuple[str, str], QSlider] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._hint = QLabel(translator("mix_detectors"))
        self._layout.addWidget(self._hint)

    def set_groups(self, groups: dict[str, list[Dataset]]) -> None:
        self._groups = {
            "superx": list(groups.get("superx") or []),
            "df4": list(groups.get("df4") or []),
        }
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif child is not None:
                while child.count():
                    inner = child.takeAt(0)
                    w = inner.widget()
                    if w is not None:
                        w.setParent(None)
                        w.deleteLater()
        self._sliders.clear()
        titles = {"superx": self.tr_("mix_superx"), "df4": self.tr_("mix_df")}
        for family in ("superx", "df4"):
            members = self._groups[family]
            if len(members) < 2:
                continue
            self._layout.addWidget(QLabel(titles[family]))
            for ds in members:
                row = QHBoxLayout()
                lab = QLabel(ds.display_name())
                sl = QSlider(Qt.Orientation.Horizontal)
                sl.setRange(0, 200)
                sl.setValue(100)
                sl.valueChanged.connect(self._emit)
                row.addWidget(lab)
                row.addWidget(sl)
                self._layout.addLayout(row)
                self._sliders[(family, ds.name)] = sl
        self._emit()

    def weights(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {"superx": {}, "df4": {}}
        for (family, name), sl in self._sliders.items():
            out[family][name] = sl.value() / 100.0
        return out

    def datasets(self, family: str) -> list[Dataset]:
        return list(self._groups.get(family) or [])

    def _emit(self) -> None:
        self.mixChanged.emit(self.weights())
