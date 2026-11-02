"""Simple image-processing undo / redo stack."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from openvelox.models import Dataset


@dataclass
class Snapshot:
    name: str
    data: np.ndarray
    metadata: dict[str, Any]
    kind: str


class UndoStack:
    def __init__(self, limit: int = 40) -> None:
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        self.limit = limit

    def push(self, dataset: Dataset) -> None:
        snap = Snapshot(
            name=dataset.name,
            data=np.array(dataset.materialize(), copy=True),
            metadata=dict(dataset.metadata),
            kind=dataset.kind.value,
        )
        self._undo.append(snap)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, current: Dataset) -> Snapshot | None:
        if not self._undo:
            return None
        self._redo.append(
            Snapshot(
                name=current.name,
                data=np.array(current.materialize(), copy=True),
                metadata=dict(current.metadata),
                kind=current.kind.value,
            )
        )
        return self._undo.pop()

    def redo(self, current: Dataset) -> Snapshot | None:
        if not self._redo:
            return None
        self._undo.append(
            Snapshot(
                name=current.name,
                data=np.array(current.materialize(), copy=True),
                metadata=dict(current.metadata),
                kind=current.kind.value,
            )
        )
        return self._redo.pop()
