"""Velox-like main window: docks, toolbar, tabbed workspace."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QWidget,
)

from openvelox import __version__
from openvelox.crashlog import report_exception, widget_alive, wrap_slot
from openvelox.io.metadata import format_coord, format_pixel_size
from openvelox.io.readers import load_experiment
from openvelox.io.synthetic import generate_synthetic_emd
from openvelox.io.report import export_report
from openvelox.io.writers import batch_export_images, export_image, export_overlay, export_quant_table, export_spectrum_csv
from openvelox.models import Dataset, DatasetKind, ExperimentFile
from openvelox.processing.atoms import find_atom_columns
from openvelox.processing.display import auto_levels, load_lut, register_lut
from openvelox.processing.dpc import ddpc, dpc_color, dpc_from_quadrants, idpc
from openvelox.processing.drift import align_and_sum, dcfi
from openvelox.processing.eds import (
    cliff_lorimer,
    cliff_lorimer_abs,
    color_overlay,
    element_map,
    energy_axis,
    export_line_scan_csv,
    gaussian_net_map,
    identify_peaks,
    integrate_windows,
    line_scan,
    line_scan_element_profile,
    make_element_maps,
    pca_denoise,
    spectrum_background,
    sum_spectrum,
)
from openvelox.processing.xray_lines import K_FACTORS_VS_SI
from openvelox.processing.fft import apply_mask, feather_mask, fft2d, ifft2d, make_mask, power_spectrum, reconstruct
from openvelox.processing.filters import (
    average_background,
    gaussian_filter,
    highpass_filter,
    median_filter,
    sobel_filter,
    subtract_background,
    unsharp_mask,
    wiener_filter,
)
from openvelox.processing.image_calc import image_calculate
from openvelox.processing.measure import (
    angle_deg,
    area_m2,
    distance,
    fft_d_spacing,
    format_area,
    line_profile,
    profile_stats,
    roi_stats,
)
from openvelox.processing.scalebar import ScaleBarStyle
from openvelox.processing.stem4d import (
    apply_diffraction_cal,
    center_of_mass_dpc,
    electron_wavelength_m,
    q_per_px_inv_angstrom,
    radius_to_pixels,
    virtual_abf,
    virtual_adf,
    virtual_bf,
)
from openvelox.ui.session import dataset_ref, load_session, save_session
from openvelox.processing.xray_lines import lines_for
from openvelox.ui.browser import BrowserPanel
from openvelox.ui.dialogs import ImageCalculatorDialog
from openvelox.ui.icons import icon_for
from openvelox.ui.image_canvas import ImageCanvas
from openvelox.ui.overlay_mixer import OverlayMixer
from openvelox.ui.workspace import MultiPanelView, layout_keys, layout_shape, mirror_view
from openvelox.ui.prefs import add_recent, clear_recent, load_prefs, recent_files, save_prefs
from openvelox.ui.property_panel import PropertyPanel
from openvelox.ui.spectrum_view import SpectrumView
from openvelox.ui.undo import UndoStack
from openvelox.ui.worker import run_in_background


def _persist_chrome() -> bool:
    return not os.environ.get("PYTEST_CURRENT_TEST")


class ImageTab(QWidget):
    def __init__(self, dataset: Dataset, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout

        self.dataset = dataset
        self.canvas = ImageCanvas()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self._preview = bool(dataset.is_large())
        frame_loader = None
        n_frames = 0
        if dataset.kind is DatasetKind.STACK and dataset.n_frames() > 1:
            n_frames = dataset.n_frames()

            def _frame(i: int, ds: Dataset = dataset) -> np.ndarray:
                return ds.image2d(index=int(i), preview=False)

            frame_loader = _frame
        try:
            image = dataset.image2d(preview=self._preview)
        except Exception:
            image = np.zeros((8, 8), dtype=np.float64)
        self.canvas.set_image(
            image,
            pixel_m=dataset.pixel_size_m(),
            n_frames=n_frames,
            frame_loader=frame_loader,
        )
        self.fft_spectrum: np.ndarray | None = None
        self.is_fft = False

    def upgrade_full(self) -> None:
        if not self._preview:
            return
        try:
            image = self.dataset.image2d(index=self.canvas.frame_index(), preview=False)
        except Exception:
            return
        self.canvas.set_image(
            image,
            pixel_m=self.dataset.pixel_size_m(),
            reset_levels=False,
            n_frames=self.canvas._n_frames,
            frame_loader=self.canvas._frame_loader,
        )
        self._preview = False


class MainWindow(QMainWindow):
    def __init__(self, translator, parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self.setWindowTitle(self.tr_("app_title"))
        self.resize(1480, 920)
        self.quant_rows: list[dict] = []
        self._last_maps: dict[str, np.ndarray] = {}
        self._current_si: Dataset | None = None
        self._fft_source: np.ndarray | None = None
        self.undo_stack = UndoStack()
        self._open_paths: list[str] = []
        self._sync_views = False
        self._layout_key = "1x1"
        self._last_line_scan: np.ndarray | None = None
        self._last_line_path: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._last_roi_energy = None
        self._last_roi_spec = None

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab)
        self._workspace = QSplitter()
        self._workspace.addWidget(self.tabs)
        self.setCentralWidget(self._workspace)

        self.browser = BrowserPanel(translator)
        self.browser.datasetActivated.connect(self._open_from_browser)
        self.browser.datasetSelected.connect(self._on_browser_select)
        self._multi: MultiPanelView | None = None
        self.props = PropertyPanel(translator)
        self.spectrum = SpectrumView(translator)

        self.mixer = OverlayMixer(translator)
        self.mixer.mixChanged.connect(self._on_mix)
        self._docks = {
            "experiment": self._add_dock("experiment", self.tr_("experiment"), self.browser, Qt.DockWidgetArea.LeftDockWidgetArea),
            "properties": self._add_dock("properties", self.tr_("properties"), self.props, Qt.DockWidgetArea.RightDockWidgetArea),
            "spectrum": self._add_dock("spectrum", self.tr_("spectrum"), self.spectrum, Qt.DockWidgetArea.BottomDockWidgetArea),
            "layers": self._add_dock("layers", self.tr_("layers"), self.mixer, Qt.DockWidgetArea.RightDockWidgetArea),
        }
        self.tabifyDockWidget(self._docks["properties"], self._docks["layers"])
        self._docks["properties"].raise_()
        self.props.set_k_rows(dict(list(K_FACTORS_VS_SI.items())[:12]))

        self.status = QLabel(self.tr_("ready"))
        self.coord = QLabel("")
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().addPermanentWidget(self.coord)

        self.props.displayChanged.connect(self._on_display)
        self.props.autoContrast.connect(self._auto_contrast)
        self.props.processRequested.connect(self._on_process)
        self.props.profile_width.valueChanged.connect(self._on_profile_width)
        self.props.scaleBarChanged.connect(self._on_scale_bar)

        self._actions: dict[str, QAction] = {}
        self._build_menus()
        self._build_toolbar()
        self.setAcceptDrops(True)
        if _persist_chrome():
            self.restore_chrome()
        translator.on_change(self.retranslate)

    def _add_dock(self, key: str, title: str, widget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(key)
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(area, dock)
        return dock

    def _act(self, key: str, slot, shortcut: str | None = None, checkable: bool = False) -> QAction:
        act = QAction(self.tr_(key), self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.setCheckable(checkable)
        # QAction.triggered always emits a bool; a 0-arg slot TypeErrors and
        # kills a --windowed PyInstaller binary.
        safe = wrap_slot(slot)
        if checkable:
            act.triggered.connect(lambda checked=False, s=safe: s(checked))
        else:
            act.triggered.connect(lambda _checked=False, s=safe: s())
        self._actions[key] = act
        return act

    def invoke_action(self, key: str) -> None:
        """Test / script helper: fire a named action without a bool argument."""
        act = self._actions.get(key)
        if act is not None:
            act.trigger()

    def _close_current_tab(self) -> None:
        if self.tabs.count():
            self._close_tab(self.tabs.currentIndex())

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if isinstance(widget, ImageTab):
            widget.canvas.teardown()
        elif widget is not None:
            for child in widget.findChildren(ImageTab):
                child.canvas.teardown()
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(self.tr_("file"))
        file_menu.addAction(self._act("open", self.open_files, "Ctrl+O"))
        file_menu.addAction(self._act("open_sample", self.open_sample))
        self._recent_menu = file_menu.addMenu(self.tr_("recent_files"))
        file_menu.addAction(self._act("clear_recent", self._clear_recent))
        file_menu.addAction(self._act("save_session", self.save_session_dialog, "Ctrl+Shift+S"))
        file_menu.addAction(self._act("load_session", self.load_session_dialog, "Ctrl+Shift+O"))
        file_menu.addSeparator()
        file_menu.addAction(self._act("export_image", self.export_current_image, "Ctrl+E"))
        file_menu.addAction(self._act("export_overlay", self.export_current_overlay, "Ctrl+Shift+V"))
        file_menu.addAction(self._act("export_report", self.export_report_dialog, "Ctrl+Shift+R"))
        file_menu.addAction(self._act("batch_export", self.batch_export, "Ctrl+Shift+E"))
        file_menu.addAction(self._act("export_spectrum", self.export_current_spectrum))
        file_menu.addAction(self._act("export_map", self.export_current_map))
        file_menu.addAction(self._act("export_quant", self.export_quant))
        file_menu.addAction(self._act("export_roi", self.export_roi_spectrum))
        file_menu.addAction(self._act("export_linescan", self.export_line_scan))
        file_menu.addSeparator()
        file_menu.addAction(self._act("close_tab", self._close_current_tab, "Ctrl+W"))
        file_menu.addAction(self._act("quit", lambda: self.close(), "Ctrl+Q"))
        self._file_menu = file_menu
        self._rebuild_recent()

        view = self.menuBar().addMenu(self.tr_("view"))
        view.addAction(self._act("fit", self._fit, "Ctrl+0"))
        view.addAction(self._act("tile", self._tile_views))
        view.addAction(self._act("sync_views", self._toggle_sync, checkable=True))
        self._layout_menu = view.addMenu(self.tr_("layout"))
        self._layout_group = QActionGroup(self)
        for key in layout_keys():
            act = self._act(f"layout_{key}", lambda _=False, k=key: self.apply_layout(k), checkable=True)
            self._layout_group.addAction(act)
            self._layout_menu.addAction(act)
        self._actions["layout_1x1"].setChecked(True)
        view.addAction(self._act("undo", self._undo, "Ctrl+Z"))
        view.addAction(self._act("redo", self._redo, "Ctrl+Y"))
        view.addAction(self._act("reset_layout", self.reset_layout))
        lang = view.addMenu(self.tr_("language"))
        group = QActionGroup(self)
        en = QAction(self.tr_("english"), self, checkable=True)
        zh = QAction(self.tr_("chinese"), self, checkable=True)
        en.setChecked(self.tr_.lang == "en")
        zh.setChecked(self.tr_.lang == "zh")
        en.triggered.connect(lambda: self.tr_.set_language("en"))
        zh.triggered.connect(lambda: self.tr_.set_language("zh"))
        group.addAction(en)
        group.addAction(zh)
        lang.addAction(en)
        lang.addAction(zh)
        self._view_menu = view
        self._lang_menu = lang

        tools = self.menuBar().addMenu(self.tr_("tools"))
        self._tool_group = QActionGroup(self)
        tool_keys = {
            "pointer": "Escape",
            "line_profile": "L",
            "distance": "D",
            "angle": "A",
            "d_spacing": "G",
            "roi_rect": "R",
            "roi_ellipse": "Shift+R",
            "roi_polygon": "P",
        }
        for key, shortcut in tool_keys.items():
            act = self._act(key, lambda _=False, k=key: self._set_tool(k), shortcut=shortcut, checkable=True)
            self._tool_group.addAction(act)
            tools.addAction(act)
        self._actions["pointer"].setChecked(True)
        tools.addSeparator()
        tools.addAction(self._act("clear_overlays", self._clear_overlays))
        self._tools_menu = tools

        proc = self.menuBar().addMenu(self.tr_("process"))
        proc.addAction(self._act("fft", lambda: self._on_process("fft", {}), "Ctrl+F"))
        proc.addAction(self._act("gaussian", lambda: self._on_process("gaussian", {"sigma": 1.2})))
        proc.addAction(self._act("unsharp", lambda: self._on_process("unsharp", {"sigma": 1.2})))
        proc.addAction(self._act("sobel", lambda: self._on_process("sobel", {})))
        proc.addAction(self._act("highpass", lambda: self._on_process("highpass", {"bg_sigma": 3})))
        proc.addAction(self._act("image_calc", lambda: self._on_process("image_calc", {})))
        self._proc_menu = proc

        help_menu = self.menuBar().addMenu(self.tr_("help"))
        help_menu.addAction(self._act("about", self._about))
        self._help_menu = help_menu

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setObjectName("mainToolbar")
        bar.setMovable(False)
        bar.setStyleSheet(
            "QToolBar { background-color: #163445; border: none; spacing: 4px; padding: 4px 8px; }"
            "QToolButton { color: #F4F7FA; background: transparent; padding: 5px 8px; border-radius: 3px; }"
            "QToolButton:hover, QToolButton:checked { background: #00A3E0; color: #FFFFFF; }"
        )
        for key in (
            "open",
            "open_sample",
            "pointer",
            "line_profile",
            "distance",
            "angle",
            "d_spacing",
            "roi_rect",
            "roi_polygon",
            "fft",
            "filters",
        ):
            if key == "filters":
                bar.addSeparator()
                continue
            if key in self._actions:
                act = self._actions[key]
                icon = icon_for(key)
                if not icon.isNull():
                    act.setIcon(icon)
                bar.addAction(act)
        fit = self._actions["fit"]
        icon = icon_for("fit")
        if not icon.isNull():
            fit.setIcon(icon)
        bar.addAction(fit)

    def retranslate(self) -> None:
        self.setWindowTitle(self.tr_("app_title"))
        for key, act in self._actions.items():
            act.setText(self.tr_(key))
        self._file_menu.setTitle(self.tr_("file"))
        self._recent_menu.setTitle(self.tr_("recent_files"))
        self._view_menu.setTitle(self.tr_("view"))
        self._layout_menu.setTitle(self.tr_("layout"))
        self._lang_menu.setTitle(self.tr_("language"))
        self._tools_menu.setTitle(self.tr_("tools"))
        self._proc_menu.setTitle(self.tr_("process"))
        self._help_menu.setTitle(self.tr_("help"))
        self.browser.retranslate()
        self.props.retranslate()
        self.spectrum.retranslate()
        self.status.setText(self.tr_("ready"))
        for key, dock in self._docks.items():
            dock.setWindowTitle(self.tr_(key))

    def current_tab(self) -> ImageTab | None:
        w = self.tabs.currentWidget()
        if isinstance(w, ImageTab):
            return w
        if isinstance(w, MultiPanelView):
            return w.focused_panel()
        if w is not None:
            found = w.findChildren(ImageTab)
            if found:
                return found[0]
        return None

    def _on_browser_select(self, obj) -> None:
        if isinstance(obj, Dataset):
            self.props.show_dataset(obj)
        elif isinstance(obj, ExperimentFile):
            self.props.show_experiment(obj)

    def _wire_tab(self, tab: ImageTab) -> None:
        tab.canvas.pixelPicked.connect(self._on_pixel)
        tab.canvas.toolFinished.connect(self._on_tool)
        tab.canvas.imageChanged.connect(lambda t=tab: self.props.set_histogram(t.canvas.image))
        tab.canvas.viewChanged.connect(lambda t=tab: self._on_view_sync(t))
        tab.canvas.fftMaskChanged.connect(lambda payload, t=tab: self._on_fft_roi(t, payload))
        tab.canvas.profile_linewidth = float(self.props.profile_width.value())
        tab.canvas.set_scale_bar_style(self.props.scale_bar_style())

    def current_image(self) -> np.ndarray | None:
        tab = self.current_tab()
        return None if tab is None else tab.canvas.image

    def open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.tr_("open"),
            "",
            "EM data (*.emd *.ser *.emi *.dm3 *.dm4 *.tif *.tiff);;All files (*)",
        )
        for path in paths:
            self.load_path(path)

    def load_path(self, path: str | Path) -> ExperimentFile:
        try:
            experiment = load_experiment(path)
        except Exception as exc:
            QMessageBox.critical(self, self.tr_("error"), str(exc))
            report_exception(exc, where=f"load {path}")
            return ExperimentFile(path=str(path), name=Path(path).name, datasets=[], metadata={"error": str(exc)})
        if str(path) not in self._open_paths:
            self._open_paths.append(str(path))
        try:
            add_recent(path)
        except Exception:
            pass
        self._rebuild_recent()
        self.browser.add_experiment(experiment)
        if experiment.datasets:
            preferred = next((d for d in experiment.datasets if d.name == "HAADF"), None)
            preferred = preferred or next((d for d in experiment.datasets if d.kind is DatasetKind.IMAGE), experiment.datasets[0])
            self.open_dataset(preferred)
        self.status.setText(self.tr_("status_opened", n=len(experiment.datasets), name=experiment.name))
        return experiment

    def open_sample(self) -> ExperimentFile:
        path = generate_synthetic_emd(Path.cwd() / "samples")
        return self.load_path(path)

    def _open_from_browser(self, dataset: Dataset):
        current = self.tabs.currentWidget()
        if isinstance(current, MultiPanelView) and current.panel_count() > 1:
            tab = ImageTab(dataset)
            self._wire_tab(tab)
            current.replace_focused(tab)
            self._tiled_tabs = current.panels()
            self.props.show_dataset(dataset)
            self.props.set_histogram(tab.canvas.image)
            self._after_open(tab, dataset)
            return tab
        return self.open_dataset(dataset)

    def open_dataset(self, dataset: Dataset) -> ImageTab:
        tab = ImageTab(dataset)
        self._wire_tab(tab)
        self.tabs.addTab(tab, dataset.display_name())
        self.tabs.setCurrentWidget(tab)
        self.props.show_dataset(dataset)
        self.props.set_histogram(tab.canvas.image)
        self._after_open(tab, dataset)
        return tab

    def _after_open(self, tab: ImageTab, dataset: Dataset) -> None:
        if tab._preview:
            self.status.setText(self.tr_("status_preview"))

            def _upgrade() -> np.ndarray:
                return dataset.image2d(index=0, preview=False)

            def _done(image: np.ndarray, t=tab) -> None:
                if widget_alive(t):
                    t.canvas.set_image(
                        image,
                        pixel_m=dataset.pixel_size_m(),
                        reset_levels=False,
                        n_frames=t.canvas._n_frames,
                        frame_loader=t.canvas._frame_loader,
                    )
                    t._preview = False
                    self.props.set_histogram(t.canvas.image)

            run_in_background(self, self.tr_("working"), _upgrade, on_done=_done)
        if dataset.kind is DatasetKind.SPECTRUM_IMAGE:
            self._current_si = dataset

            def _sum() -> tuple[np.ndarray, np.ndarray]:
                energy = self._energy_for(dataset)
                return energy, sum_spectrum(dataset.data)

            def _sum_done(pair: tuple[np.ndarray, np.ndarray]) -> None:
                self.spectrum.set_spectrum(pair[0], pair[1])

            run_in_background(self, self.tr_("working"), _sum, on_done=_sum_done)
        elif dataset.kind is DatasetKind.SPECTRUM:
            energy = self._energy_for(dataset)
            self.spectrum.set_spectrum(energy, np.asarray(dataset.data, dtype=np.float64))
        elif dataset.kind is DatasetKind.FOUR_D:
            self.status.setText("4D-STEM — use the 4D-STEM panel for virtual detectors")

    def _energy_for(self, dataset: Dataset) -> np.ndarray:
        for ax in dataset.axes:
            if "e" in ax.name.lower() or ax.units.lower() in {"kev", "ev"}:
                coords = ax.coordinates()
                if ax.units.lower() == "ev":
                    return coords / 1000.0
                return coords
        scale = float(dataset.metadata.get("energy_scale_kev", 0.02))
        offset = float(dataset.metadata.get("energy_offset_kev", 0.0))
        n = dataset.data.shape[-1]
        return energy_axis(n, scale, offset)

    def _on_tab(self, _index: int) -> None:
        widget = self.tabs.currentWidget()
        if isinstance(widget, MultiPanelView):
            self._multi = widget
        tab = self.current_tab()
        if tab is None or not widget_alive(tab):
            return
        self.props.show_dataset(tab.dataset)
        self.props.set_histogram(tab.canvas.image, vmin=tab.canvas.vmin, vmax=tab.canvas.vmax)

    def _on_panel(self, tab) -> None:
        if not isinstance(tab, ImageTab) or not widget_alive(tab):
            return
        self.props.show_dataset(tab.dataset)
        self.props.set_histogram(tab.canvas.image, vmin=tab.canvas.vmin, vmax=tab.canvas.vmax)

    def _on_pixel(self, x: int, y: int, value: float) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        px = tab.canvas.pixel_m or 0
        self.coord.setText(
            f"x={format_coord(x, px)}  y={format_coord(y, px)}  I={value:.3g}   {format_pixel_size(px)}/px"
        )
        ds = tab.dataset
        if ds.kind is DatasetKind.SPECTRUM_IMAGE:
            iy = int(np.clip(y, 0, ds.data.shape[0] - 1))
            ix = int(np.clip(x, 0, ds.data.shape[1] - 1))
            energy = self._energy_for(ds)
            self.spectrum.set_spectrum(energy, ds.data[iy, ix], title=f"Pixel ({ix},{iy})")
        elif ds.kind is DatasetKind.FOUR_D:
            self.status.setText(f"4D-STEM probe ({x},{y}) — use the 4D-STEM panel for virtual detectors")

    def _set_tool(self, name: str) -> None:
        tab = self.current_tab()
        if tab:
            tab.canvas.set_tool(name)

    def _clear_overlays(self) -> None:
        tab = self.current_tab()
        if tab:
            tab.canvas.clear_overlays()

    def _fit(self) -> None:
        tab = self.current_tab()
        if tab:
            tab.canvas.fit()

    def _on_display(self, params: dict) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        invert = bool(params.get("invert", False))
        if params.get("vmin") is not None and params.get("vmax") is not None:
            vmin = float(params["vmin"])
            vmax = float(params["vmax"])
            if vmax <= vmin:
                vmax = vmin + 1.0
        else:
            vmin, vmax = tab.canvas.vmin, tab.canvas.vmax
            contrast = float(params.get("contrast", 1.0))
            mid = 0.5 * (vmin + vmax)
            half = 0.5 * (vmax - vmin) / max(contrast, 0.05)
            vmin, vmax = mid - half, mid + half
        tab.canvas.set_display(
            colormap=params["colormap"],
            brightness=params["brightness"],
            gamma=params["gamma"],
            vmin=vmin,
            vmax=vmax,
            invert=invert,
        )
        self.props.set_histogram(tab.canvas.image, vmin=tab.canvas.vmin, vmax=tab.canvas.vmax)

    def _auto_contrast(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        vmin, vmax = auto_levels(tab.canvas.image)
        tab.canvas.set_display(vmin=vmin, vmax=vmax)
        self.props.set_histogram(tab.canvas.image, vmin=vmin, vmax=vmax)

    def _on_tool(self, name: str, payload: dict) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        img = tab.canvas.image
        px = tab.canvas.pixel_m or 1.0
        if name == "line_profile":
            width = float(payload.get("linewidth") or self.props.profile_width.value() or 1)
            tab.canvas.profile_linewidth = width
            dist, prof = line_profile(img, payload["p0"], payload["p1"], linewidth=width)
            stats = profile_stats(dist, prof)
            self.spectrum.set_line_profile(dist * px * 1e9, prof, stats=stats)
            tab.canvas.add_annotation("profile", payload["p1"][1], payload["p1"][0])
            self.status.setText(self.tr_("status_profile", **stats))
            si = tab.dataset if tab.dataset.kind is DatasetKind.SPECTRUM_IMAGE else self._si_dataset()
            if si is not None and si.data.ndim == 3:
                r0, c0 = int(round(payload["p0"][0])), int(round(payload["p0"][1]))
                r1, c1 = int(round(payload["p1"][0])), int(round(payload["p1"][1]))
                self._last_line_path = ((r0, c0), (r1, c1))
                self._last_line_scan = line_scan(si.data, (r0, c0), (r1, c1))
        elif name == "distance":
            d = distance(payload["p0"], payload["p1"], px)
            label = format_pixel_size(d)
            tab.canvas.add_annotation(label, payload["p1"][1], payload["p1"][0])
            self.status.setText(self.tr_("status_distance", value=label))
        elif name == "angle":
            ang = angle_deg(payload["p0"], payload["vertex"], payload["p1"])
            tab.canvas.add_annotation(f"{ang:.1f}°", payload["vertex"][1], payload["vertex"][0])
            self.status.setText(self.tr_("status_angle", value=f"{ang:.2f}"))
        elif name == "d_spacing":
            result = fft_d_spacing(payload["p0"], payload["p1"], img.shape, float(tab.canvas.pixel_m or 0.0))
            label = format_pixel_size(float(result["d_spacing_m"]))
            tab.canvas.add_annotation(f"d={label}", payload["p1"][1], payload["p1"][0])
            self.status.setText(self.tr_("status_d_spacing", value=label, mode=result["mode"]))
        elif name in {"roi_rect", "roi_ellipse", "roi_polygon"}:
            mask = tab.canvas.roi_mask()
            if mask is not None:
                stats = roi_stats(img, mask)
                area = format_area(area_m2(stats["n"], tab.canvas.pixel_m))
                self.status.setText(self.tr_("status_area", n=int(stats["n"]), mean=stats["mean"], area=area))
                self.props.set_roi_histogram(img, mask)
                if name == "roi_polygon":
                    pts = payload.get("points") or []
                    ax, ay = (pts[-1] if pts else (0.0, 0.0))
                else:
                    ax = float(payload.get("x", 0) + payload.get("w", 0))
                    ay = float(payload.get("y", 0))
                tab.canvas.add_annotation(area, ax, ay)
                if tab.dataset.kind is DatasetKind.SPECTRUM_IMAGE:
                    energy = self._energy_for(tab.dataset)
                    spec = sum_spectrum(tab.dataset.data, mask)
                    bg_method = self.props.bg_eds.currentText()
                    bg = spectrum_background(spec, energy, method=bg_method)
                    self.spectrum.set_spectrum(energy, spec, title="ROI spectrum")
                    self.spectrum.set_background(energy, bg)
                    peaks = identify_peaks(energy, spec, bg_method=bg_method)
                    self.spectrum.add_peak_markers(peaks)
                    self._last_roi_energy = energy
                    self._last_roi_spec = spec

    def _on_process(self, name: str, params: dict) -> None:
        try:
            self._run_process(name, params)
        except Exception as exc:
            QMessageBox.critical(self, self.tr_("error"), str(exc))

    def _run_process(self, name: str, params: dict) -> None:
        tab = self.current_tab()
        if name == "image_calc":
            self._image_calc()
            return
        if name == "dpc":
            self._compute_dpc()
            return
        if name == "eds_selection":
            self._mark_elements(params.get("elements") or [])
            return
        if name in {"identify", "element_maps", "gauss_maps", "overlay", "quantify", "pca", "line_scan"}:
            self._run_eds(name, params)
            return
        if name in {"virtual_bf", "virtual_adf", "virtual_abf", "com"}:
            self._run_4d(name, params)
            return
        if name == "atoms":
            self._run_atoms(params)
            return
        if name == "drift":
            self._run_drift()
            return
        if name == "dcfi":
            self._run_dcfi(params)
            return
        if name == "fft_mask":
            self._update_fft_mask(params)
            return
        if name == "place_fft_mask":
            self._place_fft_mask(params)
            return
        if name == "load_lut":
            self._load_lut()
            return
        if tab is None:
            return
        img = tab.canvas.image
        if name == "gaussian":
            self.undo_stack.push(tab.dataset)
            out = gaussian_filter(img, params.get("sigma", 1.2))
            self._push_image(out, f"{tab.dataset.name} · Gaussian", tab.dataset)
        elif name == "median":
            out = median_filter(img, params.get("size", 3))
            self._push_image(out, f"{tab.dataset.name} · Median", tab.dataset)
        elif name == "wiener":
            out = wiener_filter(img, params.get("size", 5))
            self._push_image(out, f"{tab.dataset.name} · Wiener", tab.dataset)
        elif name == "bg_sub":
            out = subtract_background(
                img,
                method=str(params.get("method") or "average"),
                sigma=params.get("bg_sigma", params.get("sigma", 25)),
                radius=params.get("radius", 25),
                percentile=params.get("percentile", 1.0),
            )
            self._push_image(out, f"{tab.dataset.name} · BG-sub", tab.dataset)
        elif name == "unsharp":
            out = unsharp_mask(img, params.get("sigma", 1.2), params.get("amount", 1.0))
            self._push_image(out, f"{tab.dataset.name} · Unsharp", tab.dataset)
        elif name == "sobel":
            out = sobel_filter(img)
            self._push_image(out, f"{tab.dataset.name} · Sobel", tab.dataset)
        elif name == "highpass":
            out = highpass_filter(img, params.get("bg_sigma", params.get("sigma", 3)))
            self._push_image(out, f"{tab.dataset.name} · High-pass", tab.dataset)
        elif name == "fft":
            self._show_fft(tab)
        elif name == "ifft":
            self._apply_ifft(tab, params)

    def _push_image(self, image: np.ndarray, name: str, proto: Dataset) -> ImageTab:
        ds = Dataset(
            name=name,
            kind=DatasetKind.IMAGE,
            data=np.asarray(image, dtype=np.float64),
            axes=list(proto.axes[-2:]) if len(proto.axes) >= 2 else [],
            metadata=dict(proto.metadata),
            source_path=proto.source_path,
            detector=proto.detector,
        )
        return self.open_dataset(ds)

    def _show_fft(self, tab: ImageTab) -> None:
        spec = fft2d(tab.canvas.image)
        power = power_spectrum(tab.canvas.image, log=True)
        # Suppress the DC peak so Bragg spots stay visible.
        vis = power.copy()
        cy, cx = vis.shape[0] // 2, vis.shape[1] // 2
        vis[max(0, cy - 2) : cy + 3, max(0, cx - 2) : cx + 3] = np.median(vis)
        new = self._push_image(vis, f"{tab.dataset.name} · FFT", tab.dataset)
        new.fft_spectrum = spec
        new.is_fft = True
        vmin, vmax = auto_levels(vis, low=20, high=99.9)
        new.canvas.colormap = "thermal"
        new.canvas.set_display(colormap="thermal", vmin=vmin, vmax=vmax)
        self._fft_source = tab.canvas.image
        new.canvas.place_fft_roi("circle", radius=float(self.props.mask_radius.value()))
        self._update_fft_mask(self.props.fft_params(), tab=new)
        self.status.setText(self.tr_("status_fft"))
        self.props.setCurrentIndex(3)

    def _fft_mask_array(self, tab: ImageTab, params: dict) -> np.ndarray:
        spec = tab.fft_spectrum
        shape = spec.shape[:2] if spec is not None else tab.canvas.image.shape[:2]
        roi = tab.canvas.fft_roi_params()
        center = params.get("center") or (roi["center"] if roi else None)
        width = params.get("width") or (roi["width"] if roi else None)
        height = params.get("height") or (roi["height"] if roi else None)
        mask = make_mask(
            shape,
            kind=params.get("kind", "circle"),
            center=center,
            radius=params.get("radius", 20),
            inner=params.get("inner", 6),
            outer=params.get("outer", 40),
            width=width,
            height=height,
            invert=params.get("invert", False),
        )
        return feather_mask(mask, params.get("soft", 0))

    def _update_fft_mask(self, params: dict, tab: ImageTab | None = None) -> None:
        tab = tab or self.current_tab()
        if tab is None or not getattr(tab, "is_fft", False):
            return
        mask = self._fft_mask_array(tab, params)
        tab.canvas.set_mask_overlay(mask)
        if params.get("live") or self.props.live_ifft.isChecked():
            self._preview_ifft(tab, params)

    def _on_fft_roi(self, tab: ImageTab, payload: dict) -> None:
        if not getattr(tab, "is_fft", False):
            return
        self.props.mask_radius.blockSignals(True)
        try:
            self.props.mask_radius.setValue(float(payload.get("radius") or 20))
        finally:
            self.props.mask_radius.blockSignals(False)
        merged = {**self.props.fft_params(), **payload}
        self._update_fft_mask(merged, tab=tab)

    def _place_fft_mask(self, params: dict) -> None:
        tab = self.current_tab()
        if tab is None or not getattr(tab, "is_fft", False):
            return
        tab.canvas.place_fft_roi(params.get("kind", "circle"), radius=float(params.get("radius") or 20))
        self._update_fft_mask(params, tab=tab)

    def _preview_ifft(self, tab: ImageTab, params: dict) -> None:
        spec = tab.fft_spectrum
        if spec is None:
            spec = fft2d(self._fft_source if self._fft_source is not None else tab.canvas.image)
        rec = reconstruct(
            spec,
            kind=params.get("kind", "circle"),
            center=params.get("center"),
            radius=params.get("radius", 20),
            inner=params.get("inner", 6),
            outer=params.get("outer", 40),
            width=params.get("width"),
            height=params.get("height"),
            invert=params.get("invert", False),
            soft=params.get("soft", 0),
        )
        preview = getattr(self, "_ifft_preview_tab", None)
        if preview is not None and widget_alive(preview):
            preview.canvas.set_image(rec, reset_levels=False)
            return
        self._ifft_preview_tab = self._push_image(rec, f"{tab.dataset.name} · iFFT preview", tab.dataset)

    def _apply_ifft(self, tab: ImageTab, params: dict) -> None:
        spec = tab.fft_spectrum
        if spec is None:
            spec = fft2d(self._fft_source if self._fft_source is not None else tab.canvas.image)
        roi = tab.canvas.fft_roi_params() if getattr(tab, "is_fft", False) else None
        rec = reconstruct(
            spec,
            kind=params.get("kind", "circle"),
            center=params.get("center") or (roi["center"] if roi else None),
            radius=params.get("radius", 20),
            inner=params.get("inner", 6),
            outer=params.get("outer", 40),
            width=params.get("width") or (roi["width"] if roi else None),
            height=params.get("height") or (roi["height"] if roi else None),
            invert=params.get("invert", False),
            soft=params.get("soft", 0),
        )
        self._push_image(rec, f"{tab.dataset.name} · iFFT", tab.dataset)

    def _image_calc(self) -> None:
        datasets = [ds for ds in self.browser.all_datasets() if ds.data.ndim == 2]
        # include open tabs
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, ImageTab) and w.dataset not in datasets and w.canvas.image.ndim == 2:
                datasets.append(
                    Dataset(name=w.dataset.name, kind=DatasetKind.IMAGE, data=w.canvas.image, metadata=w.dataset.metadata)
                )
        dlg = ImageCalculatorDialog(self.tr_, datasets, self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        op, a, b = dlg.selection()
        if a is None:
            return
        out = image_calculate(op, a.image2d(), None if op in {"invert", "normalize"} or b is None else b.image2d())
        self._push_image(out, f"{op}({a.name})", a)

    def _mark_elements(self, symbols: list[str]) -> None:
        if self.spectrum.energy.size == 0:
            return
        peaks = []
        for symbol in symbols:
            for name, e in lines_for(symbol):
                if self.spectrum.energy.min() <= e <= self.spectrum.energy.max():
                    peaks.append({"energy_kev": e, "symbol": symbol, "line": name.split()[-1]})
        self.spectrum.add_peak_markers(peaks)

    def _si_dataset(self) -> Dataset | None:
        tab = self.current_tab()
        if tab and tab.dataset.kind is DatasetKind.SPECTRUM_IMAGE:
            return tab.dataset
        return self._current_si

    def _run_eds(self, name: str, params: dict) -> None:
        si = self._si_dataset()
        if si is None:
            raise RuntimeError(self.tr_("no_spectrum"))
        energy = self._energy_for(si)
        spec = self.spectrum.counts if self.spectrum.counts.size else sum_spectrum(si.data)
        if spec.size != energy.size:
            spec = sum_spectrum(si.data)
            self.spectrum.set_spectrum(energy, spec)
        elements = params.get("elements") or self.props.table.selected_list()
        if name == "identify":
            bg_method = str(params.get("bg_method") or self.props.bg_eds.currentText())
            peaks = identify_peaks(energy, spec, bg_method=bg_method)
            bg = spectrum_background(spec, energy, method=bg_method)
            self.spectrum.set_spectrum(energy, spec)
            self.spectrum.set_background(energy, bg)
            self.spectrum.add_peak_markers(peaks)
            found = [p["symbol"] for p in peaks if p.get("symbol")]
            if found:
                self.props.table.set_selected(list({str(s) for s in found}))
                self.props.refresh_selected()
            els = ", ".join(dict.fromkeys(str(s) for s in found if s)) or "—"
            self.status.setText(self.tr_("status_identify", n=len(peaks), els=els))
        elif name == "pca":
            denoised = pca_denoise(si.data, n_components=int(params.get("components", 8)))
            ds = Dataset(
                name=f"{si.name} · PCA",
                kind=DatasetKind.SPECTRUM_IMAGE,
                data=denoised,
                axes=list(si.axes),
                metadata=dict(si.metadata),
                source_path=si.source_path,
                detector=si.detector,
            )
            self._current_si = ds
            self.open_dataset(ds)
        elif name == "element_maps":
            if not elements:
                elements = ["Au", "Si", "Cu", "C"]
            mode = str(params.get("map_mode") or self.props.map_mode.currentText())
            self._last_maps = make_element_maps(si.data, energy, elements, mode=mode)
            self.mixer.set_maps(self._last_maps)
            for el, mmap in self._last_maps.items():
                self._push_image(mmap, f"{el} map", si)
            self.status.setText(self.tr_("status_maps"))
            self.props.setCurrentIndex(4)
        elif name == "gauss_maps":
            if not elements:
                elements = ["Au", "Si", "Cu", "C"]

            def _fit() -> dict:
                return {el: gaussian_net_map(si.materialize(), energy, el) for el in elements}

            def _done(maps: dict) -> None:
                self._last_maps = maps
                self.mixer.set_maps(maps)
                for el, mmap in maps.items():
                    self._push_image(mmap, f"{el} net", si)
                self.status.setText(self.tr_("status_maps"))

            run_in_background(self, self.tr_("working"), _fit, on_done=_done, on_fail=lambda m: QMessageBox.critical(self, self.tr_("error"), m))
        elif name == "overlay":
            if not self._last_maps:
                if not elements:
                    elements = ["Au", "Si", "Cu"]
                self._last_maps = {el: element_map(si.data, energy, el) for el in elements}
            rgb = color_overlay(self._last_maps)
            # store as float gray-ish? show RGB by putting channels... canvas expects 2D.
            # Convert to a display-ready luminance plus keep RGB via a special push
            ds = Dataset(
                name="EDS overlay",
                kind=DatasetKind.IMAGE,
                data=np.asarray(rgb, dtype=np.float64).mean(axis=-1),
                metadata=dict(si.metadata),
                source_path=si.source_path,
            )
            tab = self.open_dataset(ds)
            tab.canvas.item.setImage(rgb, autoLevels=False)
            self.mixer.set_maps(self._last_maps)
        elif name == "quantify":
            if not elements:
                elements = ["Au", "Si", "Cu", "C"]
            bg_method = str(params.get("bg_method") or self.props.bg_eds.currentText())
            intensities = integrate_windows(spec, energy, elements, bg_method=bg_method)
            bg = spectrum_background(spec, energy, method=bg_method)
            self.spectrum.set_background(energy, bg)
            kf = params.get("k_factors") or self.props.k_factors()
            if params.get("absorption"):
                self.quant_rows = cliff_lorimer_abs(
                    intensities,
                    k_factors=kf,
                    thickness_nm=float(params.get("thickness_nm") or 0),
                    density_g_cm3=float(params.get("density") or 5),
                    takeoff_rad=float(si.metadata.get("takeoff_rad") or 0.35),
                )
            else:
                self.quant_rows = cliff_lorimer(intensities, k_factors=kf)
            self.props.set_quant_rows(self.quant_rows)
            self.props.setCurrentIndex(4)
            self.props.refresh_selected()
            summary = ", ".join(
                f"{r.get('element', '?')} {float(r.get('atomic_percent') or 0):.1f} at.%"
                for r in self.quant_rows
            )
            self.status.setText(self.tr_("status_quant", summary=summary or "—"))
        elif name == "line_scan":
            h, w = si.data.shape[:2]
            if self._last_line_path is not None:
                p0, p1 = self._last_line_path
            else:
                p0, p1 = (h // 2, 0), (h // 2, max(w - 1, 0))
            scan = line_scan(si.data, p0, p1)
            self._last_line_scan = scan
            self._last_line_path = (p0, p1)
            self._push_image(scan, f"{si.name} · line scan", si)
            if elements:
                prof = line_scan_element_profile(
                    scan, energy, str(elements[0]), bg_method=str(params.get("bg_method") or "snip")
                )
                self.spectrum.set_line_profile(np.arange(prof.size, dtype=np.float64), prof)
            else:
                self.spectrum.set_spectrum(energy, scan.sum(axis=0), title="Line-scan sum")
            self.status.setText(self.tr_("status_line_scan", n=int(scan.shape[0])))

    def _compute_dpc(self) -> None:
        names = self.browser.datasets_by_name()
        quads = {}
        for key in ("DF4-A", "DF4-B", "DF4-C", "DF4-D"):
            if key in names:
                quads[key] = names[key].image2d()
        if len(quads) < 4:
            ds4 = None
            for cand in self.browser.all_datasets():
                if cand.kind is DatasetKind.FOUR_D:
                    ds4 = cand
                    break
            if ds4 is None:
                raise RuntimeError("Open a dataset that contains DF4-A/B/C/D segmented images.")
            params = self.props.stem_params()
            dx, dy = center_of_mass_dpc(ds4.data)
            dx, dy = apply_diffraction_cal(
                dx, dy, rotation_deg=float(params.get("rotation_deg") or 0), q_per_px=params.get("q_per_px") or None
            )
            proto = ds4
        else:
            dx, dy = dpc_from_quadrants(quads)
            proto = names["DF4-A"]
        self._push_image(dx, "DPC X", proto)
        self._push_image(dy, "DPC Y", proto)
        self._push_image(idpc(dx, dy), "iDPC", proto)
        self._push_image(ddpc(dx, dy), "dDPC", proto)
        color = dpc_color(dx, dy)
        tab = self._push_image(np.hypot(dx, dy), "DPC vector", proto)
        tab.canvas.item.setImage(color, autoLevels=False)
        self.status.setText(self.tr_("status_dpc"))

    def _run_4d(self, name: str, params: dict) -> None:
        tab = self.current_tab()
        ds = tab.dataset if tab and tab.dataset.kind is DatasetKind.FOUR_D else None
        if ds is None:
            for cand in self.browser.all_datasets():
                if cand.kind is DatasetKind.FOUR_D:
                    ds = cand
                    break
        if ds is None:
            raise RuntimeError("No 4D-STEM dataset is open.")
        params = dict(params or {})
        unit = str(params.get("unit") or "px")
        qpp = float(params.get("q_per_px") or 0.0)
        cl = params.get("camera_length_m")
        det_px = params.get("detector_pixel_m") or ds.pixel_size_m()
        hv = float(ds.metadata.get("high_tension_v") or 0.0)
        if qpp <= 0 and cl and det_px and hv:
            qpp = q_per_px_inv_angstrom(
                camera_length_m=float(cl),
                detector_pixel_m=float(det_px),
                wavelength_m=electron_wavelength_m(hv),
            )
            self.props.q_per_px.setValue(qpp)
        def _r(key: str, default: float) -> float:
            return radius_to_pixels(
                float(params.get(key, default) or default),
                unit,
                q_per_px=qpp or None,
                camera_length_m=cl,
                detector_pixel_m=det_px,
            )
        if name == "virtual_bf":
            img = virtual_bf(ds.data, radius=_r("radius", 4.0))
            self._push_image(img, "Virtual BF", ds)
        elif name == "virtual_adf":
            img = virtual_adf(ds.data, inner=_r("inner", 5.0), outer=_r("outer", 11.0))
            self._push_image(img, "Virtual ADF", ds)
        elif name == "virtual_abf":
            img = virtual_abf(ds.data, inner=_r("abf_inner", 2.0), outer=_r("abf_outer", 3.5))
            self._push_image(img, "Virtual ABF", ds)
            self.status.setText(self.tr_("status_abf"))
        elif name == "com":
            cx, cy = center_of_mass_dpc(ds.data)
            cx, cy = apply_diffraction_cal(
                cx, cy, rotation_deg=float(params.get("rotation_deg") or 0), q_per_px=qpp or None
            )
            self._push_image(cx, "CoM DPC X", ds)
            self._push_image(cy, "CoM DPC Y", ds)
            self._push_image(idpc(cx, cy), "CoM iDPC", ds)
            self._push_image(ddpc(cx, cy), "CoM dDPC", ds)
        ds.metadata["diffraction"] = self.props.diffraction_params()
        if qpp:
            self.status.setText(self.tr_("status_cal", q=f"{qpp:.4g}"))

    def _run_atoms(self, params: dict) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        coords = find_atom_columns(
            tab.canvas.image,
            sigma=params.get("sigma", 1.2),
            min_distance=int(params.get("min_distance", 6)),
        )
        if coords.size:
            tab.canvas.show_points(coords[:, 0], coords[:, 1], color=(0, 200, 255, 180))
        self.status.setText(self.tr_("status_atoms", n=int(coords.shape[0])))

    def _run_drift(self) -> None:
        tab = self.current_tab()
        ds = tab.dataset if tab else None
        if ds is None or ds.kind is not DatasetKind.STACK:
            for cand in self.browser.all_datasets():
                if cand.kind is DatasetKind.STACK:
                    ds = cand
                    break
        if ds is None or ds.kind is not DatasetKind.STACK:
            raise RuntimeError("No image series / stack is open.")
        aligned, summed, _shifts = align_and_sum(ds.data)
        self._push_image(summed, f"{ds.name} · aligned sum", ds)
        stack_ds = Dataset(
            name=f"{ds.name} · aligned",
            kind=DatasetKind.STACK,
            data=aligned,
            axes=list(ds.axes),
            metadata=dict(ds.metadata),
            source_path=ds.source_path,
        )
        self.open_dataset(stack_ds)
        self.status.setText(self.tr_("status_align", n=aligned.shape[0]))

    def _run_dcfi(self, params: dict | None = None) -> None:
        tab = self.current_tab()
        ds = tab.dataset if tab else None
        if ds is None or ds.kind is not DatasetKind.STACK:
            for cand in self.browser.all_datasets():
                if cand.kind is DatasetKind.STACK:
                    ds = cand
                    break
        if ds is None or ds.kind is not DatasetKind.STACK:
            raise RuntimeError("No image series / stack is open.")
        params = params or self.props.dcfi_params()
        result = dcfi(
            ds.data,
            reference=str(params.get("reference") or "first"),
            reduce=str(params.get("reduce") or "mean"),
            highpass_sigma=float(params.get("highpass_sigma") or 0),
            max_shift=params.get("max_shift"),
            crop=bool(params.get("crop", True)),
        )
        self._push_image(result.integrated, f"{ds.name} · DCFI", ds)
        stack_ds = Dataset(
            name=f"{ds.name} · DCFI aligned",
            kind=DatasetKind.STACK,
            data=result.aligned,
            axes=list(ds.axes),
            metadata=dict(ds.metadata),
            source_path=ds.source_path,
        )
        self.open_dataset(stack_ds)
        mag = np.hypot(result.shifts[:, 0], result.shifts[:, 1])
        self.spectrum.set_line_profile(np.arange(mag.size, dtype=np.float64), mag)
        self.status.setText(
            self.tr_("status_dcfi", n=int(result.used.sum()), rms=result.residual_rms)
        )

    def _load_lut(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr_("load_lut"), "", "LUT (*.lut *.csv *.txt);;All files (*)")
        if not path:
            return
        lut = load_lut(path)
        name = Path(path).stem
        register_lut(name, lut)
        self.props.add_lut_name(name)
        tab = self.current_tab()
        if tab is not None:
            tab.canvas.set_display(colormap=name)

    def export_current_image(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_image"), "image.png", "PNG (*.png);;TIFF (*.tif)")
        if not path:
            return
        export_image(path, tab.canvas.image, **self._export_image_kwargs(tab))

    def export_report_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr_("export_report"),
            "report.pdf",
            "PDF (*.pdf);;HTML (*.html);;PowerPoint (*.pptx)",
        )
        if not path:
            return
        dest = export_report(path, self.report_model())
        self.status.setText(self.tr_("status_report", path=str(dest)))

    def report_model(self) -> dict:
        images: list[tuple[str, np.ndarray]] = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, ImageTab):
                images.append((w.dataset.display_name(), w.canvas.image))
            elif isinstance(w, MultiPanelView):
                for panel in w.panels():
                    images.append((panel.dataset.display_name(), panel.canvas.image))
        meta_lines = []
        tab = self.current_tab()
        if tab is not None:
            m = tab.dataset.metadata or {}
            meta_lines = [
                f"{tab.dataset.display_name()}  {tab.dataset.kind.value}",
                f"HV {m.get('high_tension_v', '—')}  pixel {tab.canvas.pixel_m}",
            ]
        spec = None
        if self.spectrum.energy.size and self.spectrum.counts.size:
            spec = (self.spectrum.energy, self.spectrum.counts)
        return {
            "title": "OpenVelox report",
            "subtitle": self.windowTitle(),
            "images": images[:8],
            "spectrum": spec,
            "quant": list(self.quant_rows),
            "metadata": meta_lines,
        }

    def export_current_overlay(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_overlay"), "overlay.png", "PNG (*.png);;TIFF (*.tif)")
        if not path:
            return
        kwargs = self._export_image_kwargs(tab)
        kwargs.pop("scale_bar", None)
        export_overlay(path, tab.canvas.image, **kwargs)

    def export_current_spectrum(self) -> None:
        if self.spectrum.energy.size == 0:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_spectrum"), "spectrum.csv", "CSV (*.csv)")
        if path:
            export_spectrum_csv(path, self.spectrum.energy, self.spectrum.counts)

    def export_current_map(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_map"), "map.csv", "CSV (*.csv)")
        if path:
            from openvelox.io.writers import export_map_csv

            export_map_csv(path, tab.canvas.image, tab.dataset.name)

    def export_quant(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_quant"), "quantification.csv", "CSV (*.csv)")
        if path:
            export_quant_table(path, self.quant_rows)

    def export_roi_spectrum(self) -> None:
        if self._last_roi_energy is None or self._last_roi_spec is None:
            if self.spectrum.energy.size:
                self.export_current_spectrum()
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_roi"), "roi_spectrum.csv", "CSV (*.csv)")
        if path:
            export_spectrum_csv(path, self._last_roi_energy, self._last_roi_spec)

    def export_line_scan(self) -> None:
        if self._last_line_scan is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("export_linescan"), "linescan.csv", "CSV (*.csv)")
        if path:
            si = self._si_dataset()
            energy = self._energy_for(si) if si is not None else np.arange(self._last_line_scan.shape[-1])
            export_line_scan_csv(path, energy, self._last_line_scan)

    def batch_export(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, self.tr_("batch_export"))
        if not directory:
            return
        items: list[tuple[str, np.ndarray, dict]] = []
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if not isinstance(widget, ImageTab):
                continue
            items.append(
                (
                    widget.dataset.display_name(),
                    widget.canvas.image,
                    self._export_image_kwargs(widget),
                )
            )
        written = batch_export_images(directory, items)
        self.status.setText(self.tr_("status_batch", n=len(written)))

    def _on_profile_width(self, value: int) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.canvas.profile_linewidth = float(value)

    def _on_scale_bar(self, params: dict) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.canvas.set_scale_bar_style(ScaleBarStyle.from_mapping(params))

    def _export_image_kwargs(self, tab: ImageTab) -> dict:
        return {
            "pixel_m": tab.canvas.pixel_m,
            "colormap": tab.canvas.colormap,
            "vmin": tab.canvas.vmin,
            "vmax": tab.canvas.vmax,
            "gamma": tab.canvas.gamma,
            "brightness": tab.canvas.brightness,
            "invert": bool(tab.canvas.invert),
            "scale_bar": True,
            "scale_bar_style": tab.canvas.scale_bar_style,
            "annotations": tab.canvas.collect_annotations(),
            "title": tab.dataset.display_name(),
        }

    def _rebuild_recent(self) -> None:
        menu = getattr(self, "_recent_menu", None)
        if menu is None:
            return
        menu.clear()
        items = recent_files()
        if not items:
            empty = QAction(self.tr_("empty_browser"), self)
            empty.setEnabled(False)
            menu.addAction(empty)
            return
        for path in items:
            act = QAction(Path(path).name, self)
            act.setToolTip(path)
            safe = wrap_slot(lambda p=path: self.load_path(p))
            act.triggered.connect(lambda _checked=False, s=safe: s())
            menu.addAction(act)

    def _clear_recent(self) -> None:
        clear_recent()
        self._rebuild_recent()

    def open_dropped_paths(self, paths: list[str]) -> None:
        for path in paths:
            if path:
                self.load_path(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime is None:
            return
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        self.open_dropped_paths(paths)
        event.acceptProposedAction()

    def chrome_payload(self) -> dict:
        return {
            "geometry": bytes(self.saveGeometry().toHex()).decode("ascii"),
            "docks": bytes(self.saveState().toHex()).decode("ascii"),
            "language": self.tr_.lang,
        }

    def save_chrome(self) -> None:
        try:
            save_prefs(self.chrome_payload())
        except Exception as exc:  # noqa: BLE001
            report_exception(exc, where="save chrome")

    def restore_chrome(self, data: dict | None = None) -> bool:
        payload = data if data is not None else load_prefs()
        ok = False
        try:
            if payload.get("geometry"):
                ok = bool(self.restoreGeometry(bytes.fromhex(str(payload["geometry"])))) or ok
            if payload.get("docks"):
                ok = bool(self.restoreState(bytes.fromhex(str(payload["docks"])))) or ok
        except Exception:
            return False
        return ok

    def reset_layout(self) -> None:
        self.resize(1480, 920)
        for key, area in (
            ("experiment", Qt.DockWidgetArea.LeftDockWidgetArea),
            ("properties", Qt.DockWidgetArea.RightDockWidgetArea),
            ("layers", Qt.DockWidgetArea.RightDockWidgetArea),
            ("spectrum", Qt.DockWidgetArea.BottomDockWidgetArea),
        ):
            dock = self._docks.get(key)
            if dock is not None:
                self.addDockWidget(area, dock)
                dock.show()
        self.tabifyDockWidget(self._docks["properties"], self._docks["layers"])
        self._docks["properties"].raise_()

    def closeEvent(self, event) -> None:  # noqa: N802
        if _persist_chrome():
            self.save_chrome()
        super().closeEvent(event)

    def save_session_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.tr_("save_session"), "session.openvelox.json", "JSON (*.json)")
        if not path:
            return
        save_session(path, self.session_payload())
        self.status.setText(self.tr_("session_saved"))

    def session_payload(self) -> dict:
        tiles: list[dict] = []
        current = self.tabs.currentWidget()
        if isinstance(current, MultiPanelView):
            tiles = [dataset_ref(p.dataset) for p in current.panels()]
        tabs = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, ImageTab):
                tabs.append(dataset_ref(w.dataset))
        return {
            "files": list(self._open_paths),
            "language": self.tr_.lang,
            "k_factors": self.props.k_factors(),
            "geometry": bytes(self.saveGeometry().toHex()).decode("ascii"),
            "docks": bytes(self.saveState().toHex()).decode("ascii"),
            "layout": self._layout_key,
            "sync_views": bool(self._sync_views),
            "tabs": tabs,
            "tiles": tiles,
            "diffraction": self.props.diffraction_params(),
        }

    def _match_dataset(self, ref: dict) -> Dataset | None:
        name = str(ref.get("name") or "")
        path = str(ref.get("source_path") or "")
        kind = str(ref.get("kind") or "")
        for ds in self.browser.all_datasets():
            if name and ds.name != name:
                continue
            if path and ds.source_path and str(ds.source_path) != path:
                continue
            if kind and ds.kind.value != kind:
                continue
            return ds
        if name:
            for ds in self.browser.all_datasets():
                if ds.name == name:
                    return ds
        return None

    def load_session_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr_("load_session"), "", "JSON (*.json)")
        if path:
            self.load_session_file(path)

    def load_session_file(self, path: str | Path) -> None:
        data = load_session(path)
        if data.get("language"):
            self.tr_.set_language(str(data["language"]))
        if data.get("k_factors"):
            self.props.set_k_rows({str(k): float(v) for k, v in data["k_factors"].items()})
        for file_path in data.get("files") or []:
            if Path(file_path).is_file():
                try:
                    self.load_path(file_path)
                except Exception as exc:  # noqa: BLE001
                    report_exception(exc, where=f"session {file_path}")
        try:
            if data.get("geometry"):
                self.restoreGeometry(bytes.fromhex(str(data["geometry"])))
            if data.get("docks"):
                self.restoreState(bytes.fromhex(str(data["docks"])))
        except Exception:
            pass
        if data.get("diffraction"):
            self.props.set_diffraction_controls(data["diffraction"])
        if data.get("sync_views"):
            act = self._actions.get("sync_views")
            if act is not None:
                act.setChecked(True)
            self._toggle_sync(True)
        layout = str(data.get("layout") or "1x1")
        tile_refs = list(data.get("tiles") or [])
        if layout and layout != "1x1" and tile_refs:
            datasets = [ds for ds in (self._match_dataset(ref) for ref in tile_refs) if ds is not None]
            if datasets:
                self.apply_layout(layout, datasets=datasets)
        self.status.setText(self.tr_("session_loaded", n=len(data.get("files") or [])))

    def _on_mix(self, rgb: np.ndarray) -> None:
        tab = self.current_tab()
        if tab is None or not widget_alive(tab):
            return
        if "overlay" not in tab.dataset.name.lower() and "mix" not in tab.dataset.name.lower():
            return
        if widget_alive(tab.canvas.item):
            tab.canvas.item.setImage(rgb, autoLevels=False)

    def _datasets_for_layout(self, n: int) -> list[Dataset]:
        seen: list[Dataset] = []

        def add(ds: Dataset | None) -> None:
            if ds is not None and ds not in seen:
                seen.append(ds)

        tab = self.current_tab()
        if tab is not None:
            add(tab.dataset)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, ImageTab):
                add(w.dataset)
            elif isinstance(w, MultiPanelView):
                for panel in w.panels():
                    add(panel.dataset)
        for ds in self.browser.all_datasets():
            add(ds)
            if len(seen) >= n:
                break
        return seen[:n]

    def apply_layout(self, key: str, datasets: list[Dataset] | None = None) -> MultiPanelView | None:
        rows, cols = layout_shape(key)
        n = rows * cols
        self._layout_key = key
        act = self._actions.get(f"layout_{key}")
        if act is not None:
            act.setChecked(True)
        if n <= 1:
            self.status.setText(self.tr_("status_layout", layout=key))
            return None
        datasets = datasets if datasets else self._datasets_for_layout(n)
        current = self.tabs.currentWidget()
        if isinstance(current, MultiPanelView):
            view = current
            stale = list(view.panels())
            view._tabs = []
            for old in stale:
                try:
                    old.setParent(None)
                    old.canvas.teardown()
                    old.deleteLater()
                except RuntimeError:
                    pass
            try:
                view.panelActivated.disconnect(self._on_panel)
            except (RuntimeError, TypeError):
                pass
            view.rebuild(key)
        else:
            view = MultiPanelView(self.tr_, layout=key)
            self.tabs.addTab(view, key.replace("x", " × "))
            self.tabs.setCurrentWidget(view)
        tabs = []
        for ds in datasets:
            panel = ImageTab(ds)
            self._wire_tab(panel)
            tabs.append(panel)
        view.set_tabs(tabs)
        view.set_linked(self._sync_views)
        view.panelActivated.connect(self._on_panel)
        self._tiled_tabs = view.panels()
        self._multi = view
        self.status.setText(self.tr_("status_layout", layout=key))
        return view

    def _tile_views(self) -> None:
        if len(self._datasets_for_layout(4)) < 2:
            self.status.setText(self.tr_("tile"))
            return
        self.apply_layout("2x2")

    def _on_view_sync(self, src: ImageTab) -> None:
        if not self._sync_views or not widget_alive(src):
            return
        current = self.tabs.currentWidget()
        if isinstance(current, MultiPanelView) and current.is_linked():
            return
        peers = getattr(self, "_tiled_tabs", None) or [
            self.tabs.widget(i) for i in range(self.tabs.count()) if isinstance(self.tabs.widget(i), ImageTab)
        ]
        for dst in peers:
            if dst is src or not isinstance(dst, ImageTab) or not widget_alive(dst):
                continue
            self._mirror_range(src, dst)

    def _mirror_range(self, src: ImageTab, dst: ImageTab) -> None:
        if not widget_alive(src) or not widget_alive(dst):
            return
        mirror_view(src.canvas, dst.canvas)

    def _toggle_sync(self, on: bool = True) -> None:
        self._sync_views = bool(on)
        current = self.tabs.currentWidget()
        if isinstance(current, MultiPanelView):
            current.set_linked(self._sync_views)
        if self._multi is not None and self._multi is not current:
            try:
                self._multi.set_linked(self._sync_views)
            except RuntimeError:
                self._multi = None

    def _undo(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        snap = self.undo_stack.undo(tab.dataset)
        if snap is None:
            return
        tab.dataset.data = snap.data
        tab.dataset.name = snap.name
        tab.canvas.set_image(np.asarray(snap.data, dtype=np.float64) if np.asarray(snap.data).ndim == 2 else tab.dataset.image2d(), reset_levels=True)
        self.props.set_histogram(tab.canvas.image)

    def _redo(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        snap = self.undo_stack.redo(tab.dataset)
        if snap is None:
            return
        tab.dataset.data = snap.data
        tab.canvas.set_image(tab.dataset.image2d(), reset_levels=True)
        self.props.set_histogram(tab.canvas.image)

    def _about(self) -> None:
        QMessageBox.about(self, self.tr_("about"), f"OpenVelox {__version__}\n\n{self.tr_('about_text')}")

    def capture_screenshots(self, directory: str | Path) -> list[Path]:
        """Headless-friendly grabs of the README gallery views."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        self.resize(1600, 980)
        QApplication.processEvents()

        def grab(name: str) -> Path:
            QApplication.processEvents()
            path = directory / name
            self.grab().save(str(path))
            saved.append(path)
            return path

        haadf = next((ds for ds in self.browser.all_datasets() if ds.name == "HAADF"), None)
        if haadf is not None:
            self.open_dataset(haadf)
            self.props.setCurrentIndex(0)
            self._docks["properties"].raise_()
        grab("main_window.png")

        if haadf is not None:
            tab = self.open_dataset(haadf)
            image = tab.canvas.image
            h, w = image.shape[:2]
            tab.canvas.simulate_tool("distance", (8, 8), (max(w - 8, 9), max(h // 3, 9)))
            tab.canvas.simulate_tool("angle", (10, max(h - 10, 2)), (max(w // 2, 4), max(h // 2, 4)), (max(w - 10, 6), max(h - 8, 4)))
            tab.canvas.simulate_tool("roi_rect", (6, 6), (max(w // 3, 8), max(h // 3, 8)))
            self.props.setCurrentIndex(1)
            self._docks["properties"].raise_()
            grab("measurements.png")

            self.apply_layout("2x2")
            act = self._actions.get("sync_views")
            if act is not None:
                act.setChecked(True)
            self._toggle_sync(True)
            grab("multi_panel.png")

            tab = self.open_dataset(haadf)
            self._show_fft(tab)
            self.props.setCurrentIndex(3)
            self._docks["properties"].raise_()
            self.props.mask_kind.setCurrentText("annulus")
            self.props.mask_inner.setValue(4)
            self.props.mask_outer.setValue(18)
            self._update_fft_mask(self.props.fft_params())
            grab("fft_view.png")
            grab("fft_mask.png")

        stack = next((ds for ds in self.browser.all_datasets() if ds.kind is DatasetKind.STACK), None)
        if stack is not None:
            self.open_dataset(stack)
            self.props.setCurrentIndex(8)
            self._docks["properties"].raise_()
            self._run_dcfi(self.props.dcfi_params())
            grab("dcfi.png")

        si = next((ds for ds in self.browser.all_datasets() if ds.kind is DatasetKind.SPECTRUM_IMAGE), None)
        if si is not None:
            self.open_dataset(si)
            self.props.table.set_selected(["Au", "Si", "Cu", "C"])
            self._run_eds("identify", {"elements": ["Au", "Si", "Cu", "C"]})
            self._run_eds("element_maps", {"elements": ["Au", "Si", "Cu"]})
            self._run_eds("overlay", {"elements": ["Au", "Si", "Cu"]})
            self._run_eds("quantify", {"elements": ["Au", "Si", "Cu", "C"], "absorption": True, "thickness_nm": 40})
            self.props.setCurrentIndex(4)
            self._docks["properties"].raise_()
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if isinstance(w, ImageTab) and w.dataset.name.startswith("Au map"):
                    self.tabs.setCurrentWidget(w)
                    break
            grab("eds_mapping.png")
            grab("eds_quant.png")
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if isinstance(w, ImageTab) and "overlay" in w.dataset.name.lower():
                    self.tabs.setCurrentWidget(w)
                    break
            self._docks["layers"].raise_()
            grab("overlay_mixer.png")

        four = next((ds for ds in self.browser.all_datasets() if ds.kind is DatasetKind.FOUR_D), None)
        if four is not None:
            self.open_dataset(four)
            self.props.setCurrentIndex(6)
            self._docks["properties"].raise_()
            self._run_4d("virtual_bf", self.props.stem_params())
            self._run_4d("virtual_adf", self.props.stem_params())
            self._run_4d("virtual_abf", self.props.stem_params())
            grab("stem4d.png")
        return saved


def schedule_screenshots(window: MainWindow, directory: str | Path) -> None:
    def _go() -> None:
        window.capture_screenshots(directory)
        QApplication.instance().quit()

    QTimer.singleShot(400, _go)
