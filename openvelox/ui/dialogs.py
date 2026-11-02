"""Modal dialogs: image calculator, about."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout

from openvelox.models import Dataset


class ImageCalculatorDialog(QDialog):
    def __init__(self, translator, datasets: list[Dataset], parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self.setWindowTitle(translator("image_calc"))
        self.datasets = datasets
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.op = QComboBox()
        self.op.addItems(["add", "sub", "mul", "div", "invert", "normalize"])
        self.a = QComboBox()
        self.b = QComboBox()
        for ds in datasets:
            if ds.data.ndim >= 2:
                label = ds.display_name()
                self.a.addItem(label, ds)
                self.b.addItem(label, ds)
        form.addRow(translator("dataset_a"), self.a)
        form.addRow(translator("dataset_b"), self.b)
        form.addRow("Op", self.op)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> tuple[str, Dataset | None, Dataset | None]:
        return (
            self.op.currentText(),
            self.a.currentData(),
            self.b.currentData(),
        )
