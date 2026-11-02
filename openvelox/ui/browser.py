"""Left-hand experiment / dataset browser with Velox-style thumbnails."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from openvelox.models import Dataset, DatasetKind, ExperimentFile
from openvelox.ui.thumbnails import dataset_thumbnail, kind_icon

_KIND_ICON = {
    DatasetKind.IMAGE: "▣",
    DatasetKind.STACK: "▦",
    DatasetKind.SPECTRUM: "∿",
    DatasetKind.SPECTRUM_IMAGE: "▣∿",
    DatasetKind.FOUR_D: "▣⁴",
}

_KIND_GROUP = {
    DatasetKind.IMAGE: "images",
    DatasetKind.STACK: "series",
    DatasetKind.SPECTRUM: "spectra",
    DatasetKind.SPECTRUM_IMAGE: "spectrum_images",
    DatasetKind.FOUR_D: "stem4d",
}

THUMB_SIZE = 40


class BrowserPanel(QWidget):
    datasetActivated = Signal(object)
    datasetSelected = Signal(object)

    def __init__(self, translator, parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.tr_("search_datasets"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setExpandsOnDoubleClick(False)
        from PySide6.QtCore import QSize

        self.tree.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(False)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.currentItemChanged.connect(self._on_current)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.filter)
        lay.addWidget(self.tree, 1)
        self._placeholder()

    def _placeholder(self) -> None:
        self.tree.clear()
        item = QTreeWidgetItem([self.tr_("empty_browser")])
        item.setDisabled(True)
        self.tree.addTopLevelItem(item)

    def retranslate(self) -> None:
        self.filter.setPlaceholderText(self.tr_("search_datasets"))
        if self.tree.topLevelItemCount() == 1 and self.tree.topLevelItem(0).isDisabled():
            self.tree.topLevelItem(0).setText(0, self.tr_("empty_browser"))
            return
        for i in range(self.tree.topLevelItemCount()):
            self._retranslate_item(self.tree.topLevelItem(i))

    def _retranslate_item(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if isinstance(key, str):
            item.setText(0, self.tr_(key))
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Dataset):
            item.setText(0, self._label(data))
        for i in range(item.childCount()):
            self._retranslate_item(item.child(i))

    def add_experiment(self, experiment: ExperimentFile) -> None:
        if self.tree.topLevelItemCount() == 1 and self.tree.topLevelItem(0).isDisabled():
            self.tree.clear()
        top = QTreeWidgetItem([experiment.name])
        top.setData(0, Qt.ItemDataRole.UserRole, experiment)
        top.setForeground(0, QBrush(QColor("#7FDBFF")))
        font = top.font(0)
        font.setBold(True)
        top.setFont(0, font)
        top.setToolTip(0, experiment.path or experiment.name)
        groups: dict[str, QTreeWidgetItem] = {}
        for ds in experiment.datasets:
            gkey = _KIND_GROUP.get(ds.kind, "images")
            if gkey not in groups:
                group = QTreeWidgetItem([self.tr_(gkey)])
                group.setData(0, Qt.ItemDataRole.UserRole + 1, gkey)
                font = QFont(group.font(0))
                font.setItalic(True)
                group.setFont(0, font)
                group.setForeground(0, QBrush(QColor("#8A96A0")))
                group.setIcon(0, kind_icon(ds.kind, size=THUMB_SIZE))
                top.addChild(group)
                groups[gkey] = group
            child = QTreeWidgetItem([self._label(ds)])
            child.setData(0, Qt.ItemDataRole.UserRole, ds)
            child.setIcon(0, dataset_thumbnail(ds, size=THUMB_SIZE))
            child.setToolTip(0, self._tooltip(ds))
            groups[gkey].addChild(child)
        self.tree.addTopLevelItem(top)
        top.setExpanded(True)
        for group in groups.values():
            group.setExpanded(True)
        self._apply_filter(self.filter.text())

    def _label(self, ds: Dataset) -> str:
        icon = _KIND_ICON.get(ds.kind, "•")
        shape = "×".join(str(n) for n in ds.shape)
        return f"{icon}  {ds.display_name()}  ({shape})"

    def _tooltip(self, ds: Dataset) -> str:
        m = ds.metadata or {}
        bits = [
            ds.display_name(),
            ds.kind.value,
            "×".join(str(n) for n in ds.shape),
            str(m.get("detector") or ds.detector or ""),
        ]
        return "\n".join(b for b in bits if b)

    def _dataset_from_item(self, item: QTreeWidgetItem | None) -> Dataset | None:
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return data if isinstance(data, Dataset) else None

    def _payload(self, item: QTreeWidgetItem | None):
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_double(self, item: QTreeWidgetItem, _col: int) -> None:
        ds = self._dataset_from_item(item)
        if ds is not None:
            self.datasetActivated.emit(ds)

    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        payload = self._payload(item)
        if payload is not None:
            self.datasetSelected.emit(payload)

    def _on_current(self, current: QTreeWidgetItem, _prev: QTreeWidgetItem) -> None:
        payload = self._payload(current)
        if payload is not None:
            self.datasetSelected.emit(payload)

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(i), needle)

    def _filter_item(self, item: QTreeWidgetItem, needle: str) -> bool:
        child_hit = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), needle):
                child_hit = True
        if not needle:
            item.setHidden(False)
            return True
        payload = self._payload(item)
        hay = item.text(0).lower()
        if isinstance(payload, Dataset):
            hay = f"{hay} {payload.display_name().lower()} {payload.kind.value}"
        elif isinstance(payload, ExperimentFile):
            hay = f"{hay} {payload.name.lower()}"
        own = needle in hay
        show = own or child_hit
        item.setHidden(not show)
        if show and child_hit:
            item.setExpanded(True)
        return show

    def all_datasets(self) -> list[Dataset]:
        out: list[Dataset] = []

        def walk(item: QTreeWidgetItem) -> None:
            ds = self._dataset_from_item(item)
            if ds is not None:
                out.append(ds)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def datasets_by_name(self) -> dict[str, Dataset]:
        return {ds.name: ds for ds in self.all_datasets()}

    def selected_dataset(self) -> Dataset | None:
        return self._dataset_from_item(self.tree.currentItem())
