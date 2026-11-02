"""Keep a windowed / frozen OpenVelox process alive when something throws.

Unhandled exceptions in Qt slots kill ``--windowed`` PyInstaller binaries
because ``sys.stderr`` is ``None`` and the default hook has nowhere to go.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openvelox.paths import log_dir

LOG_NAME = "openvelox.log"
CRASH_NAME = "crash.log"

_LOGGER: logging.Logger | None = None
_CRASH_FH = None
_INSTALLED = False


def safe_write(stream: Any, text: str) -> None:
    if stream is None:
        return
    try:
        stream.write(text)
        stream.flush()
    except Exception:
        return


def safe_print(*args: object, **kwargs: object) -> None:
    stream = kwargs.pop("file", sys.stderr if sys.stderr is not None else sys.stdout)
    sep = str(kwargs.get("sep", " "))
    end = str(kwargs.get("end", "\n"))
    safe_write(stream, sep.join(str(a) for a in args) + end)


def log_path() -> Path:
    return log_dir() / LOG_NAME


def crash_path() -> Path:
    return log_dir() / CRASH_NAME


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger("openvelox")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    path = str(log_path())
    has_file = any(getattr(h, "baseFilename", None) == path for h in logger.handlers)
    if not has_file:
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
        )
        logger.addHandler(handler)
    if sys.stderr is not None and not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in logger.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        logger.addHandler(stream)
    _LOGGER = logger
    return logger


def _format_exception(exc_type, exc, tb) -> str:
    return "".join(traceback.format_exception(exc_type, exc, tb))


def _should_dialog() -> bool:
    if os.environ.get("OPENVELOX_NO_DIALOG"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return True


def show_error_dialog(title: str, message: str) -> None:
    if not _should_dialog():
        return
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle(title)
        box.setText(message[:2000])
        box.setInformativeText(f"A full traceback was written to:\n{log_path()}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
    except Exception:
        return


def report_exception(exc: BaseException | None = None, *, where: str = "") -> None:
    if exc is None:
        exc_type, exc, tb = sys.exc_info()
        text = _format_exception(exc_type, exc, tb) if exc_type else "Unknown error\n"
    else:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    header = f"{datetime.now(timezone.utc).isoformat()} {where}\n"
    get_logger().error("%s%s", header, text)
    safe_write(sys.stderr, header + text)
    preview = text.strip().splitlines()
    brief = preview[-1] if preview else "Unexpected error"
    show_error_dialog("OpenVelox", f"{where + ': ' if where else ''}{brief}")


def _excepthook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        if sys.__excepthook__ is not _excepthook:
            sys.__excepthook__(exc_type, exc, tb)
        return
    text = _format_exception(exc_type, exc, tb)
    get_logger().error("unhandled exception\n%s", text)
    safe_write(sys.stderr, text)
    preview = text.strip().splitlines()
    show_error_dialog("OpenVelox", preview[-1] if preview else "Unexpected error")


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is KeyboardInterrupt:
        return
    report_exception(args.exc_value, where=f"thread {args.thread.name if args.thread else '?'}")


def _qt_message_handler(mode, context, message) -> None:
    try:
        from PySide6.QtCore import QtMsgType

        level = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }.get(mode, logging.WARNING)
    except Exception:
        level = logging.WARNING
    loc = ""
    try:
        if context is not None and getattr(context, "file", None):
            loc = f" ({context.file}:{context.line})"
    except Exception:
        loc = ""
    get_logger().log(level, "Qt%s: %s", loc, message)


def install_faulthandler() -> None:
    global _CRASH_FH
    try:
        _CRASH_FH = open(crash_path(), "a", encoding="utf-8")  # noqa: SIM115
        _CRASH_FH.write(f"\n--- faulthandler {datetime.now(timezone.utc).isoformat()} ---\n")
        _CRASH_FH.flush()
        faulthandler.enable(file=_CRASH_FH, all_threads=True)
    except Exception:
        try:
            faulthandler.enable()
        except Exception:
            return


def install() -> None:
    """Install process-wide hooks. Safe to call more than once."""
    global _INSTALLED
    if _INSTALLED:
        return
    get_logger().info("OpenVelox starting (frozen=%s)", bool(getattr(sys, "frozen", False)))
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    install_faulthandler()
    try:
        from PySide6.QtCore import qInstallMessageHandler

        qInstallMessageHandler(_qt_message_handler)
    except Exception:
        pass
    _INSTALLED = True


def wrap_slot(fn: Callable) -> Callable:
    def _inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            report_exception(exc, where=getattr(fn, "__qualname__", getattr(fn, "__name__", "slot")))
            return None

    _inner.__name__ = getattr(fn, "__name__", "slot")
    return _inner


def widget_alive(obj: Any) -> bool:
    if obj is None:
        return False
    try:
        from shiboken6 import isValid

        return bool(isValid(obj))
    except Exception:
        try:
            obj.objectName()
            return True
        except Exception:
            return False
