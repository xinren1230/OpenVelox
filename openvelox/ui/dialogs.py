"""Modal dialogs: image calculator, about."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from openvelox.models import Dataset

_PRESETS = (
    ("A+B", "add"),
    ("A-B", "sub"),
    ("A*B", "mul"),
    ("A/B", "div"),
    ("A/(A+B)", "A/(A+B)"),
    ("2*A", "2*A"),
    ("abs(A-B)", "abs(A-B)"),
    ("log(A+1)", "log(A+1)"),
    ("sqrt(A)", "sqrt(A)"),
    ("invert", "invert"),
    ("normalize", "normalize"),
)


class ImageCalculatorDialog(QDialog):
    def __init__(self, translator, datasets: list[Dataset], parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self.setWindowTitle(translator("image_calc"))
        self.datasets = datasets
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.op = QComboBox()
        for label, _key in _PRESETS:
            self.op.addItem(label)
        self.expr = QLineEdit("A+B")
        self.a = QComboBox()
        self.b = QComboBox()
        for ds in datasets:
            if getattr(ds.data, "ndim", 0) >= 2:
                label = ds.display_name()
                self.a.addItem(label, ds)
                self.b.addItem(label, ds)
        form.addRow(translator("dataset_a"), self.a)
        form.addRow(translator("dataset_b"), self.b)
        form.addRow(translator("presets"), self.op)
        form.addRow(translator("expression"), self.expr)
        layout.addLayout(form)
        self.op.currentTextChanged.connect(self.expr.setText)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def expression(self) -> str:
        text = self.expr.text().strip()
        return text or self.op.currentText()

    def selection(self) -> tuple[str, Dataset | None, Dataset | None]:
        mapping = {label: key for label, key in _PRESETS}
        op = mapping.get(self.op.currentText(), self.op.currentText())
        return (
            op,
            self.a.currentData(),
            self.b.currentData(),
        )
