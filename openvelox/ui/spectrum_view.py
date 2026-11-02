"""Bottom spectrum / line-profile plot."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget


class SpectrumView(QWidget):
    def __init__(self, translator, parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#101214")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.curve = self.plot.plot(pen=pg.mkPen("#00A3E0", width=1.4))
        self.bg_curve = self.plot.plot(pen=pg.mkPen("#8A93A0", width=1.0, style=pg.QtCore.Qt.PenStyle.DashLine))
        self._markers: list = []
        self._energy = np.array([])
        self._counts = np.array([])
        layout.addWidget(self.plot)
        self.set_empty()

    def set_empty(self) -> None:
        self.plot.setTitle(self.tr_("no_spectrum"), color="#8A93A0")
        self.curve.setData([], [])
        self.bg_curve.setData([], [])
        self.clear_markers()

    def retranslate(self) -> None:
        if self._energy.size == 0:
            self.set_empty()
        else:
            self.plot.setLabel("bottom", self.tr_("energy"))
            self.plot.setLabel("left", self.tr_("counts"))

    def set_spectrum(
        self,
        energy: np.ndarray,
        counts: np.ndarray,
        title: str | None = None,
        xlabel: str | None = None,
        ylabel: str | None = None,
    ) -> None:
        self._energy = np.asarray(energy, dtype=np.float64)
        self._counts = np.asarray(counts, dtype=np.float64)
        self.curve.setData(self._energy, self._counts)
        self.plot.setTitle(title or self.tr_("sum_spectrum"), color="#E8EEF2")
        self.plot.setLabel("bottom", xlabel or self.tr_("energy"))
        self.plot.setLabel("left", ylabel or self.tr_("counts"))

    def set_background(self, energy: np.ndarray, background: np.ndarray) -> None:
        e = np.asarray(energy, dtype=np.float64)
        bg = np.asarray(background, dtype=np.float64)
        if e.size == 0 or bg.size == 0 or e.size != bg.size:
            self.bg_curve.setData([], [])
            return
        self.bg_curve.setData(e, bg)

    def set_line_profile(self, x: np.ndarray, y: np.ndarray, stats: dict | None = None) -> None:
        title = self.tr_("line_profile")
        if stats:
            title = (
                f"{title}  mean={stats.get('mean', 0):.3g}  "
                f"FWHM={stats.get('fwhm', 0):.2f}  L={stats.get('length', 0):.1f}"
            )
        self.set_spectrum(x, y, title=title, xlabel=self.tr_("position"), ylabel=self.tr_("intensity"))

    def clear_markers(self) -> None:
        for item in self._markers:
            self.plot.removeItem(item)
        self._markers.clear()

    def add_peak_markers(self, peaks: list[dict]) -> None:
        self.clear_markers()
        if self._counts.size == 0:
            return
        ymax = float(self._counts.max()) if self._counts.size else 1.0
        used: list[float] = []
        for peak in peaks:
            e = float(peak.get("energy_kev") or peak.get("energy") or 0.0)
            text = str(peak.get("label") or "").strip()
            if not text:
                label = peak.get("symbol") or ""
                line = peak.get("line") or ""
                text = f"{label} {line}".strip()
            family = bool(peak.get("family"))
            color = "#C9A227" if family else "#F4C542"
            inf = pg.InfiniteLine(e, angle=90, pen=pg.mkPen(color, width=1, style=pg.QtCore.Qt.PenStyle.DashLine))
            self.plot.addItem(inf)
            self._markers.append(inf)
            if text:
                lift = 0.92
                for prev in used:
                    if abs(prev - e) < 0.25:
                        lift -= 0.08
                used.append(e)
                ti = pg.TextItem(text, color=color, anchor=(0.5, 1))
                ti.setPos(e, ymax * max(lift, 0.55))
                self.plot.addItem(ti)
                self._markers.append(ti)

    @property
    def energy(self) -> np.ndarray:
        return self._energy

    @property
    def counts(self) -> np.ndarray:
        return self._counts
