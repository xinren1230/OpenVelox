from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


def test_main_window_opens_sample(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from openvelox.i18n import Translator
    from openvelox.theme import STYLESHEET, apply_pyqtgraph
    from openvelox.ui.main_window import MainWindow

    apply_pyqtgraph()
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("DejaVu Sans", 10))
    app.setStyleSheet(STYLESHEET)
    win = MainWindow(Translator("en"))
    exp = win.open_sample()
    assert exp.datasets
    assert win.tabs.count() >= 1
    win._run_process("fft", {})
    assert any(getattr(win.tabs.widget(i), "is_fft", False) for i in range(win.tabs.count()))
    session = tmp_path / "sess.json"
    from openvelox.ui.session import save_session

    save_session(session, {"files": win._open_paths, "language": "en", "k_factors": {"Au": 1.8}})
    win.tr_.set_language("zh")
    assert "透射" in win.windowTitle()
    win._tile_views()
    shots = win.capture_screenshots(tmp_path / "shots")
    names = {p.name for p in shots}
    for required in (
        "main_window.png",
        "multi_panel.png",
        "fft_view.png",
        "fft_mask.png",
        "dcfi.png",
        "eds_mapping.png",
        "eds_quant.png",
        "overlay_mixer.png",
        "stem4d.png",
        "measurements.png",
    ):
        assert required in names
        assert (tmp_path / "shots" / required).stat().st_size > 1000
    win.close()
