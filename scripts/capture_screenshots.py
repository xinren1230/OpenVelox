#!/usr/bin/env python3
"""Launch OpenVelox offscreen, open the sample, save the README gallery views."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("OPENVELOX_SYNC_JOBS", "1")
os.environ.setdefault("OPENVELOX_NO_DIALOG", "1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        default=str(ROOT / "docs" / "screenshots"),
        help="Directory for PNG screenshots",
    )
    args = parser.parse_args()

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from openvelox.i18n import Translator
    from openvelox.theme import STYLESHEET, apply_pyqtgraph
    from openvelox.ui.main_window import MainWindow

    apply_pyqtgraph()
    app = QApplication.instance() or QApplication(["OpenVelox"])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(Translator("en"))
    window.show()
    window.open_sample()
    app.processEvents()
    window.capture_screenshots(args.output)
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
