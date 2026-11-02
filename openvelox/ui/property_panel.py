"""Right-hand property / processing panel."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from openvelox.processing.measure import intensity_histogram
from openvelox.processing.scalebar import ScaleBarStyle

from openvelox.io.metadata import acquisition_sections, format_dwell, format_hv, format_pixel_size
from openvelox.models import Dataset, ExperimentFile
from openvelox.processing.display import lut_names
from openvelox.ui.periodic_table import PeriodicTable


def _scroll(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    return area


_SB_COLORS = (("sb_white", "#FFFFFF"), ("sb_black", "#000000"), ("sb_cyan", "#00A3E0"), ("sb_yellow", "#F4C542"))
_SB_POSITIONS = ("bottom_left", "bottom_right", "top_left", "top_right")
_SB_LENGTHS = (
    ("1 nm", 1e-9),
    ("2 nm", 2e-9),
    ("5 nm", 5e-9),
    ("10 nm", 1e-8),
    ("20 nm", 2e-8),
    ("50 nm", 5e-8),
    ("100 nm", 1e-7),
    ("200 nm", 2e-7),
    ("500 nm", 5e-7),
    ("1 µm", 1e-6),
    ("2 µm", 2e-6),
    ("5 µm", 5e-6),
)


class PropertyPanel(QTabWidget):
    displayChanged = Signal(dict)
    autoContrast = Signal()
    processRequested = Signal(str, dict)
    scaleBarChanged = Signal(dict)

    def __init__(self, translator, parent=None) -> None:
        super().__init__(parent)
        self.tr_ = translator
        self._build()

    def _build(self) -> None:
        info = QWidget()
        ilay = QVBoxLayout(info)
        ilay.setContentsMargins(4, 4, 4, 4)
        ilay.setSpacing(4)
        self.meta_filter = QLineEdit()
        self.meta_filter.setPlaceholderText(self.tr_("search_metadata"))
        self.meta_filter.setClearButtonEnabled(True)
        self.meta_filter.textChanged.connect(self._filter_metadata)
        self.meta_tree = QTreeWidget()
        self.meta_tree.setColumnCount(2)
        self.meta_tree.setHeaderLabels([self.tr_("property"), self.tr_("value")])
        self.meta_tree.setAlternatingRowColors(True)
        self.meta_tree.setRootIsDecorated(True)
        self.meta_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.meta_tree.header().setStretchLastSection(True)
        self.info = QTextEdit()
        self.info.setReadOnly(True)
        self.info.setMaximumHeight(0)
        self.info.hide()
        ilay.addWidget(self.meta_filter)
        ilay.addWidget(self.meta_tree, 1)
        ilay.addWidget(self.info)
        self.addTab(info, self.tr_("info"))

        display = QWidget()
        dlay = QVBoxLayout(display)
        self.cmap = QComboBox()
        self.cmap.addItems(lut_names())
        self.cmap.currentTextChanged.connect(lambda _: self._emit_display())
        form = QFormLayout()
        form.addRow(self.tr_("colormap"), self.cmap)
        self.s_bright = self._slider_row("brightness", 10, 250, 100)
        self.s_contrast = self._slider_row("contrast", 10, 250, 100)
        self.s_gamma = self._slider_row("gamma", 20, 300, 100)
        form.addRow(self.tr_("brightness"), self.s_bright)
        form.addRow(self.tr_("contrast"), self.s_contrast)
        form.addRow(self.tr_("gamma"), self.s_gamma)
        self.invert_lut = QCheckBox(self.tr_("invert_lut"))
        self.invert_lut.toggled.connect(lambda _: self._emit_display())
        form.addRow(self.invert_lut)
        dlay.addLayout(form)
        auto = QPushButton(self.tr_("auto_contrast"))
        auto.clicked.connect(self.autoContrast.emit)
        dlay.addWidget(auto)
        load_lut = QPushButton(self.tr_("load_lut"))
        load_lut.clicked.connect(lambda: self.processRequested.emit("load_lut", {}))
        dlay.addWidget(load_lut)
        self._load_lut_btn = load_lut
        self.hist = pg.PlotWidget()
        self.hist.setBackground("#1A1E22")
        self.hist.setFixedHeight(140)
        self.hist.hideAxis("left")
        self.hist_curve = self.hist.plot(pen=pg.mkPen("#00A3E0"))
        self.hist_region = pg.LinearRegionItem(values=(0.0, 1.0), brush=(0, 163, 224, 40))
        self.hist_region.sigRegionChangeFinished.connect(self._on_hist_region)
        self.hist.addItem(self.hist_region)
        self._hist_guard = False
        dlay.addWidget(QLabel(self.tr_("histogram")))
        dlay.addWidget(self.hist)
        self._roi_hist_label = QLabel(self.tr_("roi_histogram"))
        self.roi_hist = pg.PlotWidget()
        self.roi_hist.setBackground("#1A1E22")
        self.roi_hist.setFixedHeight(110)
        self.roi_hist.hideAxis("left")
        self.roi_hist_curve = self.roi_hist.plot(pen=pg.mkPen("#7CDB6A"))
        dlay.addWidget(self._roi_hist_label)
        dlay.addWidget(self.roi_hist)
        self._scale_box = QGroupBox(self.tr_("scale_bar"))
        sform = QFormLayout(self._scale_box)
        self.sb_visible = QCheckBox(self.tr_("scale_bar_visible"))
        self.sb_visible.setChecked(True)
        self.sb_color = QComboBox()
        for key, hexv in _SB_COLORS:
            self.sb_color.addItem(self.tr_(key), hexv)
        self.sb_position = QComboBox()
        for key in _SB_POSITIONS:
            self.sb_position.addItem(self.tr_(key), key)
        self.sb_font = QSpinBox()
        self.sb_font.setRange(6, 28)
        self.sb_font.setValue(9)
        self.sb_thick = QSpinBox()
        self.sb_thick.setRange(1, 16)
        self.sb_thick.setValue(4)
        self.sb_length = QComboBox()
        self.sb_length.addItem(self.tr_("auto"), None)
        for label, meters in _SB_LENGTHS:
            self.sb_length.addItem(label, meters)
        sform.addRow(self.sb_visible)
        sform.addRow(self.tr_("scale_bar_color"), self.sb_color)
        sform.addRow(self.tr_("position"), self.sb_position)
        sform.addRow(self.tr_("scale_bar_font"), self.sb_font)
        sform.addRow(self.tr_("scale_bar_thickness"), self.sb_thick)
        sform.addRow(self.tr_("scale_bar_length"), self.sb_length)
        self._sb_guard = False
        self.sb_visible.toggled.connect(lambda *_: self._emit_scale_bar())
        self.sb_color.currentIndexChanged.connect(lambda *_: self._emit_scale_bar())
        self.sb_position.currentIndexChanged.connect(lambda *_: self._emit_scale_bar())
        self.sb_font.valueChanged.connect(lambda *_: self._emit_scale_bar())
        self.sb_thick.valueChanged.connect(lambda *_: self._emit_scale_bar())
        self.sb_length.currentIndexChanged.connect(lambda *_: self._emit_scale_bar())
        dlay.addWidget(self._scale_box)
        dlay.addStretch(1)
        self.addTab(display, self.tr_("display"))
        self._auto_btn = auto

        proc = QWidget()
        play = QVBoxLayout(proc)
        self.sigma = QDoubleSpinBox()
        self.sigma.setRange(0.1, 80)
        self.sigma.setValue(1.2)
        self.median_size = QSpinBox()
        self.median_size.setRange(1, 21)
        self.median_size.setValue(3)
        self.bg_sigma = QDoubleSpinBox()
        self.bg_sigma.setRange(1, 200)
        self.bg_sigma.setValue(25)
        self.profile_width = QSpinBox()
        self.profile_width.setRange(1, 31)
        self.profile_width.setValue(1)
        pf = QFormLayout()
        self.bg_method = QComboBox()
        self.bg_method.addItems(["average", "rolling_ball", "plane", "constant"])
        self.bg_radius = QDoubleSpinBox()
        self.bg_radius.setRange(1, 400)
        self.bg_radius.setValue(25)
        self.bg_percentile = QDoubleSpinBox()
        self.bg_percentile.setRange(0, 50)
        self.bg_percentile.setValue(1.0)
        pf.addRow(self.tr_("sigma"), self.sigma)
        pf.addRow(self.tr_("median_size"), self.median_size)
        pf.addRow(self.tr_("bg_method"), self.bg_method)
        pf.addRow(self.tr_("bg_sigma"), self.bg_sigma)
        pf.addRow(self.tr_("rolling_radius"), self.bg_radius)
        pf.addRow(self.tr_("bg_percentile"), self.bg_percentile)
        pf.addRow(self.tr_("profile_width"), self.profile_width)
        play.addLayout(pf)
        for key, label in (
            ("gaussian", "gaussian"),
            ("median", "median"),
            ("wiener", "wiener"),
            ("bg_sub", "bg_sub"),
            ("unsharp", "unsharp"),
            ("sobel", "sobel"),
            ("highpass", "highpass"),
        ):
            btn = QPushButton(self.tr_(label))
            btn.clicked.connect(lambda _=False, k=key: self._emit_process(k))
            play.addWidget(btn)
        calc = QPushButton(self.tr_("image_calc"))
        calc.clicked.connect(lambda: self.processRequested.emit("image_calc", {}))
        play.addWidget(calc)
        play.addStretch(1)
        self.addTab(_scroll(proc), self.tr_("filters"))

        fft = QWidget()
        flay = QVBoxLayout(fft)
        self.mask_kind = QComboBox()
        self.mask_kind.addItems(["circle", "annulus", "rect"])
        self.mask_radius = QDoubleSpinBox()
        self.mask_radius.setRange(1, 2000)
        self.mask_radius.setValue(20)
        self.mask_inner = QDoubleSpinBox()
        self.mask_inner.setRange(0, 2000)
        self.mask_inner.setValue(6)
        self.mask_outer = QDoubleSpinBox()
        self.mask_outer.setRange(1, 2000)
        self.mask_outer.setValue(40)
        self.invert_mask = QComboBox()
        self.invert_mask.addItems(["off", "on"])
        self.mask_soft = QDoubleSpinBox()
        self.mask_soft.setRange(0, 40)
        self.mask_soft.setValue(0)
        self.live_ifft = QCheckBox(self.tr_("preview_ifft"))
        ff = QFormLayout()
        ff.addRow(self.tr_("mask"), self.mask_kind)
        ff.addRow(self.tr_("mask_circle") + " R", self.mask_radius)
        ff.addRow(self.tr_("inner_angle"), self.mask_inner)
        ff.addRow(self.tr_("outer_angle"), self.mask_outer)
        ff.addRow(self.tr_("invert_mask"), self.invert_mask)
        ff.addRow(self.tr_("soft_edge"), self.mask_soft)
        flay.addLayout(ff)
        flay.addWidget(self.live_ifft)
        for box in (self.mask_kind, self.invert_mask):
            box.currentTextChanged.connect(lambda *_: self._fft_changed())
        for spin in (self.mask_radius, self.mask_inner, self.mask_outer, self.mask_soft):
            spin.valueChanged.connect(lambda *_: self._fft_changed())
        self.live_ifft.toggled.connect(lambda *_: self._fft_changed())
        b_fft = QPushButton(self.tr_("fft"))
        b_fft.clicked.connect(lambda: self.processRequested.emit("fft", {}))
        b_place = QPushButton(self.tr_("place_mask"))
        b_place.clicked.connect(lambda: self.processRequested.emit("place_fft_mask", self.fft_params()))
        b_ifft = QPushButton(self.tr_("apply_ifft"))
        b_ifft.clicked.connect(lambda: self.processRequested.emit("ifft", self.fft_params()))
        flay.addWidget(b_fft)
        flay.addWidget(b_place)
        flay.addWidget(b_ifft)
        flay.addStretch(1)
        self.addTab(_scroll(fft), "FFT")

        eds = QWidget()
        elay = QVBoxLayout(eds)
        self.table = PeriodicTable()
        elay.addWidget(QLabel(self.tr_("periodic_table")))
        elay.addWidget(self.table)
        self.sel_count = QLabel(self.tr_("selected_count", n=0, els="—"))
        self.sel_count.setObjectName("hint")
        elay.addWidget(self.sel_count)
        self.pca_n = QSpinBox()
        self.pca_n.setRange(1, 64)
        self.pca_n.setValue(8)
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0, 5000)
        self.thickness.setValue(0)
        self.density = QDoubleSpinBox()
        self.density.setRange(0.1, 25)
        self.density.setValue(5.0)
        self.absorption = QComboBox()
        self.absorption.addItems(["off", "on"])
        self.bg_eds = QComboBox()
        self.bg_eds.addItems(["snip", "linear", "velox"])
        self.map_mode = QComboBox()
        self.map_mode.addItems(["window", "gaussian"])
        ef = QFormLayout()
        ef.addRow(self.tr_("components"), self.pca_n)
        ef.addRow(self.tr_("thickness"), self.thickness)
        ef.addRow(self.tr_("density"), self.density)
        ef.addRow(self.tr_("absorption"), self.absorption)
        ef.addRow(self.tr_("bg_model"), self.bg_eds)
        ef.addRow(self.tr_("map_mode"), self.map_mode)
        elay.addLayout(ef)
        elay.addWidget(QLabel(self.tr_("k_table")))
        self.k_table = QTableWidget(0, 2)
        self.k_table.setHorizontalHeaderLabels([self.tr_("el"), self.tr_("k_vs_si")])
        self.k_table.horizontalHeader().setStretchLastSection(True)
        self.k_table.setMaximumHeight(120)
        elay.addWidget(self.k_table)
        for key, label in (
            ("identify", "identify"),
            ("element_maps", "element_maps"),
            ("gauss_maps", "gauss_maps"),
            ("overlay", "overlay"),
            ("quantify", "quantify"),
            ("pca", "pca"),
            ("line_scan", "line_scan"),
        ):
            btn = QPushButton(self.tr_(label))
            btn.clicked.connect(lambda _=False, k=key: self._emit_eds(k))
            elay.addWidget(btn)
        self.quant_table = QTableWidget(0, 6)
        self.quant_table.setHorizontalHeaderLabels(
            [
                self.tr_("el"),
                self.tr_("at_percent"),
                self.tr_("wt_percent"),
                self.tr_("intensity_short"),
                "k",
                self.tr_("abs_short"),
            ]
        )
        self.quant_table.horizontalHeader().setStretchLastSection(True)
        self.quant_table.setMaximumHeight(160)
        elay.addWidget(self.quant_table)
        elay.addStretch(1)
        self.addTab(_scroll(eds), self.tr_("eds"))

        dpc = QWidget()
        dlay = QVBoxLayout(dpc)
        b = QPushButton(self.tr_("compute_dpc"))
        b.clicked.connect(lambda: self.processRequested.emit("dpc", {}))
        dlay.addWidget(b)
        dlay.addStretch(1)
        self.addTab(_scroll(dpc), self.tr_("dpc"))

        stem = QWidget()
        slay = QVBoxLayout(stem)
        self.bf_r = QDoubleSpinBox()
        self.bf_r.setRange(1, 200)
        self.bf_r.setValue(4)
        self.adf_in = QDoubleSpinBox()
        self.adf_in.setRange(0, 200)
        self.adf_in.setValue(5)
        self.adf_out = QDoubleSpinBox()
        self.adf_out.setRange(1, 200)
        self.adf_out.setValue(11)
        self.abf_in = QDoubleSpinBox()
        self.abf_in.setRange(0, 200)
        self.abf_in.setValue(2)
        self.abf_out = QDoubleSpinBox()
        self.abf_out.setRange(0.5, 200)
        self.abf_out.setValue(3.5)
        self.det_unit = QComboBox()
        self.det_unit.addItems(["px", "mrad"])
        self.q_per_px = QDoubleSpinBox()
        self.q_per_px.setDecimals(6)
        self.q_per_px.setRange(0, 10)
        self.q_per_px.setValue(0.0)
        self.rotation_deg = QDoubleSpinBox()
        self.rotation_deg.setRange(-180, 180)
        self.rotation_deg.setValue(0)
        self.cl_m = QDoubleSpinBox()
        self.cl_m.setDecimals(4)
        self.cl_m.setRange(0, 10)
        self.cl_m.setValue(0)
        self.det_pixel_m = QDoubleSpinBox()
        self.det_pixel_m.setDecimals(12)
        self.det_pixel_m.setRange(0, 1e-3)
        self.det_pixel_m.setValue(0)
        sf = QFormLayout()
        sf.addRow("BF R", self.bf_r)
        sf.addRow(self.tr_("inner_angle"), self.adf_in)
        sf.addRow(self.tr_("outer_angle"), self.adf_out)
        sf.addRow(self.tr_("abf_inner"), self.abf_in)
        sf.addRow(self.tr_("abf_outer"), self.abf_out)
        sf.addRow(self.tr_("detector_unit"), self.det_unit)
        sf.addRow(self.tr_("q_per_px"), self.q_per_px)
        sf.addRow(self.tr_("rotation"), self.rotation_deg)
        sf.addRow(self.tr_("camera_length"), self.cl_m)
        slay.addLayout(sf)
        self.cartoon = QLabel()
        self.cartoon.setFixedSize(96, 96)
        slay.addWidget(self.cartoon)
        for box in (self.bf_r, self.adf_in, self.adf_out, self.abf_in, self.abf_out):
            box.valueChanged.connect(lambda *_: self._refresh_cartoon())
        self._refresh_cartoon()
        for key, label in (
            ("virtual_bf", "virtual_bf"),
            ("virtual_adf", "virtual_adf"),
            ("virtual_abf", "virtual_abf"),
            ("com", "com"),
        ):
            btn = QPushButton(self.tr_(label))
            btn.clicked.connect(lambda _=False, k=key: self.processRequested.emit(k, self.stem_params()))
            slay.addWidget(btn)
        slay.addStretch(1)
        self.addTab(_scroll(stem), self.tr_("stem4d"))

        atoms = QWidget()
        alay = QVBoxLayout(atoms)
        self.atom_sigma = QDoubleSpinBox()
        self.atom_sigma.setRange(0.3, 20)
        self.atom_sigma.setValue(1.2)
        self.atom_sep = QSpinBox()
        self.atom_sep.setRange(2, 40)
        self.atom_sep.setValue(6)
        af = QFormLayout()
        af.addRow(self.tr_("sigma"), self.atom_sigma)
        af.addRow(self.tr_("min_distance"), self.atom_sep)
        alay.addLayout(af)
        ba = QPushButton(self.tr_("find_atoms"))
        ba.clicked.connect(lambda: self.processRequested.emit("atoms", self.atom_params()))
        alay.addWidget(ba)
        alay.addStretch(1)
        self.addTab(_scroll(atoms), self.tr_("atoms"))

        drift = QWidget()
        rlay = QVBoxLayout(drift)
        self.dcfi_ref = QComboBox()
        self.dcfi_ref.addItems(["first", "previous", "mean"])
        self.dcfi_reduce = QComboBox()
        self.dcfi_reduce.addItems(["mean", "sum"])
        self.dcfi_highpass = QDoubleSpinBox()
        self.dcfi_highpass.setRange(0, 80)
        self.dcfi_highpass.setValue(0)
        self.dcfi_max_shift = QDoubleSpinBox()
        self.dcfi_max_shift.setRange(0, 200)
        self.dcfi_max_shift.setValue(0)
        self.dcfi_crop = QComboBox()
        self.dcfi_crop.addItems(["on", "off"])
        df = QFormLayout()
        df.addRow(self.tr_("reference"), self.dcfi_ref)
        df.addRow(self.tr_("reduce"), self.dcfi_reduce)
        df.addRow(self.tr_("highpass_corr"), self.dcfi_highpass)
        df.addRow(self.tr_("max_shift"), self.dcfi_max_shift)
        df.addRow(self.tr_("crop_overlap"), self.dcfi_crop)
        rlay.addLayout(df)
        bdcfi = QPushButton(self.tr_("dcfi"))
        bdcfi.clicked.connect(lambda: self.processRequested.emit("dcfi", self.dcfi_params()))
        bd = QPushButton(self.tr_("align_sum"))
        bd.clicked.connect(lambda: self.processRequested.emit("drift", {}))
        rlay.addWidget(bdcfi)
        rlay.addWidget(bd)
        rlay.addStretch(1)
        self.addTab(_scroll(drift), self.tr_("drift"))
        self._dcfi_btn = bdcfi

        self.table.elementToggled.connect(self._on_element_toggle)

    def _slider_row(self, name: str, lo: int, hi: int, val: int):
        from PySide6.QtWidgets import QSlider

        sl = QSlider(Qt.Orientation.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        sl.valueChanged.connect(lambda _: self._emit_display())
        sl.setObjectName(name)
        return sl

    def _emit_display(self, *, from_hist: bool = False) -> None:
        # Contrast squeezes the displayed range around the mid-point.
        contrast = self.s_contrast.value() / 100.0
        payload = {
            "colormap": self.cmap.currentText(),
            "brightness": self.s_bright.value() / 100.0,
            "gamma": self.s_gamma.value() / 100.0,
            "contrast": contrast,
            "invert": self.invert_lut.isChecked(),
        }
        if from_hist:
            lo, hi = self.hist_region.getRegion()
            payload["vmin"] = float(lo)
            payload["vmax"] = float(hi)
        self.displayChanged.emit(payload)

    def _on_hist_region(self) -> None:
        if self._hist_guard:
            return
        self._emit_display(from_hist=True)

    def add_lut_name(self, name: str) -> None:
        if self.cmap.findText(name) < 0:
            self.cmap.addItem(name)
        self.cmap.setCurrentText(name)

    def _on_element_toggle(self, *_args) -> None:
        self.refresh_selected()
        self.processRequested.emit("eds_selection", {"elements": self.table.selected_list()})

    def refresh_selected(self) -> None:
        els = self.table.selected_list()
        self.sel_count.setText(self.tr_("selected_count", n=len(els), els=", ".join(els) or "—"))

    def _emit_process(self, key: str) -> None:
        params = {
            "sigma": self.sigma.value(),
            "size": self.median_size.value(),
            "bg_sigma": self.bg_sigma.value(),
            "amount": 1.0,
        }
        if key == "bg_sub":
            params.update(self.bg_params())
        self.processRequested.emit(key, params)

    def bg_params(self) -> dict:
        return {
            "method": self.bg_method.currentText(),
            "bg_sigma": self.bg_sigma.value(),
            "sigma": self.bg_sigma.value(),
            "radius": self.bg_radius.value(),
            "percentile": self.bg_percentile.value(),
        }

    def dcfi_params(self) -> dict:
        max_shift = self.dcfi_max_shift.value()
        return {
            "reference": self.dcfi_ref.currentText(),
            "reduce": self.dcfi_reduce.currentText(),
            "highpass_sigma": self.dcfi_highpass.value(),
            "max_shift": max_shift if max_shift > 0 else None,
            "crop": self.dcfi_crop.currentText() == "on",
        }

    def _fft_changed(self) -> None:
        self.processRequested.emit("fft_mask", self.fft_params())

    def k_factors(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in range(self.k_table.rowCount()):
            el = self.k_table.item(row, 0)
            kf = self.k_table.item(row, 1)
            if el and kf:
                try:
                    out[el.text()] = float(kf.text())
                except ValueError:
                    continue
        return out

    def set_k_rows(self, factors: dict[str, float]) -> None:
        self.k_table.setRowCount(len(factors))
        for i, (el, k) in enumerate(factors.items()):
            self.k_table.setItem(i, 0, QTableWidgetItem(el))
            self.k_table.setItem(i, 1, QTableWidgetItem(f"{k:.3f}"))

    def _emit_eds(self, key: str) -> None:
        self.processRequested.emit(
            key,
            {
                "elements": self.table.selected_list(),
                "components": self.pca_n.value(),
                "k_factors": self.k_factors(),
                "thickness_nm": self.thickness.value(),
                "density": self.density.value(),
                "absorption": self.absorption.currentText() == "on",
                "bg_method": self.bg_eds.currentText(),
                "map_mode": self.map_mode.currentText(),
            },
        )

    def fft_params(self) -> dict:
        return {
            "kind": self.mask_kind.currentText(),
            "radius": self.mask_radius.value(),
            "inner": self.mask_inner.value(),
            "outer": self.mask_outer.value(),
            "invert": self.invert_mask.currentText() == "on",
            "soft": self.mask_soft.value(),
            "live": self.live_ifft.isChecked(),
        }

    def stem_params(self) -> dict:
        return {
            "radius": self.bf_r.value(),
            "inner": self.adf_in.value(),
            "outer": self.adf_out.value(),
            "abf_inner": self.abf_in.value(),
            "abf_outer": self.abf_out.value(),
            "unit": self.det_unit.currentText(),
            "q_per_px": self.q_per_px.value(),
            "rotation_deg": self.rotation_deg.value(),
            "camera_length_m": self.cl_m.value() or None,
            "detector_pixel_m": self.det_pixel_m.value() or None,
        }

    def diffraction_params(self) -> dict:
        return {
            "q_per_px": self.q_per_px.value(),
            "rotation_deg": self.rotation_deg.value(),
            "unit": self.det_unit.currentText(),
            "camera_length_m": self.cl_m.value(),
        }

    def set_diffraction_controls(self, data: dict | None) -> None:
        if not data:
            return
        if data.get("q_per_px") is not None:
            self.q_per_px.setValue(float(data.get("q_per_px") or 0))
        if data.get("rotation_deg") is not None:
            self.rotation_deg.setValue(float(data.get("rotation_deg") or 0))
        unit = data.get("unit")
        if unit:
            idx = self.det_unit.findText(str(unit))
            if idx >= 0:
                self.det_unit.setCurrentIndex(idx)
        if data.get("camera_length_m") is not None:
            self.cl_m.setValue(float(data.get("camera_length_m") or 0))

    def _refresh_cartoon(self) -> None:
        from PySide6.QtGui import QImage, QPixmap

        from openvelox.processing.stem4d import detector_cartoon

        arr = np.ascontiguousarray(
            detector_cartoon(
                96,
                bf_r=self.bf_r.value(),
                adf_in=self.adf_in.value(),
                adf_out=self.adf_out.value(),
                abf_in=self.abf_in.value(),
                abf_out=self.abf_out.value(),
            )
        )
        h, w = arr.shape[:2]
        qimg = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.cartoon.setPixmap(QPixmap.fromImage(qimg.copy()))

    def atom_params(self) -> dict:
        return {"sigma": self.atom_sigma.value(), "min_distance": self.atom_sep.value()}

    def show_dataset(self, ds: Dataset | None) -> None:
        if ds is None:
            self.info.setPlainText("")
            self.meta_tree.clear()
            empty = QTreeWidgetItem([self.tr_("select_to_inspect"), ""])
            empty.setDisabled(True)
            self.meta_tree.addTopLevelItem(empty)
            return
        m = dict(ds.metadata or {})
        extra = {
            "detector": ds.detector or m.get("detector"),
            "pixel_size_m": m.get("pixel_size_m") or ds.pixel_size_m(),
            "kind": ds.kind.value,
            "shape": "×".join(str(n) for n in ds.shape),
            "source_path": ds.source_path,
        }
        lines = [
            f"{ds.display_name()}",
            f"Kind: {ds.kind.value}",
            f"Shape: {ds.shape}",
            f"{self.tr_('hv')}: {format_hv(m.get('high_tension_v'))}",
            f"{self.tr_('mag')}: {m.get('magnification', '—')}",
            f"{self.tr_('pixel_size')}: {format_pixel_size(m.get('pixel_size_m') or ds.pixel_size_m())}",
            f"{self.tr_('detector')}: {ds.detector or m.get('detector', '—')}",
            f"{self.tr_('dwell')}: {format_dwell(m.get('dwell_time_s'))}",
            f"{self.tr_('instrument')}: {m.get('instrument', '—')}",
            f"{self.tr_('camera_length')}: {m.get('camera_length_m', '—')}",
            f"{self.tr_('convergence')}: {m.get('convergence_rad', '—')}",
            f"Source: {ds.source_path}",
        ]
        self.info.setPlainText("\n".join(lines))
        self._fill_metadata(ds.display_name(), m, extra)

    def show_experiment(self, experiment: ExperimentFile) -> None:
        meta = dict(experiment.metadata or {})
        extra = {"source_path": experiment.path, "n_datasets": len(experiment.datasets)}
        self.info.setPlainText(f"{experiment.name}\n{experiment.path}\n{len(experiment.datasets)} dataset(s)")
        self._fill_metadata(experiment.name, meta, extra)

    def _fill_metadata(self, title: str, metadata: dict, extra: dict | None = None) -> None:
        self.meta_tree.clear()
        root = QTreeWidgetItem([title, extra.get("shape", "") if extra else ""])
        root.setExpanded(True)
        self.meta_tree.addTopLevelItem(root)
        for section_key, rows in acquisition_sections(metadata, extra=extra):
            if not rows:
                continue
            section = QTreeWidgetItem([self.tr_(section_key), ""])
            section.setData(0, Qt.ItemDataRole.UserRole, section_key)
            for key, value in rows:
                child = QTreeWidgetItem([self.tr_(key), str(value)])
                child.setToolTip(0, key)
                child.setToolTip(1, str(value))
                section.addChild(child)
            section.setExpanded(section_key != "all_metadata")
            root.addChild(section)
        self.meta_tree.expandToDepth(1)
        self._filter_metadata(self.meta_filter.text())

    def _filter_metadata(self, text: str) -> None:
        needle = (text or "").strip().lower()

        def walk(item: QTreeWidgetItem) -> bool:
            hit = False
            for i in range(item.childCount()):
                if walk(item.child(i)):
                    hit = True
            if not needle:
                item.setHidden(False)
                return True
            own = needle in item.text(0).lower() or needle in item.text(1).lower()
            show = own or hit
            item.setHidden(not show)
            if show and hit:
                item.setExpanded(True)
            return show

        for i in range(self.meta_tree.topLevelItemCount()):
            walk(self.meta_tree.topLevelItem(i))

    def metadata_pairs(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.childCount() == 0 and item.text(1):
                rows.append((item.text(0), item.text(1)))
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.meta_tree.topLevelItemCount()):
            walk(self.meta_tree.topLevelItem(i))
        return rows

    def set_histogram(self, image: np.ndarray, vmin: float | None = None, vmax: float | None = None) -> None:
        arr = np.asarray(image, dtype=np.float64).ravel()
        if arr.size == 0:
            return
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            self.hist_curve.setData([], [])
            return
        y, x = np.histogram(finite, bins=min(128, int(finite.size)))
        self.hist_curve.setData(x[:-1], y)
        lo = float(vmin) if vmin is not None else float(x[0])
        hi = float(vmax) if vmax is not None else float(x[-1])
        if hi <= lo:
            hi = lo + 1.0
        self._hist_guard = True
        try:
            self.hist_region.setRegion((lo, hi))
        finally:
            self._hist_guard = False

    def set_roi_histogram(self, image: np.ndarray, mask: np.ndarray | None = None, bins: int = 64) -> None:
        x, y = intensity_histogram(image, mask, bins=bins)
        self.roi_hist_curve.setData(x, y)

    def scale_bar_params(self) -> dict:
        length = self.sb_length.currentData()
        try:
            length_m = float(length) if length not in (None, "") else None
        except (TypeError, ValueError):
            length_m = None
        return {
            "color": str(self.sb_color.currentData() or "#FFFFFF"),
            "length_m": length_m,
            "font_size": int(self.sb_font.value()),
            "position": str(self.sb_position.currentData() or "bottom_left"),
            "thickness": int(self.sb_thick.value()),
            "visible": bool(self.sb_visible.isChecked()),
        }

    def scale_bar_style(self) -> ScaleBarStyle:
        return ScaleBarStyle.from_mapping(self.scale_bar_params())

    def set_scale_bar_controls(self, style: ScaleBarStyle | dict | None) -> None:
        if not isinstance(style, ScaleBarStyle):
            style = ScaleBarStyle.from_mapping(style)
        self._sb_guard = True
        try:
            self.sb_visible.setChecked(bool(style.visible))
            idx = self.sb_color.findData(style.color)
            if idx < 0:
                self.sb_color.addItem(style.color, style.color)
                idx = self.sb_color.findData(style.color)
            if idx >= 0:
                self.sb_color.setCurrentIndex(idx)
            pidx = self.sb_position.findData(style.position)
            if pidx >= 0:
                self.sb_position.setCurrentIndex(pidx)
            self.sb_font.setValue(int(style.font_size))
            self.sb_thick.setValue(int(style.thickness))
            if style.length_m:
                match = -1
                for i in range(self.sb_length.count()):
                    data = self.sb_length.itemData(i)
                    if data is not None and abs(float(data) - float(style.length_m)) < 1e-15:
                        match = i
                        break
                if match >= 0:
                    self.sb_length.setCurrentIndex(match)
            else:
                self.sb_length.setCurrentIndex(0)
        finally:
            self._sb_guard = False

    def _emit_scale_bar(self) -> None:
        if self._sb_guard:
            return
        self.scaleBarChanged.emit(self.scale_bar_params())

    def set_quant_rows(self, rows: list[dict]) -> None:
        self.quant_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            vals = [
                str(row.get("element", "")),
                f"{row.get('atomic_percent', 0):.2f}",
                f"{row.get('weight_percent', 0):.2f}",
                f"{row.get('intensity', 0):.1f}",
                f"{row.get('k_factor', 0):.2f}",
                f"{row.get('absorption_factor', 1):.3f}",
            ]
            for j, val in enumerate(vals):
                self.quant_table.setItem(i, j, QTableWidgetItem(val))

    def retranslate(self) -> None:
        self.setTabText(0, self.tr_("info"))
        self.setTabText(1, self.tr_("display"))
        self.setTabText(2, self.tr_("filters"))
        self.setTabText(3, "FFT")
        self.setTabText(4, self.tr_("eds"))
        self.setTabText(5, self.tr_("dpc"))
        self.setTabText(6, self.tr_("stem4d"))
        self.setTabText(7, self.tr_("atoms"))
        self.setTabText(8, self.tr_("drift"))
        self._auto_btn.setText(self.tr_("auto_contrast"))
        self.invert_lut.setText(self.tr_("invert_lut"))
        self.live_ifft.setText(self.tr_("preview_ifft"))
        self._load_lut_btn.setText(self.tr_("load_lut"))
        self._dcfi_btn.setText(self.tr_("dcfi"))
        self.meta_filter.setPlaceholderText(self.tr_("search_metadata"))
        self.meta_tree.setHeaderLabels([self.tr_("property"), self.tr_("value")])
        self.k_table.setHorizontalHeaderLabels([self.tr_("el"), self.tr_("k_vs_si")])
        self.quant_table.setHorizontalHeaderLabels(
            [
                self.tr_("el"),
                self.tr_("at_percent"),
                self.tr_("wt_percent"),
                self.tr_("intensity_short"),
                "k",
                self.tr_("abs_short"),
            ]
        )
        self._scale_box.setTitle(self.tr_("scale_bar"))
        self.sb_visible.setText(self.tr_("scale_bar_visible"))
        self._roi_hist_label.setText(self.tr_("roi_histogram"))
        for i, (key, _hex) in enumerate(_SB_COLORS):
            if i < self.sb_color.count():
                self.sb_color.setItemText(i, self.tr_(key))
        for i, key in enumerate(_SB_POSITIONS):
            if i < self.sb_position.count():
                self.sb_position.setItemText(i, self.tr_(key))
        if self.sb_length.count():
            self.sb_length.setItemText(0, self.tr_("auto"))
        self.refresh_selected()
