"""Background jobs with a progress dialog for heavy processing."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from openvelox.crashlog import report_exception, widget_alive


class _FnWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, args: tuple, kwargs: dict) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            self.finished.emit(self._fn(*self._args, **self._kwargs))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def _run_sync(
    fn: Callable,
    args: tuple,
    kwargs: dict,
    on_done: Callable[[Any], None] | None,
    on_fail: Callable[[str], None] | None,
) -> None:
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        if on_fail:
            on_fail(str(exc))
        else:
            report_exception(exc, where="background")
        return
    if on_done:
        on_done(result)


def run_in_background(
    parent: QWidget | None,
    title: str,
    fn: Callable,
    *args: Any,
    on_done: Callable[[Any], None] | None = None,
    on_fail: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> None:
    """Run ``fn`` on a QThread. Falls back to in-process if no event loop."""
    app = QApplication.instance()
    force_sync = bool(os.environ.get("OPENVELOX_SYNC_JOBS") or os.environ.get("PYTEST_CURRENT_TEST"))
    if force_sync or app is None:
        _run_sync(fn, args, kwargs, on_done, on_fail)
        return

    progress = QProgressDialog(title, None, 0, 0, parent)
    progress.setWindowTitle(title)
    progress.setMinimumDuration(200)
    progress.setCancelButton(None)
    progress.setAutoClose(True)
    progress.show()

    thread = QThread(parent)
    worker = _FnWorker(fn, args, kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def _ok(result: Any) -> None:
        if widget_alive(progress):
            progress.close()
        thread.quit()
        if not thread.wait(5000):
            thread.terminate()
            thread.wait(500)
        if on_done and (parent is None or widget_alive(parent)):
            try:
                on_done(result)
            except Exception as exc:  # noqa: BLE001
                report_exception(exc, where="background.on_done")

    def _err(msg: str) -> None:
        if widget_alive(progress):
            progress.close()
        thread.quit()
        thread.wait(2000)
        if on_fail and (parent is None or widget_alive(parent)):
            try:
                on_fail(msg)
            except Exception as exc:  # noqa: BLE001
                report_exception(exc, where="background.on_fail")

    worker.finished.connect(_ok, Qt.ConnectionType.QueuedConnection)
    worker.failed.connect(_err, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(worker.deleteLater)
    # Keep refs on the parent (or progress) so GC cannot collect the thread.
    holder = parent if parent is not None else progress
    jobs = getattr(holder, "_ov_jobs", None)
    if jobs is None:
        jobs = []
        holder._ov_jobs = jobs  # type: ignore[attr-defined]
    jobs.append((thread, worker, progress))
    progress._ov_thread = thread  # type: ignore[attr-defined]
    progress._ov_worker = worker  # type: ignore[attr-defined]
    thread.start()
