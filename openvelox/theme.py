"""Dark Thermo Fisher Velox-inspired laboratory theme."""

from __future__ import annotations

THERMO_CYAN = "#00A3E0"
NAVY = "#0E1C26"
NAVY_DEEP = "#081118"
PANEL = "#1B242C"
CHROME = "#12181D"
TEXT = "#E8EEF2"
MUTED = "#8A96A0"
IMAGE_BG = "#0A0D10"
BORDER = "#2C3944"

STYLESHEET = f"""
* {{
    font-family: "Inter", "DejaVu Sans", "Noto Sans", sans-serif;
}}
QMainWindow, QDialog, QMdiArea {{
    background: {CHROME};
    color: {TEXT};
}}
QMenuBar {{
    background: {NAVY_DEEP};
    color: {TEXT};
    padding: 2px 6px;
    font-weight: 500;
}}
QMenuBar::item:selected {{
    background: {NAVY};
}}
QMenu {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background: {THERMO_CYAN};
    color: #FFFFFF;
}}
QToolBar {{
    background: {NAVY};
    border: none;
    spacing: 4px;
    padding: 4px 8px;
    color: {TEXT};
}}
QToolBar QToolButton {{
    color: {TEXT};
    background: transparent;
    padding: 5px 8px;
    border-radius: 3px;
}}
QToolBar QToolButton:hover, QToolBar QToolButton:checked {{
    background: {THERMO_CYAN};
    color: #FFFFFF;
}}
QDockWidget {{
    color: {TEXT};
    font-weight: 600;
    titlebar-close-icon: none;
}}
QDockWidget::title {{
    background: {NAVY};
    color: {TEXT};
    padding: 6px 8px;
    border: none;
}}
QTreeWidget, QTableWidget, QListWidget, QTextEdit, QPlainTextEdit {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    alternate-background-color: #162028;
    selection-background-color: {THERMO_CYAN};
    selection-color: #FFFFFF;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {PANEL};
}}
QTabBar::tab {{
    background: #151C22;
    color: {MUTED};
    padding: 6px 12px;
    border: 1px solid {BORDER};
    border-bottom: none;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {PANEL};
    color: {THERMO_CYAN};
    font-weight: 600;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    margin-top: 12px;
    padding: 8px 6px 6px 6px;
    font-weight: 600;
    color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {THERMO_CYAN};
}}
QPushButton {{
    background: #24303A;
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 5px 10px;
    color: {TEXT};
}}
QPushButton:hover {{
    border-color: {THERMO_CYAN};
    color: #FFFFFF;
}}
QPushButton:pressed {{
    background: {THERMO_CYAN};
    color: #FFFFFF;
}}
QPushButton:disabled {{
    color: #5C6770;
    background: #151C22;
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {THERMO_CYAN};
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: #0F161C;
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 3px 6px;
    color: {TEXT};
}}
QStatusBar {{
    background: {NAVY_DEEP};
    color: #D7E3EA;
}}
QHeaderView::section {{
    background: #151C22;
    color: {TEXT};
    padding: 4px;
    border: 1px solid {BORDER};
    font-weight: 600;
}}
QSplitter::handle {{
    background: {BORDER};
}}
QLabel {{
    color: {TEXT};
}}
QLabel#hint {{
    color: {MUTED};
}}
QToolTip {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {THERMO_CYAN};
    padding: 4px 6px;
}}
QCheckBox {{
    color: {TEXT};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 13px;
    height: 13px;
    border: 1px solid {BORDER};
    background: #0F161C;
}}
QCheckBox::indicator:checked {{
    background: {THERMO_CYAN};
}}
QScrollArea {{
    background: {PANEL};
    border: none;
}}
QProgressBar {{
    background: #0F161C;
    border: 1px solid {BORDER};
    color: {TEXT};
    text-align: center;
}}
QProgressBar::chunk {{
    background: {THERMO_CYAN};
}}
QMdiSubWindow {{
    background: {CHROME};
    color: {TEXT};
}}
"""


def apply_pyqtgraph() -> None:
    import pyqtgraph as pg

    pg.setConfigOptions(
        imageAxisOrder="row-major",
        antialias=True,
        background=IMAGE_BG,
        foreground="#E8EEF2",
        useNumba=False,
    )
