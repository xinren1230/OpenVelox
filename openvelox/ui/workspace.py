"""Velox-style multi-panel workspace with linked zoom / pan."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

LAYOUTS: dict[str, tuple[int, int]] = {
    "1x1": (1, 1),
    "1x2": (1, 2),
    "2x1": (2, 1),
    "2x2": (2, 2),
    "1x3": (1, 3),
    "2x3": (2, 3),
}


def layout_shape(key: str) -> tuple[int, int]:
    return LAYOUTS.get(key, (1, 1))


def layout_keys() -> tuple[str, ...]:
    return tuple(LAYOUTS)


def mirror_view(src_canvas, dst_canvas) -> None:
    """Copy zoom/pan, scaling by pixel size so mixed-FOV tiles stay registered."""
    if src_canvas is dst_canvas:
        return
    try:
        xr, yr = src_canvas.vb.viewRange()
    except Exception:
        return
    src_px = float(src_canvas.pixel_m or 0.0) or 1.0
    dst_px = float(dst_canvas.pixel_m or 0.0) or 1.0
    scale = src_px / dst_px
    dst_canvas.vb.blockSignals(True)
    try:
        dst_canvas.vb.setRange(
            xRange=(float(xr[0]) * scale, float(xr[1]) * scale),
            yRange=(float(yr[0]) * scale, float(yr[1]) * scale),
            padding=0,
        )
    except Exception:
        pass
    dst_canvas.vb.blockSignals(False)


class _Cell(QFrame):
    focused = Signal(int)

    def __init__(self, index: int, parent=None) -> None:
        super().__init__(parent)
        self.index = index
        self.setObjectName("workspaceCell")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(1, 1, 1, 1)
        self._body.setSpacing(0)
        self.set_active(False)

    def set_active(self, on: bool) -> None:
        color = "#00A3E0" if on else "#2C3944"
        self.setStyleSheet(f"QFrame#workspaceCell {{ border: 2px solid {color}; background: #101214; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.focused.emit(self.index)
        super().mousePressEvent(event)

    def set_content(self, widget: QWidget) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            child = item.widget()
            if child is not None:
                child.setParent(None)
        if widget is not None:
            self._body.addWidget(widget, 1)


class MultiPanelView(QWidget):
    panelActivated = Signal(object)

    def __init__(self, translator=None, layout: str = "2x2", parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self.layout_key = layout if layout in LAYOUTS else "2x2"
        self._linked = False
        self._syncing = False
        self._focused = 0
        self._tabs: list = []
        self._cells: list[_Cell] = []
        self._wired: set[int] = set()
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(2)
        self.rebuild(self.layout_key)

    def panel_count(self) -> int:
        rows, cols = layout_shape(self.layout_key)
        return rows * cols

    def panels(self) -> list:
        return [tab for tab in self._tabs if tab is not None]

    def focused_index(self) -> int:
        return int(self._focused)

    def focused_panel(self):
        if 0 <= self._focused < len(self._tabs) and self._tabs[self._focused] is not None:
            return self._tabs[self._focused]
        found = self.panels()
        return found[0] if found else None

    def rebuild(self, layout: str) -> None:
        self.layout_key = layout if layout in LAYOUTS else "2x2"
        for tab in self._tabs:
            if tab is not None:
                try:
                    tab.setParent(None)
                except RuntimeError:
                    pass
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cells = []
        rows, cols = layout_shape(self.layout_key)
        n = rows * cols
        alive = []
        for tab in self._tabs:
            try:
                if tab is None:
                    continue
                tab.objectName()
                alive.append(tab)
            except RuntimeError:
                continue
        self._tabs = (alive + [None] * n)[:n]
        for i in range(n):
            cell = _Cell(i)
            cell.focused.connect(self._on_cell)
            self._cells.append(cell)
            self._grid.addWidget(cell, i // cols, i % cols)
        self._paint_cells()
        self._focus(min(self._focused, max(n - 1, 0)), emit=False)

    def set_tabs(self, tabs: list) -> None:
        for old in self._tabs:
            if old is not None and old not in tabs:
                try:
                    old.setParent(None)
                    old.canvas.teardown()
                    old.deleteLater()
                except RuntimeError:
                    pass
        n = self.panel_count()
        self._tabs = list(tabs)[:n] + [None] * max(0, n - len(tabs))
        self._paint_cells()
        self._wire()
        if self.panels():
            self._focus(0, emit=True)

    def replace_focused(self, tab) -> None:
        idx = self._focused if 0 <= self._focused < self.panel_count() else 0
        old = self._tabs[idx] if idx < len(self._tabs) else None
        if old is not None and old is not tab:
            try:
                old.setParent(None)
                old.canvas.teardown()
                old.deleteLater()
            except RuntimeError:
                pass
        if idx >= len(self._tabs):
            self._tabs.extend([None] * (idx + 1 - len(self._tabs)))
        self._tabs[idx] = tab
        self._paint_cells()
        self._wire()
        self._focus(idx, emit=True)

    def set_linked(self, linked: bool) -> None:
        self._linked = bool(linked)
        if self._linked:
            src = self.focused_panel() or (self.panels()[0] if self.panels() else None)
            if src is not None:
                self._sync_from(src)

    def is_linked(self) -> bool:
        return bool(self._linked)

    def _placeholder(self) -> QWidget:
        label = QLabel(self.tr_("empty_panel") if self.tr_ else "Double-click a dataset to show it here")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setObjectName("hint")
        return label

    def _paint_cells(self) -> None:
        for i, cell in enumerate(self._cells):
            tab = self._tabs[i] if i < len(self._tabs) else None
            cell.set_content(tab if tab is not None else self._placeholder())
            cell.set_active(i == self._focused)

    def _wire(self) -> None:
        live = set()
        for tab in self.panels():
            key = id(tab.canvas)
            live.add(key)
            if key in self._wired:
                try:
                    tab.canvas.viewChanged.disconnect(self._on_canvas_view)
                except (RuntimeError, TypeError):
                    pass
            tab.canvas.viewChanged.connect(self._on_canvas_view)
            self._wired.add(key)
        self._wired = live

    def _on_canvas_view(self) -> None:
        if not self._linked or self._syncing:
            return
        sender = self.sender()
        for tab in self.panels():
            try:
                if tab.canvas is sender:
                    self._sync_from(tab)
                    return
            except RuntimeError:
                continue

    def _on_cell(self, index: int) -> None:
        self._focus(index, emit=True)

    def _focus(self, index: int, emit: bool = True) -> None:
        self._focused = int(index)
        for i, cell in enumerate(self._cells):
            cell.set_active(i == self._focused)
        if emit:
            tab = self.focused_panel()
            if tab is not None:
                self.panelActivated.emit(tab)

    def _on_view(self, src) -> None:
        if not self._linked or self._syncing or src is None:
            return
        self._sync_from(src)

    def _sync_from(self, src) -> None:
        self._syncing = True
        try:
            for dst in self.panels():
                if dst is src:
                    continue
                mirror_view(src.canvas, dst.canvas)
        finally:
            self._syncing = False
