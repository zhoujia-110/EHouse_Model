"""Standalone DXF preprocessing workbench GUI."""

from __future__ import annotations

from pathlib import Path
import traceback

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolBox,
    QVBoxLayout,
    QWidget,
)

from ehouse_model.dxf_preprocessor import (
    DxfPreprocessModel,
    PreprocessOptions,
    PreprocessPreview,
)
from ehouse_model.dxf_reader import DxfSegment2D, Point2D

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DxfOverlayPreview(QGraphicsView):
    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setMinimumSize(680, 460)
        self._original: tuple[DxfSegment2D, ...] = ()
        self._current: tuple[DxfSegment2D, ...] = ()
        self._preview: PreprocessPreview | None = None
        self._view_bounds = QRectF(0, 0, 1, 1)
        self._auto_fit = True
        self._zoom_level = 0
        self._is_panning = False
        self._last_pan_position = None
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def set_data(
        self,
        *,
        original: tuple[DxfSegment2D, ...],
        current: tuple[DxfSegment2D, ...],
        preview: PreprocessPreview | None,
        reset_view: bool = False,
    ) -> None:
        self._original = original
        self._current = current
        self._preview = preview
        if reset_view:
            self._auto_fit = True
            self._zoom_level = 0
        self._redraw()

    def fit_to_view(self) -> None:
        self._auto_fit = True
        self._zoom_level = 0
        if self._view_bounds.isValid() and not self._view_bounds.isNull():
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def _redraw(self) -> None:
        self.scene.clear()
        if not self._original:
            self.scene.addText("请选择DXF图纸")
            return

        original_pen = _cosmetic_pen("#cbd5e1", 0.0)
        current_pen = _cosmetic_pen("#16a34a", 0.0)
        output_pen = _cosmetic_pen("#0891b2", 0.0)
        removed_pen = _cosmetic_pen("#dc2626", 1.8)
        trimmed_pen = _cosmetic_pen("#f59e0b", 2.0)

        _draw_segments(self.scene, self._original, original_pen)
        if self._preview is None:
            _draw_segments(self.scene, self._current, current_pen)
        else:
            _draw_segments(self.scene, self._preview.output_segments, output_pen)
            _draw_segments(self.scene, self._preview.removed_segments, removed_pen)
            _draw_segments(self.scene, self._preview.trimmed_segments, trimmed_pen)

        bounds = _segments_bounds(
            [
                *self._original,
                *self._current,
                *(self._preview.output_segments if self._preview else ()),
                *(self._preview.removed_segments if self._preview else ()),
                *(self._preview.trimmed_segments if self._preview else ()),
            ]
        )
        margin = max(max(bounds.width(), bounds.height()) * 0.04, 10.0)
        self._view_bounds = bounds.adjusted(-margin, -margin, margin, margin)
        self.scene.setSceneRect(self._view_bounds)
        if self._auto_fit:
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._auto_fit and self._view_bounds.isValid() and not self._view_bounds.isNull():
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._original:
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            event.accept()
            return
        next_zoom = self._zoom_level + (1 if delta > 0 else -1)
        if not -8 <= next_zoom <= 28:
            event.accept()
            return

        factor = 1.18 if delta > 0 else 1 / 1.18
        self._auto_fit = False
        self._zoom_level = next_zoom
        self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            self.fit_to_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._last_pan_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._is_panning and self._last_pan_position is not None:
            delta = event.position() - self._last_pan_position
            self._last_pan_position = event.position()
            self._auto_fit = False
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._is_panning and event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self._last_pan_position = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreprocessWorkbenchWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DXF 预处理工作台")
        self.setMinimumSize(1280, 760)
        self.resize(1500, 900)
        self.model: DxfPreprocessModel | None = None
        self.current_preview: PreprocessPreview | None = None

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择需要预处理的DXF图纸")
        browse_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton), "选择DXF")
        browse_button.clicked.connect(self.choose_dxf)
        load_button = QPushButton("加载")
        load_button.clicked.connect(self.load_from_path)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("原始DXF:"))
        top_layout.addWidget(self.path_edit, 1)
        top_layout.addWidget(browse_button)
        top_layout.addWidget(load_button)

        self.layer_table = QTableWidget(0, 6)
        self.layer_table.setHorizontalHeaderLabels(["提取", "图层", "实体数", "线段数", "实体类型", "颜色"])
        self.layer_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.layer_table.horizontalHeader().setStretchLastSection(True)

        self.preview = DxfOverlayPreview()
        self.status_label = QLabel("未加载图纸")

        left_panel = QWidget()
        left_panel.setMinimumWidth(360)
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("图层列表"))
        left_layout.addWidget(self.layer_table)

        right_panel = self._build_operation_panel()
        right_panel.setMinimumWidth(320)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        legend = QLabel("灰=原图  绿/蓝=当前或预览保留  红=候选删除  黄=候选裁剪")
        center_layout.addWidget(legend)
        center_layout.addWidget(self.preview, 1)
        center_layout.addWidget(self.status_label)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([420, 920, 360])

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(150)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.addLayout(top_layout)
        root_layout.addWidget(splitter, 1)
        root_layout.addWidget(QLabel("日志 / 统计"))
        root_layout.addWidget(self.log_edit)
        self.setCentralWidget(root)
        self._create_menus()

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        open_action = QAction("打开DXF", self)
        open_action.triggered.connect(self.choose_dxf)
        save_clean_action = QAction("保存清理DXF", self)
        save_clean_action.triggered.connect(self.save_clean_dxf)
        save_overlay_action = QAction("保存Overlay", self)
        save_overlay_action.triggered.connect(self.save_overlay_dxf)
        save_report_action = QAction("保存报告CSV", self)
        save_report_action.triggered.connect(self.save_report_csv)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        file_menu.addAction(save_clean_action)
        file_menu.addAction(save_overlay_action)
        file_menu.addAction(save_report_action)
        file_menu.addSeparator()
        file_menu.addAction(exit_action)

        edit_menu = self.menuBar().addMenu("编辑")
        apply_action = QAction("应用本步", self)
        apply_action.triggered.connect(self.apply_preview)
        discard_action = QAction("放弃本步", self)
        discard_action.triggered.connect(self.discard_preview)
        undo_action = QAction("撤销上一步", self)
        undo_action.triggered.connect(self.undo_step)
        reset_action = QAction("恢复原图", self)
        reset_action.triggered.connect(self.reset_model)
        edit_menu.addAction(apply_action)
        edit_menu.addAction(discard_action)
        edit_menu.addSeparator()
        edit_menu.addAction(undo_action)
        edit_menu.addAction(reset_action)

        view_menu = self.menuBar().addMenu("视图")
        fit_action = QAction("适配视图", self)
        fit_action.triggered.connect(self.preview.fit_to_view)
        view_menu.addAction(fit_action)

    def _build_operation_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbox = QToolBox()

        layer_page = QWidget()
        layer_layout = QVBoxLayout(layer_page)
        preview_layer_button = QPushButton("生成图层提取预览")
        preview_layer_button.clicked.connect(self.preview_layer_extract)
        layer_layout.addWidget(QLabel("勾选左侧图层后生成预览"))
        layer_layout.addWidget(preview_layer_button)
        layer_layout.addStretch(1)
        toolbox.addItem(layer_page, "图层提取")

        axis_page = QWidget()
        axis_layout = QVBoxLayout(axis_page)
        self.angle_spin = _double_spin(0.1, 15.0, 2.0, 1)
        axis_layout.addWidget(QLabel("角度容差(度)"))
        axis_layout.addWidget(self.angle_spin)
        axis_button = QPushButton("生成轴线过滤预览")
        axis_button.clicked.connect(self.preview_axis)
        axis_layout.addWidget(axis_button)
        axis_layout.addStretch(1)
        toolbox.addItem(axis_page, "仅保留水平/竖直线")

        merge_page = QWidget()
        merge_layout = QVBoxLayout(merge_page)
        self.merge_tol_spin = _double_spin(0.0, 50.0, 1.0, 1)
        self.gap_tol_spin = _double_spin(0.0, 100.0, 5.0, 1)
        merge_layout.addWidget(QLabel("同线容差(mm)"))
        merge_layout.addWidget(self.merge_tol_spin)
        merge_layout.addWidget(QLabel("断裂间隙(mm)"))
        merge_layout.addWidget(self.gap_tol_spin)
        merge_button = QPushButton("生成合并预览")
        merge_button.clicked.connect(self.preview_merge)
        merge_layout.addWidget(merge_button)
        merge_layout.addStretch(1)
        toolbox.addItem(merge_page, "合并重叠/断裂线")

        cross_page = QWidget()
        cross_layout = QVBoxLayout(cross_page)
        self.closure_length_spin = _double_spin(10.0, 1000.0, 300.0, 1)
        self.cross_tol_spin = _double_spin(0.0, 50.0, 5.0, 1)
        cross_layout.addWidget(QLabel("短线最大长度(mm)"))
        cross_layout.addWidget(self.closure_length_spin)
        cross_layout.addWidget(QLabel("交叉容差(mm)"))
        cross_layout.addWidget(self.cross_tol_spin)
        cross_button = QPushButton("生成封口短线预览")
        cross_button.clicked.connect(self.preview_cross_cleanup)
        cross_layout.addWidget(cross_button)
        cross_layout.addStretch(1)
        toolbox.addItem(cross_page, "删除交叉封口短线")

        trim_page = QWidget()
        trim_layout = QVBoxLayout(trim_page)
        self.trim_tol_spin = _double_spin(0.0, 50.0, 5.0, 1)
        self.trim_band_spin = _double_spin(50.0, 2000.0, 300.0, 1)
        self.trim_remainder_spin = _double_spin(0.0, 200.0, 20.0, 1)
        self.tie_breaker_combo = QComboBox()
        self.tie_breaker_combo.addItem("长度接近时保留水平构件", "keep_horizontal")
        self.tie_breaker_combo.addItem("长度接近时保留竖向构件", "keep_vertical")
        trim_layout.addWidget(QLabel("裁剪容差(mm)"))
        trim_layout.addWidget(self.trim_tol_spin)
        trim_layout.addWidget(QLabel("最小构件带长度(mm)"))
        trim_layout.addWidget(self.trim_band_spin)
        trim_layout.addWidget(QLabel("最小残段长度(mm)"))
        trim_layout.addWidget(self.trim_remainder_spin)
        trim_layout.addWidget(self.tie_breaker_combo)
        trim_button = QPushButton("生成让位裁剪预览")
        trim_button.clicked.connect(self.preview_overlap_trim)
        trim_layout.addWidget(trim_button)
        trim_layout.addStretch(1)
        toolbox.addItem(trim_page, "相交构件让位裁剪")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(toolbox)
        layout.addWidget(scroll, 1)

        action_box = QGroupBox("当前步骤")
        action_layout = QVBoxLayout(action_box)
        apply_button = QPushButton("应用本步")
        apply_button.clicked.connect(self.apply_preview)
        discard_button = QPushButton("放弃本步")
        discard_button.clicked.connect(self.discard_preview)
        undo_button = QPushButton("撤销上一步")
        undo_button.clicked.connect(self.undo_step)
        reset_button = QPushButton("恢复原图")
        reset_button.clicked.connect(self.reset_model)
        fit_button = QPushButton("适配视图")
        fit_button.clicked.connect(self.preview.fit_to_view)
        action_layout.addWidget(apply_button)
        action_layout.addWidget(discard_button)
        action_layout.addWidget(undo_button)
        action_layout.addWidget(reset_button)
        action_layout.addWidget(fit_button)
        layout.addWidget(action_box)
        return panel

    def choose_dxf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择DXF图纸", str(PROJECT_ROOT / "drawings"), "DXF 文件 (*.dxf)")
        if path:
            self.path_edit.setText(path)
            self.load_dxf(Path(path))

    def load_from_path(self) -> None:
        text = self.path_edit.text().strip().strip('"')
        if not text:
            self._show_warning("请先选择DXF图纸。")
            return
        self.load_dxf(Path(text))

    def load_dxf(self, path: Path) -> None:
        try:
            self.model = DxfPreprocessModel.load(path)
            self.current_preview = None
            self.path_edit.setText(str(path))
            self._populate_layers()
            self._refresh_preview(reset_view=True)
            non_line_summary = self.model.non_line_type_summary or "无"
            self._log(
                f"已加载 {path}；原始实体 {self.model.original_entity_count}；"
                f"参与识别线段 {len(self.model.original_segments)}；"
                f"未参与识别对象 {self.model.non_line_entity_count}（{non_line_summary}）；"
                f"图层 {len(self.model.layer_stats)}。"
            )
        except Exception as exc:
            self._show_error("加载DXF失败", exc)

    def preview_layer_extract(self) -> None:
        model = self._require_model()
        if model is None:
            return
        layers = self._checked_layers()
        if not layers:
            self._show_warning("请至少勾选一个图层。")
            return
        self._set_preview(model.preview_layer_extract(layers))

    def preview_axis(self) -> None:
        model = self._require_model()
        if model is not None:
            self._set_preview(
                model.preview_keep_axis_aligned(
                    angle_tolerance_degrees=self.angle_spin.value(),
                )
            )

    def preview_merge(self) -> None:
        model = self._require_model()
        if model is not None:
            self._set_preview(
                model.preview_merge_collinear(
                    merge_tolerance=self.merge_tol_spin.value(),
                    gap_tolerance=self.gap_tol_spin.value(),
                    angle_tolerance_degrees=self.angle_spin.value(),
                )
            )

    def preview_cross_cleanup(self) -> None:
        model = self._require_model()
        if model is None:
            return
        options = PreprocessOptions(
            keep_layers=(),
            remove_layer_keywords=(),
            angle_tolerance_degrees=self.angle_spin.value(),
            cross_cleanup_enabled=True,
            closure_max_length=self.closure_length_spin.value(),
            cross_tolerance=self.cross_tol_spin.value(),
            overlap_trim_enabled=False,
        )
        self._set_preview(model.preview_cross_cleanup(options))

    def preview_overlap_trim(self) -> None:
        model = self._require_model()
        if model is None:
            return
        options = PreprocessOptions(
            keep_layers=(),
            remove_layer_keywords=(),
            angle_tolerance_degrees=self.angle_spin.value(),
            cross_cleanup_enabled=False,
            overlap_trim_enabled=True,
            overlap_trim_tolerance=self.trim_tol_spin.value(),
            overlap_trim_min_band_length=self.trim_band_spin.value(),
            overlap_trim_min_remainder=self.trim_remainder_spin.value(),
            overlap_trim_tie_breaker=str(self.tie_breaker_combo.currentData()),
        )
        self._set_preview(model.preview_overlap_trim(options))

    def apply_preview(self) -> None:
        model = self._require_model()
        if model is None or self.current_preview is None:
            self._show_warning("当前没有可应用的预览。")
            return
        summary = self.current_preview.summary
        model.apply_preview(self.current_preview)
        self.current_preview = None
        self._refresh_preview(reset_view=False)
        self._log(f"已应用：{summary}")

    def discard_preview(self) -> None:
        if self.current_preview is None:
            return
        self._log(f"已放弃：{self.current_preview.name}")
        self.current_preview = None
        self._refresh_preview(reset_view=False)

    def undo_step(self) -> None:
        model = self._require_model()
        if model is None:
            return
        if model.undo():
            self.current_preview = None
            self._refresh_preview(reset_view=False)
            self._log("已撤销上一步。")
        else:
            self._show_warning("没有可撤销的步骤。")

    def reset_model(self) -> None:
        model = self._require_model()
        if model is None:
            return
        model.reset()
        self.current_preview = None
        self._refresh_preview(reset_view=True)
        self._log("已恢复原图。")

    def save_clean_dxf(self) -> None:
        model = self._require_model()
        if model is None:
            return
        default = model.input_path.with_name(f"{model.input_path.stem}_clean.dxf")
        path, _ = QFileDialog.getSaveFileName(self, "保存清理DXF", str(default), "DXF 文件 (*.dxf)")
        if path:
            try:
                model.save_clean_dxf(path)
                self._log(f"已保存清理DXF：{path}")
            except Exception as exc:
                self._show_error("保存清理DXF失败", exc)

    def save_overlay_dxf(self) -> None:
        model = self._require_model()
        if model is None:
            return
        default = model.input_path.with_name(f"{model.input_path.stem}_workspace_overlay.dxf")
        path, _ = QFileDialog.getSaveFileName(self, "保存Overlay", str(default), "DXF 文件 (*.dxf)")
        if path:
            try:
                model.save_overlay_dxf(path, self.current_preview)
                self._log(f"已保存Overlay：{path}")
            except Exception as exc:
                self._show_error("保存Overlay失败", exc)

    def save_report_csv(self) -> None:
        model = self._require_model()
        if model is None:
            return
        default = model.input_path.with_name(f"{model.input_path.stem}_preprocess_steps.csv")
        path, _ = QFileDialog.getSaveFileName(self, "保存报告CSV", str(default), "CSV 文件 (*.csv)")
        if path:
            try:
                model.save_report_csv(path)
                self._log(f"已保存报告CSV：{path}")
            except Exception as exc:
                self._show_error("保存报告CSV失败", exc)

    def _populate_layers(self) -> None:
        model = self.model
        if model is None:
            return
        self.layer_table.setRowCount(0)
        for row, stat in enumerate(model.layer_stats):
            self.layer_table.insertRow(row)
            check_item = QTableWidgetItem("")
            check_item.setFlags(check_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            check_item.setCheckState(Qt.CheckState.Checked)
            self.layer_table.setItem(row, 0, check_item)
            self.layer_table.setItem(row, 1, _readonly_item(stat.layer))
            self.layer_table.setItem(row, 2, _readonly_item(str(stat.entity_count)))
            self.layer_table.setItem(row, 3, _readonly_item(str(stat.segment_count)))
            self.layer_table.setItem(row, 4, _readonly_item(", ".join(stat.entity_types)))
            self.layer_table.setItem(row, 5, _readonly_item(", ".join(str(color) for color in stat.colors)))

    def _checked_layers(self) -> tuple[str, ...]:
        layers: list[str] = []
        for row in range(self.layer_table.rowCount()):
            check_item = self.layer_table.item(row, 0)
            layer_item = self.layer_table.item(row, 1)
            if check_item is None or layer_item is None:
                continue
            if check_item.checkState() == Qt.CheckState.Checked:
                layers.append(layer_item.text())
        return tuple(layers)

    def _set_preview(self, preview: PreprocessPreview) -> None:
        self.current_preview = preview
        self._refresh_preview(reset_view=False)
        self._log(preview.summary)

    def _refresh_preview(self, *, reset_view: bool) -> None:
        model = self.model
        if model is None:
            self.preview.set_data(original=(), current=(), preview=None, reset_view=True)
            self.status_label.setText("未加载图纸")
            return
        self.preview.set_data(
            original=model.original_segments,
            current=model.current_segments,
            preview=self.current_preview,
            reset_view=reset_view,
        )
        preview_suffix = ""
        if self.current_preview is not None:
            preview_suffix = f"；当前预览：{self.current_preview.name}"
        self.status_label.setText(
            f"原始实体 {model.original_entity_count}；"
            f"参与识别线段 {len(model.original_segments)}；"
            f"未参与识别对象 {model.non_line_entity_count}；"
            f"当前线段 {len(model.current_segments)}；"
            f"已应用记录 {len(model.applied_records)}{preview_suffix}"
        )

    def _require_model(self) -> DxfPreprocessModel | None:
        if self.model is None:
            self._show_warning("请先加载DXF图纸。")
            return None
        return self.model

    def _log(self, message: str) -> None:
        self.log_edit.appendPlainText(message)

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "提示", message)

    def _show_error(self, title: str, exc: Exception) -> None:
        QMessageBox.critical(self, title, f"{exc}\n\n{traceback.format_exc()}")


def _double_spin(
    minimum: float,
    maximum: float,
    value: float,
    decimals: int,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(1.0)
    spin.setValue(value)
    return spin


def _readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def _cosmetic_pen(color: str, width: float) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCosmetic(True)
    return pen


def _draw_segments(
    scene: QGraphicsScene,
    segments: tuple[DxfSegment2D, ...] | list[DxfSegment2D],
    pen: QPen,
) -> None:
    for segment in segments:
        scene.addLine(segment.start[0], segment.start[1], segment.end[0], segment.end[1], pen)


def _segments_bounds(segments: list[DxfSegment2D]) -> QRectF:
    if not segments:
        return QRectF(0, 0, 1, 1)
    xs = [point[0] for segment in segments for point in (segment.start, segment.end)]
    ys = [point[1] for segment in segments for point in (segment.start, segment.end)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return QRectF(min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0))


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = PreprocessWorkbenchWindow()
    window.showMaximized()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
