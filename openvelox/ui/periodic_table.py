"""Clickable periodic table for EDS element selection."""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QGridLayout, QPushButton, QWidget

from openvelox.processing.xray_lines import GROUPS, PERIODIC_ORDER, element

_COLORS = {
    "alkali": "#F5C6C6",
    "alkaline": "#F8D9B0",
    "transition": "#D6C7F0",
    "lanthanide": "#F3C6E2",
    "actinide": "#E4B8D4",
    "nonmetal": "#C7E6C7",
    "halogen": "#C4E4F2",
    "noble": "#C9D4F5",
    "metalloid": "#D7E8B8",
    "other": "#E4E6EA",
}


def _group_of(symbol: str) -> str:
    for name, members in GROUPS.items():
        if symbol in members:
            return name
    return "other"


class PeriodicTable(QWidget):
    elementToggled = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.selected: set[str] = set()
        self._buttons: dict[str, QPushButton] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setSpacing(1)
        for i, symbol in enumerate(PERIODIC_ORDER):
            row, col = divmod(i, 18)
            if symbol is None:
                continue
            rec = element(symbol)
            btn = QPushButton(symbol)
            btn.setCheckable(True)
            btn.setToolTip(f"{rec['name']}  Z={rec['Z']}")
            btn.setFixedSize(34, 26)
            btn.setStyleSheet(self._style(symbol, False))
            btn.toggled.connect(lambda on, s=symbol: self._toggle(s, on))
            grid.addWidget(btn, row, col)
            self._buttons[symbol] = btn

    def _style(self, symbol: str, on: bool) -> str:
        bg = "#00A3E0" if on else _COLORS[_group_of(symbol)]
        fg = "#FFFFFF" if on else "#1B1F23"
        return (
            f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid #9AA3AB; "
            f"font-size: 11px; font-family: 'DejaVu Sans'; padding: 0; }}"
        )

    def _toggle(self, symbol: str, on: bool) -> None:
        if on:
            self.selected.add(symbol)
        else:
            self.selected.discard(symbol)
        self._buttons[symbol].setStyleSheet(self._style(symbol, on))
        self.elementToggled.emit(symbol, on)

    def set_selected(self, symbols: list[str]) -> None:
        for symbol, btn in self._buttons.items():
            btn.blockSignals(True)
            btn.setChecked(symbol in symbols)
            btn.setStyleSheet(self._style(symbol, symbol in symbols))
            btn.blockSignals(False)
        self.selected = set(symbols)

    def selected_list(self) -> list[str]:
        return sorted(self.selected, key=lambda s: element(s)["Z"])
