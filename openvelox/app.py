"""OpenVelox application entry point."""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()

    from openvelox.crashlog import install, report_exception, safe_print

    try:
        install()
    except Exception as exc:  # noqa: BLE001
        safe_print(f"crashlog install failed: {exc}")

    parser = argparse.ArgumentParser(description="OpenVelox — Velox-like TEM/STEM analysis")
    parser.add_argument("files", nargs="*", help="EMD / SER / DM / TIFF files to open")
    parser.add_argument("--sample", action="store_true", help="Generate and open the synthetic Velox EMD")
    parser.add_argument("--lang", choices=("en", "zh"), default="en", help="UI language")
    parser.add_argument(
        "--screenshot-dir",
        default=None,
        help="After launch, grab the main / EDS / FFT views and exit",
    )
    parser.add_argument("--offscreen", action="store_true", help="Force Qt offscreen platform")
    args = parser.parse_args(argv)

    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    os.environ.setdefault("QT_API", "pyside6")

    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from openvelox.i18n import Translator
    from openvelox.paths import ensure_window_icon
    from openvelox.theme import STYLESHEET, apply_pyqtgraph
    from openvelox.ui.main_window import MainWindow, schedule_screenshots

    apply_pyqtgraph()
    app = QApplication.instance() or QApplication(sys.argv if sys.argv else ["OpenVelox"])
    try:
        icon_path = ensure_window_icon()
        if icon_path is not None and icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception as exc:  # noqa: BLE001
        safe_print(f"window icon failed: {exc}")
    app.setApplicationName("OpenVelox")
    app.setOrganizationName("OpenVelox")
    app.setStyle("Fusion")
    app.setFont(QFont("Inter", 10))
    app.setStyleSheet(STYLESHEET)

    translator = Translator(args.lang)
    window = MainWindow(translator)
    window.show()

    for path in args.files:
        try:
            window.load_path(path)
        except Exception as exc:  # noqa: BLE001
            report_exception(exc, where=f"open {path}")
    if args.sample or (args.screenshot_dir and not args.files):
        try:
            window.open_sample()
        except Exception as exc:  # noqa: BLE001
            report_exception(exc, where="open sample")

    if args.screenshot_dir:
        schedule_screenshots(window, Path(args.screenshot_dir))

    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
