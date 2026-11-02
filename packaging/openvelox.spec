# PyInstaller spec — one-folder Windows (or Linux) app:
#   pyinstaller packaging/openvelox.spec
# Onefile-compatible: openvelox.paths.window_icon_path() and resource_root()
# read sys._MEIPASS first. To emit a true onefile EXE, set exclude_binaries=False
# on EXE and drop the COLLECT block.
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis

ROOT = Path(SPECPATH).resolve().parents[0]

analysis = Analysis(
    [str(ROOT / "openvelox" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "samples" / "synthetic_velox.emd"), "samples"),
        (str(ROOT / "docs" / "screenshots"), "docs/screenshots"),
        (str(ROOT / "openvelox" / "resources" / "openvelox.ico"), "openvelox/resources"),
        (str(ROOT / "openvelox" / "resources" / "logo.png"), "openvelox/resources"),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "pyqtgraph",
        "h5py",
        "scipy",
        "skimage",
        "tifffile",
        "openvelox.crashlog",
        "openvelox.paths",
        "openvelox.processing.preview",
        "openvelox.ui.prefs",
        "openvelox.ui.icons",
        "shiboken6",
        "multiprocessing",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="OpenVelox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "openvelox" / "resources" / "openvelox.ico"),
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.zipfiles,
    analysis.datas,
    strip=False,
    upx=True,
    name="OpenVelox",
)
