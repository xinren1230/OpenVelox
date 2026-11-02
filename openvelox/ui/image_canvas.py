"""Central image display: zoom/pan, scale bar, overlays, measurement tools."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from openvelox.crashlog import widget_alive
from openvelox.processing.display import apply_display, auto_levels
from openvelox.processing.measure import polygon_mask
from openvelox.processing.scalebar import ScaleBarStyle, choose_bar, parse_color


class ScaleBarOverlay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pixel_m: float | None = None
        self.px_per_view: float = 1.0
        self.view_width_data: float = 80.0
        self.style = ScaleBarStyle()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(40)
        self.setFixedWidth(300)

    def set_style(self, style: ScaleBarStyle) -> None:
        self.style = style or ScaleBarStyle()
        self.setVisible(bool(self.style.visible))
        self.update()

    def set_scale(self, pixel_m: float | None, view_width_data: float, view_width_px: float) -> None:
        self.pixel_m = pixel_m
        self.view_width_data = float(view_width_data)
        if view_width_data > 0:
            self.px_per_view = view_width_px / view_width_data
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self.style.visible or not self.pixel_m or self.pixel_m <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _length, label, bar_data = choose_bar(self.pixel_m, self.view_width_data, self.style)
        bar_px = max(12, int(bar_data * self.px_per_view))
        rgb = parse_color(self.style.color)
        color = QColor(*rgb)
        thickness = max(1, int(self.style.thickness))
        right = self.style.position.endswith("right")
        x0 = self.width() - 8 - bar_px if right else 8
        painter.setPen(QPen(color, 1))
        painter.setBrush(color)
        painter.drawRect(x0, 20, bar_px, thickness)
        painter.setFont(QFont("DejaVu Sans", max(6, int(self.style.font_size))))
        painter.setPen(color)
        painter.drawText(x0, 16, label)
        painter.end()


class ImageCanvas(QWidget):
    pixelPicked = Signal(int, int, float)
    toolFinished = Signal(str, object)
    viewChanged = Signal()
    imageChanged = Signal()
    fftMaskChanged = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.image = np.zeros((8, 8), dtype=np.float64)
        self.pixel_m: float | None = 1e-9
        self.colormap = "gray"
        self.vmin = 0.0
        self.vmax = 1.0
        self.gamma = 1.0
        self.brightness = 1.0
        self.invert = False
        self.tool = "pointer"
        self.scale_bar_style = ScaleBarStyle()
        self._mask_item = None
        self._fft_roi = None
        self._clicks: list[tuple[float, float]] = []
        self._roi = None
        self._line = None
        self._scatter = None
        self._annots: list = []
        self._annot_data: list[dict] = []
        self._last_line: tuple[tuple[float, float], tuple[float, float]] | None = None
        self._poly_points: list[tuple[float, float]] | None = None
        self._frame_loader = None
        self._n_frames = 0
        self.profile_linewidth = 1.0

        self.plot = pg.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)
        self.plot.hideAxis("bottom")
        self.plot.hideAxis("left")
        self.plot.setBackground("#101214")
        self.vb = self.plot.getViewBox()
        self.vb.setMenuEnabled(False)
        self.item = pg.ImageItem()
        self.item.setAutoDownsample(True)
        self.plot.addItem(self.item)

        self.scale_bar = ScaleBarOverlay(self.plot)
        self.scale_bar.move(12, 12)

        self.frame_row = QWidget()
        fr = QHBoxLayout(self.frame_row)
        fr.setContentsMargins(4, 0, 4, 0)
        self.frame_label = QLabel("Frame 0")
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.valueChanged.connect(self._on_frame)
        fr.addWidget(self.frame_label)
        fr.addWidget(self.frame_slider)
        self.frame_row.hide()
        self._stack: np.ndarray | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.frame_row)

        proxy = pg.SignalProxy(self.plot.scene().sigMouseClicked, rateLimit=20, slot=self._on_click)
        self._proxy = proxy
        self.vb.sigRangeChanged.connect(self._update_scale_bar)
        self.plot.scene().sigMouseMoved.connect(self._on_move)

    def set_scale_bar_style(self, style: ScaleBarStyle | dict | None) -> None:
        if not isinstance(style, ScaleBarStyle):
            style = ScaleBarStyle.from_mapping(style)
        self.scale_bar_style = style
        self.scale_bar.set_style(style)
        self._update_scale_bar()

    def set_image(
        self,
        image: np.ndarray,
        pixel_m: float | None = None,
        stack: np.ndarray | None = None,
        reset_levels: bool = True,
        n_frames: int = 0,
        frame_loader=None,
    ) -> None:
        arr = np.asarray(image)
        if arr.ndim == 3 and arr.shape[-1] in {3, 4}:
            arr = np.mean(arr[..., :3], axis=-1)
        if arr.ndim != 2:
            if arr.size == 0:
                arr = np.zeros((8, 8), dtype=np.float64)
            elif arr.ndim == 1:
                arr = arr.reshape(1, -1)
            elif arr.ndim == 0:
                arr = np.zeros((8, 8), dtype=np.float64)
            else:
                arr = np.reshape(arr, (arr.shape[0], -1))
        self.image = np.nan_to_num(np.asarray(arr, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
        if pixel_m is not None:
            self.pixel_m = pixel_m
        if frame_loader is not None:
            self._frame_loader = frame_loader
        try:
            self._stack = np.asarray(stack) if stack is not None else None
        except Exception:
            self._stack = None
        frames = int(n_frames) if n_frames else 0
        if frames <= 1 and self._stack is not None and self._stack.ndim == 3:
            frames = int(self._stack.shape[0])
        self._n_frames = frames
        if frames > 1:
            cur = int(self.frame_slider.value()) if not reset_levels else 0
            self.frame_slider.blockSignals(True)
            self.frame_slider.setRange(0, frames - 1)
            self.frame_slider.setValue(int(np.clip(cur, 0, frames - 1)))
            self.frame_slider.blockSignals(False)
            self.frame_row.show()
            self.frame_label.setText(f"Frame {self.frame_slider.value()}")
        else:
            self.frame_row.hide()
        if reset_levels:
            self.vmin, self.vmax = auto_levels(self.image)
        self.refresh()
        if reset_levels:
            self.vb.autoRange()
        self._update_scale_bar()

    def frame_index(self) -> int:
        return int(self.frame_slider.value()) if self.frame_row.isVisible() else 0

    def set_stack_frame(self, index: int) -> None:
        n = self._n_frames or (self._stack.shape[0] if self._stack is not None and self._stack.ndim == 3 else 0)
        if n <= 0 and self._frame_loader is None and self._stack is None:
            return
        index = int(np.clip(index, 0, max(0, n - 1)))
        try:
            if self._frame_loader is not None:
                frame = np.asarray(self._frame_loader(index), dtype=np.float64)
            elif self._stack is not None:
                frame = np.asarray(self._stack[index], dtype=np.float64)
            else:
                return
        except Exception:
            return
        self.image = np.nan_to_num(frame, nan=0.0, posinf=0.0, neginf=0.0)
        self.frame_label.setText(f"Frame {index}")
        self.refresh()
        self.imageChanged.emit()

    def _on_frame(self, value: int) -> None:
        self.set_stack_frame(value)

    def set_display(self, **kwargs) -> None:
        for key in ("colormap", "vmin", "vmax", "gamma", "brightness", "invert"):
            if key in kwargs and kwargs[key] is not None:
                setattr(self, key, kwargs[key])
        self.refresh()

    def refresh(self) -> None:
        from openvelox.processing.preview import downsample2d

        src = self.image
        # Paint a downsampled raster for huge frames; keep full-res in ``self.image``.
        disp = downsample2d(src, 2048) if src.ndim == 2 and max(src.shape) > 2048 else src
        rgb = apply_display(
            disp,
            colormap=self.colormap,
            vmin=self.vmin,
            vmax=self.vmax,
            gamma=self.gamma,
            brightness=self.brightness,
            invert=bool(self.invert),
        )
        self.item.setImage(rgb, autoLevels=False)
        if src.ndim == 2 and src.size and disp is not src:
            self.item.setRect(QRectF(0, 0, float(src.shape[1]), float(src.shape[0])))

    def set_tool(self, name: str) -> None:
        self.tool = name
        self._clicks.clear()
        if self._roi is not None:
            self.plot.removeItem(self._roi)
            self._roi = None
        if self._line is not None:
            self.plot.removeItem(self._line)
            self._line = None
        self._poly_points = None

    def clear_overlays(self) -> None:
        if self._scatter is not None:
            self.plot.removeItem(self._scatter)
            self._scatter = None
        for item in self._annots:
            self.plot.removeItem(item)
        self._annots.clear()
        self._annot_data.clear()
        self._last_line = None
        self._poly_points = None
        self.set_tool(self.tool)

    def show_points(self, rows: np.ndarray, cols: np.ndarray, color="y") -> None:
        if self._scatter is not None:
            self.plot.removeItem(self._scatter)
        self._scatter = pg.ScatterPlotItem(x=cols, y=rows, size=6, brush=color, pen=None)
        self.plot.addItem(self._scatter)

    def add_annotation(self, text: str, x: float, y: float, *, color: str = "#FFE08A") -> None:
        item = pg.TextItem(text, color=color, anchor=(0, 1))
        item.setPos(x, y)
        self.plot.addItem(item)
        self._annots.append(item)
        self._annot_data.append({"kind": "text", "x": float(x), "y": float(y), "text": str(text), "color": color})

    def collect_annotations(self) -> list[dict]:
        return list(self._annot_data)

    def _map(self, pos) -> tuple[float, float] | None:
        if self.vb.sceneBoundingRect().contains(pos):
            p = self.vb.mapSceneToView(pos)
            return float(p.x()), float(p.y())
        return None

    def teardown(self) -> None:
        """Drop pyqtgraph items before the widget is deleted (closed tab)."""
        try:
            self.vb.sigRangeChanged.disconnect(self._update_scale_bar)
        except Exception:
            pass
        try:
            self.clear_overlays()
        except Exception:
            pass
        self.clear_fft_mask()
        self._roi = None
        self._line = None

    def closeEvent(self, event) -> None:  # noqa: N802
        self.teardown()
        super().closeEvent(event)

    def _on_move(self, pos) -> None:
        if not widget_alive(self):
            return
        mapped = self._map(pos)
        if mapped is None:
            return
        x, y = mapped
        r, c = int(round(y)), int(round(x))
        if self.image.ndim == 2 and 0 <= r < self.image.shape[0] and 0 <= c < self.image.shape[1]:
            self.pixelPicked.emit(c, r, float(self.image[r, c]))

    def simulate_tool(self, name: str, *points: tuple[float, float]) -> None:
        """Drive a measurement tool from tests without sending mouse events."""
        self.set_tool(name)
        for x, y in points:
            self._clicks.append((float(x), float(y)))
        if name in {"line_profile", "distance", "d_spacing"} and len(self._clicks) >= 2:
            self._finish_line()
        elif name == "angle" and len(self._clicks) >= 3:
            self._finish_angle()
        elif name in {"roi_rect", "roi_ellipse"} and len(self._clicks) >= 2:
            self._finish_roi()
        elif name == "roi_polygon" and len(self._clicks) >= 3:
            self._finish_polygon()

    def _on_click(self, event) -> None:
        if not widget_alive(self):
            return
        ev = event[0] if isinstance(event, tuple) else event
        button = ev.button()
        if button == Qt.MouseButton.RightButton:
            if self.tool == "roi_polygon" and len(self._clicks) >= 3:
                self._finish_polygon()
            return
        if button != Qt.MouseButton.LeftButton:
            return
        mapped = self._map(ev.scenePos())
        if mapped is None:
            return
        x, y = mapped
        if self.tool == "pointer":
            return
        if self.tool == "roi_polygon" and len(self._clicks) >= 3:
            x0, y0 = self._clicks[0]
            if float(np.hypot(x - x0, y - y0)) <= 4.0:
                self._finish_polygon()
                return
        self._clicks.append((x, y))
        if self.tool == "roi_polygon":
            self._update_poly_preview()
            double = bool(ev.double()) if hasattr(ev, "double") else False
            if double and len(self._clicks) >= 3:
                self._finish_polygon()
            return
        if self.tool in {"line_profile", "distance", "d_spacing"} and len(self._clicks) == 2:
            self._finish_line()
        elif self.tool == "angle" and len(self._clicks) == 3:
            self._finish_angle()
        elif self.tool in {"roi_rect", "roi_ellipse"} and len(self._clicks) == 2:
            self._finish_roi()

    def _update_poly_preview(self) -> None:
        if self._line is not None:
            self.plot.removeItem(self._line)
            self._line = None
        if len(self._clicks) < 2:
            return
        xs = [p[0] for p in self._clicks]
        ys = [p[1] for p in self._clicks]
        self._line = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#7CDB6A", width=2))
        self.plot.addItem(self._line)

    def _finish_line(self) -> None:
        (x0, y0), (x1, y1) = self._clicks
        if self._line is not None:
            self.plot.removeItem(self._line)
        self._line = pg.PlotDataItem([x0, x1], [y0, y1], pen=pg.mkPen("#00A3E0", width=2))
        self.plot.addItem(self._line)
        self._last_line = ((y0, x0), (y1, x1))
        self._annot_data.append({"kind": "line", "p0": (y0, x0), "p1": (y1, x1), "width": 2, "color": "#00A3E0"})
        self.toolFinished.emit(
            self.tool,
            {"p0": (y0, x0), "p1": (y1, x1), "linewidth": float(self.profile_linewidth)},
        )
        self._clicks.clear()

    def _finish_angle(self) -> None:
        pts = self._clicks
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        item = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#F4C542", width=2))
        self.plot.addItem(item)
        self._annots.append(item)
        payload = {
            "p0": (pts[0][1], pts[0][0]),
            "vertex": (pts[1][1], pts[1][0]),
            "p1": (pts[2][1], pts[2][0]),
        }
        self._annot_data.append({"kind": "angle", **payload, "color": "#F4C542", "width": 2})
        self.toolFinished.emit("angle", payload)
        self._clicks.clear()

    def _finish_roi(self) -> None:
        (x0, y0), (x1, y1) = self._clicks
        w, h = abs(x1 - x0), abs(y1 - y0)
        x, y = min(x0, x1), min(y0, y1)
        if self._roi is not None:
            self.plot.removeItem(self._roi)
        if self.tool == "roi_ellipse":
            self._roi = pg.EllipseROI([x, y], [max(w, 4), max(h, 4)], pen=pg.mkPen("#7CDB6A", width=2))
            kind = "ellipse"
        else:
            self._roi = pg.RectROI([x, y], [max(w, 4), max(h, 4)], pen=pg.mkPen("#7CDB6A", width=2))
            kind = "rect"
        self.plot.addItem(self._roi)
        self._poly_points = None
        self._annot_data.append(
            {"kind": kind, "box": (float(x), float(y), float(x + max(w, 4)), float(y + max(h, 4))), "color": "#7CDB6A"}
        )
        self.toolFinished.emit(self.tool, {"x": x, "y": y, "w": w, "h": h})
        self._clicks.clear()

    def _finish_polygon(self) -> None:
        pts = [(float(x), float(y)) for x, y in self._clicks]
        if len(pts) < 3:
            return
        self._poly_points = pts
        xs = [p[0] for p in pts] + [pts[0][0]]
        ys = [p[1] for p in pts] + [pts[0][1]]
        if self._line is not None:
            self.plot.removeItem(self._line)
        self._line = pg.PlotDataItem(xs, ys, pen=pg.mkPen("#7CDB6A", width=2))
        self.plot.addItem(self._line)
        self._annot_data.append({"kind": "polygon", "points": pts, "color": "#7CDB6A"})
        self.toolFinished.emit("roi_polygon", {"points": pts})
        self._clicks.clear()

    def roi_mask(self) -> np.ndarray | None:
        if self.image.ndim != 2 or self.image.size == 0:
            return None
        if self._poly_points and len(self._poly_points) >= 3:
            return polygon_mask(self.image.shape, self._poly_points)
        if self._roi is None or not widget_alive(self._roi):
            self._roi = None
            return None
        try:
            pos = self._roi.pos()
            size = self._roi.size()
        except Exception:
            return None
        h, w = self.image.shape
        yy, xx = np.ogrid[:h, :w]
        x0, y0 = float(pos.x()), float(pos.y())
        rw, rh = float(size.x()), float(size.y())
        if isinstance(self._roi, pg.EllipseROI):
            cx, cy = x0 + rw / 2, y0 + rh / 2
            return ((xx - cx) / max(rw / 2, 1e-6)) ** 2 + ((yy - cy) / max(rh / 2, 1e-6)) ** 2 <= 1.0
        return (xx >= x0) & (xx <= x0 + rw) & (yy >= y0) & (yy <= y0 + rh)

    def _update_scale_bar(self, *args) -> None:
        if not widget_alive(self) or not widget_alive(self.plot):
            return
        vr = self.vb.viewRange()
        data_w = abs(vr[0][1] - vr[0][0])
        width_px = max(1.0, self.plot.width())
        self.scale_bar.set_scale(self.pixel_m, data_w, width_px)
        margin = 12
        ow, oh = self.scale_bar.width(), self.scale_bar.height()
        pw, ph = self.plot.width(), self.plot.height()
        pos = self.scale_bar_style.position
        if pos == "bottom_right":
            self.scale_bar.move(max(0, pw - ow - margin), max(0, ph - oh - 8))
        elif pos == "top_left":
            self.scale_bar.move(margin, margin)
        elif pos == "top_right":
            self.scale_bar.move(max(0, pw - ow - margin), margin)
        else:
            self.scale_bar.move(margin, max(0, ph - oh - 8))
        self.viewChanged.emit()

    def fit(self) -> None:
        self.vb.autoRange()

    def view_range(self) -> tuple[list[float], list[float]]:
        return self.vb.viewRange()

    def set_view_range(self, x_range, y_range) -> None:
        self.vb.setRange(xRange=x_range, yRange=y_range, padding=0)

    def set_mask_overlay(self, mask: np.ndarray | None) -> None:
        from openvelox.processing.fft import mask_overlay_rgba

        if self._mask_item is None:
            self._mask_item = pg.ImageItem()
            self._mask_item.setZValue(12)
            self.plot.addItem(self._mask_item)
        if mask is None:
            self._mask_item.clear()
            return
        rgba = mask_overlay_rgba(mask)
        self._mask_item.setImage(rgba, autoLevels=False)

    def clear_fft_mask(self) -> None:
        if self._fft_roi is not None:
            try:
                self.plot.removeItem(self._fft_roi)
            except Exception:
                pass
            self._fft_roi = None
        if self._mask_item is not None:
            try:
                self._mask_item.clear()
            except Exception:
                pass

    def place_fft_roi(self, kind: str = "circle", radius: float = 20.0, inner: float = 6.0, center=None) -> None:
        h, w = self.image.shape[:2] if self.image.ndim >= 2 else (8, 8)
        cy, cx = center if center is not None else (h / 2.0, w / 2.0)
        self.clear_fft_mask()
        r = max(4.0, float(radius))
        if kind == "rect":
            self._fft_roi = pg.RectROI([cx - r, cy - r], [2 * r, 2 * r], pen=pg.mkPen("#00A3E0", width=2))
        else:
            self._fft_roi = pg.CircleROI([cx - r, cy - r], [2 * r, 2 * r], pen=pg.mkPen("#00A3E0", width=2))
        self._fft_roi.sigRegionChangeFinished.connect(self._emit_fft_mask)
        self.plot.addItem(self._fft_roi)
        self._emit_fft_mask()

    def fft_roi_params(self) -> dict | None:
        if self._fft_roi is None:
            return None
        try:
            pos = self._fft_roi.pos()
            size = self._fft_roi.size()
        except Exception:
            return None
        cx = float(pos.x()) + float(size.x()) / 2.0
        cy = float(pos.y()) + float(size.y()) / 2.0
        return {
            "center": (cy, cx),
            "radius": float(size.x()) / 2.0,
            "width": float(size.x()),
            "height": float(size.y()),
        }

    def _emit_fft_mask(self) -> None:
        params = self.fft_roi_params()
        if params is not None:
            self.fftMaskChanged.emit(params)
