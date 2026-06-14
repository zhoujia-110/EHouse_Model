"""PySide6 GUI for the first base-only workflow."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ehouse_model.base_processing import (
    BaseExtractionResult,
    BaseProcessingOptions,
    export_base_staad,
)
from ehouse_model.correction_tools import (
    CORRECTION_CLUSTER_REALIGN,
    CORRECTION_LOCAL_PATCH,
    CORRECTION_SHORT_MEMBER,
    CorrectionStep,
    extract_base_with_correction_steps,
)
from ehouse_model.domain import Member2D, Node2D
from ehouse_model.dxf_reader import Point2D
from ehouse_model.face_extractor import FaceExtractionOptions
from ehouse_model.face_model import FaceModel, write_face_model_json

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MM_PER_METER = 1000.0


@dataclass(frozen=True, slots=True)
class _ModelSnapshot:
    face_model: FaceModel | None
    outline_segments: tuple[tuple[Point2D, Point2D], ...]
    origin_source: Point2D | None
    correction_steps: tuple[CorrectionStep, ...]
    selected_node_id: str | None
    selected_member_id: str | None
    label: str


@dataclass(frozen=True, slots=True)
class _ModelDelta:
    node_ids: tuple[str, ...]
    member_ids: tuple[str, ...]


class CenterlinePreview(QGraphicsView):
    node_clicked = Signal(str)
    member_clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setMinimumSize(560, 360)
        self._model: FaceModel | None = None
        self._outline_segments: tuple[tuple[Point2D, Point2D], ...] = ()
        self._highlighted_node_id: str | None = None
        self._highlighted_member_id: str | None = None
        self._view_bounds = QRectF(0, 0, 1, 1)
        self._pick_radius_pixels = 10.0
        self._member_pick_radius_pixels = 8.0
        self._auto_fit = True
        self._zoom_level = 0
        self._is_panning = False
        self._last_pan_position = None
        self._space_pressed = False
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_face_model(self, model: FaceModel | None, *, reset_view: bool = False) -> None:
        self._model = model
        if reset_view:
            self._auto_fit = True
            self._zoom_level = 0
        self._redraw()

    def set_outline_segments(self, segments: tuple[tuple[Point2D, Point2D], ...]) -> None:
        self._outline_segments = segments
        self._redraw()

    def fit_to_view(self) -> None:
        if self._view_bounds.isValid() and not self._view_bounds.isNull():
            self._auto_fit = True
            self._zoom_level = 0
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def set_highlighted_node(self, node_id: str | None) -> None:
        self._highlighted_node_id = node_id
        if node_id is not None:
            self._highlighted_member_id = None
        self._redraw()

    def set_highlighted_member(self, member_id: str | None) -> None:
        self._highlighted_member_id = member_id
        if member_id is not None:
            self._highlighted_node_id = None
        self._redraw()

    def _redraw(self) -> None:
        self.scene.clear()
        model = self._model
        if model is None or not model.nodes:
            self.scene.addText("尚未识别底座中心线")
            return

        nodes = {node.id: node for node in model.nodes}
        outline_pen = QPen(QColor("#cbd5e1"))
        outline_pen.setWidthF(0)
        outline_pen.setCosmetic(True)
        line_pen = QPen(QColor("#4b5563"))
        line_pen.setWidthF(0)
        line_pen.setCosmetic(True)
        node_pen = QPen(QColor("#111827"))
        node_pen.setWidthF(0)
        node_pen.setCosmetic(True)
        node_brush = QBrush(QColor("#111827"))

        for start, end in self._outline_segments:
            self.scene.addLine(start[0], start[1], end[0], end[1], outline_pen)

        for member in model.members:
            start = nodes.get(member.start_node_id)
            end = nodes.get(member.end_node_id)
            if start is None or end is None:
                continue
            self.scene.addLine(start.x, start.y, end.x, end.y, line_pen)

        highlighted_member = next(
            (member for member in model.members if member.id == self._highlighted_member_id),
            None,
        )
        if highlighted_member is not None:
            start = nodes.get(highlighted_member.start_node_id)
            end = nodes.get(highlighted_member.end_node_id)
            if start is not None and end is not None:
                member_pen = QPen(QColor("#dc2626"))
                member_pen.setWidthF(2.4)
                member_pen.setCosmetic(True)
                self.scene.addLine(start.x, start.y, end.x, end.y, member_pen)
                label = self.scene.addText(highlighted_member.id)
                label.setDefaultTextColor(QColor("#dc2626"))
                label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                label.setPos((start.x + end.x) / 2.0, (start.y + end.y) / 2.0)

        for node in model.nodes:
            marker = self.scene.addEllipse(-2.2, -2.2, 4.4, 4.4, node_pen, node_brush)
            marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            marker.setPos(node.x, node.y)
            marker.setToolTip(node.id)

        highlighted = nodes.get(self._highlighted_node_id or "")
        if highlighted is not None:
            highlight_pen = QPen(QColor("#dc2626"))
            highlight_pen.setWidthF(1.4)
            highlight_pen.setCosmetic(True)
            highlight = self.scene.addEllipse(-6.0, -6.0, 12.0, 12.0, highlight_pen)
            highlight.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            highlight.setPos(highlighted.x, highlighted.y)
            label = self.scene.addText(highlighted.id)
            label.setDefaultTextColor(QColor("#dc2626"))
            label.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            label.setPos(highlighted.x, highlighted.y)

        bounds = _model_bounds(model, self._outline_segments)
        margin = max(max(bounds.width(), bounds.height()) * 0.05, 0.5)
        self._view_bounds = bounds.adjusted(-margin, -margin, margin, margin)
        self.scene.setSceneRect(self._view_bounds)
        if self._auto_fit:
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._auto_fit and self._view_bounds.isValid() and not self._view_bounds.isNull():
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._model is None:
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
        self.setFocus()
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_pressed
        ):
            self._is_panning = True
            self._last_pan_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            node_id = self._nearest_node_id(event.position())
            if node_id is not None:
                self.set_highlighted_node(node_id)
                self.node_clicked.emit(node_id)
                event.accept()
                return
            member_id = self._nearest_member_id(event.position())
            if member_id is not None:
                self.set_highlighted_member(member_id)
                self.member_clicked.emit(member_id)
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
        if self._is_panning and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.LeftButton,
        ):
            self._is_panning = False
            self._last_pan_position = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._space_pressed else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            if not self._is_panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _nearest_node_id(self, view_position) -> str | None:  # type: ignore[no-untyped-def]
        model = self._model
        if model is None:
            return None

        best_node_id: str | None = None
        best_distance_squared = self._pick_radius_pixels * self._pick_radius_pixels
        for node in model.nodes:
            node_view_position = self.mapFromScene(node.x, node.y)
            dx = node_view_position.x() - view_position.x()
            dy = node_view_position.y() - view_position.y()
            distance_squared = dx * dx + dy * dy
            if distance_squared <= best_distance_squared:
                best_distance_squared = distance_squared
                best_node_id = node.id
        return best_node_id

    def _nearest_member_id(self, view_position) -> str | None:  # type: ignore[no-untyped-def]
        model = self._model
        if model is None:
            return None

        nodes = {node.id: node for node in model.nodes}
        best_member_id: str | None = None
        limit = self._member_pick_radius_pixels * self._member_pick_radius_pixels
        best_distance_squared = limit
        for member in model.members:
            start = nodes.get(member.start_node_id)
            end = nodes.get(member.end_node_id)
            if start is None or end is None:
                continue

            start_view = self.mapFromScene(start.x, start.y)
            end_view = self.mapFromScene(end.x, end.y)
            distance_squared = _distance_squared_to_segment(
                view_position.x(),
                view_position.y(),
                float(start_view.x()),
                float(start_view.y()),
                float(end_view.x()),
                float(end_view.y()),
            )
            if distance_squared <= best_distance_squared:
                best_distance_squared = distance_squared
                best_member_id = member.id
        return best_member_id


class LargePreviewDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("中心线放大查看")
        self.resize(1180, 760)

        layout = QVBoxLayout(self)
        button_row = QHBoxLayout()
        fit_button = QPushButton("适配窗口")
        fit_button.clicked.connect(self.fit_to_view)
        button_row.addWidget(fit_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.preview = CenterlinePreview()
        self.preview.setMinimumSize(980, 620)
        layout.addWidget(self.preview, 1)

    def set_preview_data(
        self,
        model: FaceModel | None,
        outline_segments: tuple[tuple[Point2D, Point2D], ...],
    ) -> None:
        self.preview.set_outline_segments(outline_segments)
        self.preview.set_face_model(model, reset_view=True)

    def set_highlighted_node(self, node_id: str | None) -> None:
        self.preview.set_highlighted_node(node_id)

    def set_highlighted_member(self, member_id: str | None) -> None:
        self.preview.set_highlighted_member(member_id)

    def fit_to_view(self) -> None:
        self.preview.fit_to_view()


class CorrectionToolDialog(QDialog):
    preview_requested = Signal()

    def __init__(
        self,
        tool_kind: str,
        title: str,
        extraction_options: FaceExtractionOptions,
        base_options: BaseProcessingOptions,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tool_kind = tool_kind
        self.extraction_options = extraction_options
        self.base_options = base_options
        self.preview_result: BaseExtractionResult | None = None
        self.preview_step: CorrectionStep | None = None
        self.setWindowTitle(title)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QGridLayout()
        layout.addLayout(form)

        row = 0
        if tool_kind == CORRECTION_LOCAL_PATCH:
            self.local_radius_spin = _distance_spin(base_options.local_patch_radius / MM_PER_METER)
            self.local_width_tolerance_spin = _distance_spin(base_options.local_patch_width_tolerance / MM_PER_METER)
            self.local_width_ratio_spin = _ratio_spin(base_options.local_patch_width_tolerance_ratio, 0.0, 1.0, 0.01)
            self.local_max_candidates_spin = _integer_spin(1, 20, base_options.local_patch_max_candidates_per_point)
            row = _add_spin_row(form, row, "搜索半径(m)", self.local_radius_spin)
            row = _add_spin_row(form, row, "宽度容差(m)", self.local_width_tolerance_spin)
            row = _add_spin_row(form, row, "宽度容差比例", self.local_width_ratio_spin)
            row = _add_spin_row(form, row, "每点最多新增", self.local_max_candidates_spin)
        elif tool_kind == CORRECTION_SHORT_MEMBER:
            cleanup = base_options.centerline_cleanup_options
            self.short_radius_spin = _distance_spin(cleanup.short_member_radius / MM_PER_METER)
            self.short_max_length_spin = _distance_spin(cleanup.short_member_max_length / MM_PER_METER)
            self.short_width_ratio_spin = _ratio_spin(cleanup.short_member_max_width_to_length_ratio, 0.05, 10.0, 0.1)
            self.short_overlap_ratio_spin = _ratio_spin(cleanup.min_overlap_ratio, 0.05, 1.0, 0.05)
            self.short_max_candidates_spin = _integer_spin(1, 20, cleanup.short_member_max_candidates_per_point)
            row = _add_spin_row(form, row, "搜索半径(m)", self.short_radius_spin)
            row = _add_spin_row(form, row, "最大长度(m)", self.short_max_length_spin)
            row = _add_spin_row(form, row, "宽长比上限", self.short_width_ratio_spin)
            row = _add_spin_row(form, row, "最小重叠比例", self.short_overlap_ratio_spin)
            row = _add_spin_row(form, row, "每点最多新增", self.short_max_candidates_spin)
        elif tool_kind == CORRECTION_CLUSTER_REALIGN:
            cleanup = base_options.centerline_cleanup_options
            self.cluster_radius_spin = _distance_spin(cleanup.cluster_realign_radius / MM_PER_METER)
            self.cluster_search_spin = _integer_spin(1, 80, cleanup.cluster_realign_max_search_candidates)
            self.cluster_angle_spin = _angle_spin(cleanup.angle_tolerance_degrees)
            self.cluster_orientation_combo = QComboBox()
            self.cluster_orientation_combo.addItem("自动", "auto")
            self.cluster_orientation_combo.addItem("水平", "horizontal")
            self.cluster_orientation_combo.addItem("竖向", "vertical")
            row = _add_spin_row(form, row, "搜索半径(m)", self.cluster_radius_spin)
            row = _add_spin_row(form, row, "最多搜索候选", self.cluster_search_spin)
            row = _add_spin_row(form, row, "角度容差(度)", self.cluster_angle_spin)
            form.addWidget(QLabel("重选方向"), row, 0)
            form.addWidget(self.cluster_orientation_combo, row, 1)
        else:
            raise ValueError(f"unknown correction tool: {tool_kind}")

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("生成预览")
        self.preview_button.clicked.connect(self.preview_requested.emit)
        self.apply_button = QPushButton("应用")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.accept)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.preview_button)
        button_row.addStretch()
        button_row.addWidget(self.apply_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

    def build_step(self, point: Point2D) -> CorrectionStep:
        base_options = self.base_options
        cleanup = base_options.centerline_cleanup_options
        extraction_options = self.extraction_options

        if self.tool_kind == CORRECTION_LOCAL_PATCH:
            base_options = replace(
                base_options,
                local_patch_radius=self.local_radius_spin.value() * MM_PER_METER,
                local_patch_width_tolerance=self.local_width_tolerance_spin.value() * MM_PER_METER,
                local_patch_width_tolerance_ratio=self.local_width_ratio_spin.value(),
                local_patch_max_candidates_per_point=self.local_max_candidates_spin.value(),
            )
        elif self.tool_kind == CORRECTION_SHORT_MEMBER:
            cleanup = replace(
                cleanup,
                min_overlap_ratio=self.short_overlap_ratio_spin.value(),
                short_member_radius=self.short_radius_spin.value() * MM_PER_METER,
                short_member_max_length=self.short_max_length_spin.value() * MM_PER_METER,
                short_member_max_width_to_length_ratio=self.short_width_ratio_spin.value(),
                short_member_max_candidates_per_point=self.short_max_candidates_spin.value(),
            )
            base_options = replace(base_options, centerline_cleanup_options=cleanup)
        elif self.tool_kind == CORRECTION_CLUSTER_REALIGN:
            cleanup = replace(
                cleanup,
                angle_tolerance_degrees=self.cluster_angle_spin.value(),
                cluster_realign_radius=self.cluster_radius_spin.value() * MM_PER_METER,
                cluster_realign_max_search_candidates=self.cluster_search_spin.value(),
                cluster_realign_orientation=str(self.cluster_orientation_combo.currentData()),
            )
            base_options = replace(base_options, centerline_cleanup_options=cleanup)

        return CorrectionStep(
            kind=self.tool_kind,
            point=point,
            extraction_options=extraction_options,
            base_options=base_options,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("E-House 底座几何提取工具")
        self.resize(1220, 820)
        self.face_model: FaceModel | None = None
        self.outline_segments: tuple[tuple[Point2D, Point2D], ...] = ()
        self.large_preview_dialog: LargePreviewDialog | None = None
        self.origin_source: Point2D | None = None
        self.correction_steps: list[CorrectionStep] = []
        self.undo_stack: list[_ModelSnapshot] = []
        self.initial_extraction_options = FaceExtractionOptions()
        self.initial_base_options = BaseProcessingOptions()
        self._updating_tables = False

        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)

        self._build_input_panel(main_layout)
        self._build_result_panel(main_layout)
        self._build_log_panel(main_layout)
        self.preview.set_face_model(None)

    def _build_input_panel(self, main_layout: QVBoxLayout) -> None:
        box = QGroupBox("底座识别与导出")
        grid = QGridLayout(box)

        self.dxf_path_edit = QLineEdit(str(_first_dxf_path()))
        self.std_path_edit = QLineEdit(str(PROJECT_ROOT / "output" / "base" / "geometry.std"))
        self.max_pair_width_spin = _optional_distance_spin()
        self.max_pair_width_spin.setSpecialValueText("自动")
        self.pair_width_ratio_spin = _ratio_spin(0.35, 0.1, 2.0, 0.05)
        self.snap_tolerance_spin = _distance_spin(0.2)

        grid.addWidget(QLabel("底座DXF"), 0, 0)
        grid.addWidget(_path_row(self.dxf_path_edit, self.select_dxf_file), 0, 1, 1, 3)
        grid.addWidget(QLabel("输出STD"), 1, 0)
        grid.addWidget(_path_row(self.std_path_edit, self.select_std_file), 1, 1, 1, 3)
        grid.addWidget(QLabel("最大配对宽度(m)"), 2, 0)
        grid.addWidget(self.max_pair_width_spin, 2, 1)
        grid.addWidget(QLabel("最大延伸上限(m)"), 2, 2)
        grid.addWidget(self.snap_tolerance_spin, 2, 3)
        grid.addWidget(QLabel("宽长比上限"), 3, 0)
        grid.addWidget(self.pair_width_ratio_spin, 3, 1)

        button_row = QHBoxLayout()
        recognize_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "识别底座")
        recognize_button.clicked.connect(self.recognize_base)
        local_patch_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "局部补识别")
        local_patch_button.clicked.connect(self.local_patch_recognize)
        short_member_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight), "短构件修正")
        short_member_button.clicked.connect(self.short_member_fix)
        cluster_realign_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp), "邻近错位修正")
        cluster_realign_button.clicked.connect(self.cluster_realign_fix)
        undo_button = QPushButton("撤销上一步")
        undo_button.clicked.connect(self.undo_last_action)
        save_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "保存修正")
        save_button.clicked.connect(self.save_corrections)
        export_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon), "导出STD")
        export_button.clicked.connect(self.export_std)
        open_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "打开输出文件夹")
        open_button.clicked.connect(self.open_output_folder)
        button_row.addWidget(recognize_button)
        button_row.addWidget(local_patch_button)
        button_row.addWidget(short_member_button)
        button_row.addWidget(cluster_realign_button)
        button_row.addWidget(undo_button)
        button_row.addWidget(save_button)
        button_row.addWidget(export_button)
        button_row.addWidget(open_button)
        button_row.addStretch()
        grid.addLayout(button_row, 4, 0, 1, 4)

        main_layout.addWidget(box)

    def _build_result_panel(self, main_layout: QVBoxLayout) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        preview_box = QGroupBox("中心线预览")
        preview_layout = QVBoxLayout(preview_box)
        preview_tools = QHBoxLayout()
        fit_preview_button = QPushButton("适配窗口")
        fit_preview_button.clicked.connect(self.fit_preview_to_view)
        large_preview_button = QPushButton("放大查看")
        large_preview_button.clicked.connect(self.open_large_preview)
        preview_tools.addWidget(fit_preview_button)
        preview_tools.addWidget(large_preview_button)
        preview_tools.addStretch()
        preview_layout.addLayout(preview_tools)
        self.preview = CenterlinePreview()
        self.preview.node_clicked.connect(self.select_node_by_id)
        self.preview.member_clicked.connect(self.select_member_by_id)
        preview_layout.addWidget(self.preview)
        splitter.addWidget(preview_box)

        table_box = QGroupBox("节点坐标表")
        table_layout = QVBoxLayout(table_box)
        self.node_table = QTableWidget(0, 3)
        self.node_table.setHorizontalHeaderLabels(["节点", "X", "Z"])
        self.node_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.node_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.node_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.node_table.itemChanged.connect(self.node_table_item_changed)
        self.node_table.currentItemChanged.connect(self.node_table_current_item_changed)
        table_layout.addWidget(self.node_table)
        splitter.addWidget(table_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)

        members_box = QGroupBox("构件列表")
        members_layout = QVBoxLayout(members_box)
        self.member_table = QTableWidget(0, 3)
        self.member_table.setHorizontalHeaderLabels(["构件", "起点节点", "终点节点"])
        self.member_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.member_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.member_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.member_table.currentItemChanged.connect(self.member_table_current_item_changed)
        members_layout.addWidget(self.member_table)
        main_layout.addWidget(members_box)

    def _build_log_panel(self, main_layout: QVBoxLayout) -> None:
        box = QGroupBox("日志 / 警告")
        layout = QVBoxLayout(box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setFixedHeight(120)
        layout.addWidget(self.log)
        main_layout.addWidget(box)

    def select_dxf_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择底座DXF", str(PROJECT_ROOT), "DXF 文件 (*.dxf)")
        if path:
            self.dxf_path_edit.setText(path)

    def select_std_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "选择STD输出位置", self.std_path_edit.text(), "STAAD 文件 (*.std)")
        if path:
            self.std_path_edit.setText(path)

    def recognize_base(self) -> None:
        try:
            self.correction_steps = []
            self.undo_stack = []
            self.initial_extraction_options = self._current_extraction_options()
            self.initial_base_options = self._current_base_options()
            result = self._extract_current_base()
            self._apply_extraction_result(result, reset_view=True)
            self.select_origin_node_row()
            self._log(
                f"识别完成：节点 {len(self.face_model.nodes)} 个，构件 {len(self.face_model.members)} 个，"
                f"吸附延伸端点 {result.snap_count} 个，"
                f"同线合并 {result.centerline_cleanup_merged_group_count} 组，"
                f"裁剪端部构件 {result.terminal_stub_removed_count} 根，"
                f"原点=({result.origin[0]:.4f}, {result.origin[1]:.4f})m。"
            )
            if self.face_model.warnings:
                for warning in self.face_model.warnings:
                    self._log(f"{warning.id} {warning.level} {warning.code}: {warning.message}")
        except Exception as exc:
            self._show_error("识别底座失败", exc)

    def local_patch_recognize(self) -> None:
        self._run_correction_tool(CORRECTION_LOCAL_PATCH, "局部补识别")

    def short_member_fix(self) -> None:
        self._run_correction_tool(CORRECTION_SHORT_MEMBER, "短构件修正")

    def cluster_realign_fix(self) -> None:
        self._run_correction_tool(CORRECTION_CLUSTER_REALIGN, "邻近错位修正")

    def _run_correction_tool(self, tool_kind: str, title: str) -> None:
        selected = self._selected_node_patch_point(title)
        if selected is None:
            return

        node_id, x_meter, z_meter, patch_point = selected
        dialog = CorrectionToolDialog(
            tool_kind,
            title,
            self.initial_extraction_options,
            self.initial_base_options,
            self,
        )

        def generate_preview() -> None:
            try:
                step = dialog.build_step(patch_point)
                result = self._extract_with_correction_steps(
                    tuple([*self.correction_steps, step]),
                    write_outputs=False,
                )
                dialog.preview_step = step
                dialog.preview_result = result
                dialog.apply_button.setEnabled(True)
                self._show_correction_preview(result)
                self._log(self._correction_preview_summary(title, result, _model_delta(self.face_model, result.face_model)))
            except Exception as exc:
                dialog.apply_button.setEnabled(False)
                self._restore_current_preview()
                self._show_error(f"{title}预览失败", exc)

        dialog.preview_requested.connect(generate_preview)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._restore_current_preview()
            return

        if dialog.preview_step is None or dialog.preview_result is None:
            self._restore_current_preview()
            QMessageBox.information(self, "尚未生成预览", "请先生成预览，确认结果后再应用。")
            return

        try:
            before_model = self.face_model
            self._push_history(title)
            self.correction_steps.append(dialog.preview_step)
            result = self._extract_with_correction_steps(tuple(self.correction_steps), write_outputs=True)
            delta = _model_delta(before_model, result.face_model)
            self._apply_extraction_result(result, reset_view=False)
            self._jump_to_delta(delta, fallback_point=(x_meter, z_meter))
            self._log(self._correction_apply_summary(title, node_id, result, delta))
        except Exception as exc:
            self.undo_last_action(silent=True)
            self._show_error(f"{title}应用失败", exc)

    def _correction_preview_summary(
        self,
        title: str,
        result: BaseExtractionResult,
        delta: _ModelDelta,
    ) -> str:
        return (
            f"{title}预览：节点 {len(result.face_model.nodes)} 个，构件 {len(result.face_model.members)} 个，"
            f"局部新增 {result.local_patch_added_count}，短构件新增 {result.short_member_added_count}，"
            f"邻近替换 {result.cluster_realign_replaced_group_count} 组；"
            f"新增节点 {_format_id_list(delta.node_ids)}，新增构件 {_format_id_list(delta.member_ids)}。"
        )

    def _correction_apply_summary(
        self,
        title: str,
        node_id: str,
        result: BaseExtractionResult,
        delta: _ModelDelta,
    ) -> str:
        return (
            f"{title}已应用：以节点 {node_id} 附近修正，"
            f"局部新增 {result.local_patch_added_count}，短构件新增 {result.short_member_added_count}，"
            f"邻近替换 {result.cluster_realign_replaced_group_count} 组，"
            f"当前节点 {len(result.face_model.nodes)} 个，构件 {len(result.face_model.members)} 个；"
            f"新增节点 {_format_id_list(delta.node_ids)}，新增构件 {_format_id_list(delta.member_ids)}。"
        )

    def _jump_to_delta(self, delta: _ModelDelta, *, fallback_point: tuple[float, float]) -> None:
        if delta.node_ids:
            self.select_node_by_id(delta.node_ids[0])
        if delta.member_ids:
            self.select_member_by_id(delta.member_ids[0])
        if not delta.node_ids and not delta.member_ids:
            self._select_nearest_node(*fallback_point)

    def _push_history(self, label: str) -> None:
        self.undo_stack.append(
            _ModelSnapshot(
                face_model=self.face_model,
                outline_segments=self.outline_segments,
                origin_source=self.origin_source,
                correction_steps=tuple(self.correction_steps),
                selected_node_id=self._current_selected_node_id(),
                selected_member_id=self._current_selected_member_id(),
                label=label,
            )
        )

    def undo_last_action(self, checked: bool = False, *, silent: bool = False) -> None:
        if not self.undo_stack:
            if not silent:
                QMessageBox.information(self, "没有可撤销步骤", "当前没有可撤销的修正或坐标编辑。")
            return

        snapshot = self.undo_stack.pop()
        self.correction_steps = list(snapshot.correction_steps)
        self._set_model_state(
            snapshot.face_model,
            snapshot.outline_segments,
            snapshot.origin_source,
            reset_view=False,
        )
        if snapshot.selected_node_id:
            self.select_node_by_id(snapshot.selected_node_id)
        elif snapshot.selected_member_id:
            self.select_member_by_id(snapshot.selected_member_id)
        if not silent:
            self._log(f"已撤销：{snapshot.label}")

    def _current_selected_node_id(self) -> str | None:
        row = self.node_table.currentRow()
        if row < 0:
            return None
        item = self.node_table.item(row, 0)
        return item.text() if item is not None else None

    def _current_selected_member_id(self) -> str | None:
        row = self.member_table.currentRow()
        if row < 0:
            return None
        item = self.member_table.item(row, 0)
        return item.text() if item is not None else None

    def _extract_current_base(
        self,
    ) -> BaseExtractionResult:
        return self._extract_with_correction_steps(tuple(self.correction_steps), write_outputs=True)

    def _extract_with_correction_steps(
        self,
        correction_steps: tuple[CorrectionStep, ...],
        *,
        write_outputs: bool,
    ) -> BaseExtractionResult:
        dxf_path = Path(self.dxf_path_edit.text())
        output_dir = Path(self.std_path_edit.text()).parent
        return extract_base_with_correction_steps(
            dxf_path,
            face_model_path=output_dir / "face_model.json" if write_outputs else None,
            overlay_path=output_dir / "centerline_overlay.dxf" if write_outputs else None,
            warnings_csv_path=output_dir / "warnings.csv" if write_outputs else None,
            extraction_options=self.initial_extraction_options,
            base_options=self.initial_base_options,
            correction_steps=correction_steps,
        )

    def _current_extraction_options(self) -> FaceExtractionOptions:
        max_pair_width_m = self.max_pair_width_spin.value()
        return FaceExtractionOptions(
            max_pair_width=None if max_pair_width_m == 0 else max_pair_width_m * MM_PER_METER,
            max_pair_width_to_length_ratio=self.pair_width_ratio_spin.value(),
        )

    def _current_base_options(self) -> BaseProcessingOptions:
        return BaseProcessingOptions(
            snap_extend_tolerance=self.snap_tolerance_spin.value() * MM_PER_METER,
        )

    def _apply_extraction_result(self, result: BaseExtractionResult, *, reset_view: bool) -> None:
        self._set_model_state(
            result.face_model,
            result.outline_segments,
            result.origin_source,
            reset_view=reset_view,
        )

    def _set_model_state(
        self,
        face_model: FaceModel | None,
        outline_segments: tuple[tuple[Point2D, Point2D], ...],
        origin_source: Point2D | None,
        *,
        reset_view: bool,
    ) -> None:
        self.face_model = face_model
        self.outline_segments = outline_segments
        self.origin_source = origin_source
        self.preview.set_outline_segments(self.outline_segments)
        self.preview.set_face_model(self.face_model, reset_view=reset_view)
        self._refresh_large_preview(reset_view=reset_view)
        self.populate_tables()

    def _show_correction_preview(self, result: BaseExtractionResult) -> None:
        self.preview.set_outline_segments(result.outline_segments)
        self.preview.set_face_model(result.face_model, reset_view=False)
        if self.large_preview_dialog is not None and self.large_preview_dialog.isVisible():
            self.large_preview_dialog.preview.set_outline_segments(result.outline_segments)
            self.large_preview_dialog.preview.set_face_model(result.face_model, reset_view=False)

    def _restore_current_preview(self) -> None:
        self.preview.set_outline_segments(self.outline_segments)
        self.preview.set_face_model(self.face_model, reset_view=False)
        self._refresh_large_preview(reset_view=False)

    def save_corrections(self) -> None:
        if self.face_model is None:
            QMessageBox.information(self, "没有可保存内容", "请先识别底座DXF。")
            return
        try:
            path = Path(self.std_path_edit.text()).parent / "face_model.json"
            write_face_model_json(self.face_model, path)
            self._log(f"修正结果已保存：{path}")
        except Exception as exc:
            self._show_error("保存修正失败", exc)

    def export_std(self) -> None:
        if self.face_model is None:
            QMessageBox.information(self, "没有可导出内容", "请先识别底座DXF。")
            return
        try:
            std_path = Path(self.std_path_edit.text())
            export_base_staad(self.face_model, std_path)
            self._log(f"STD 已导出：{std_path}")
        except Exception as exc:
            self._show_error("导出STD失败", exc)

    def open_output_folder(self) -> None:
        path = Path(self.std_path_edit.text()).parent
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def populate_tables(self) -> None:
        if self.face_model is None:
            self.node_table.setRowCount(0)
            self.member_table.setRowCount(0)
            return

        self._updating_tables = True
        try:
            self.node_table.setRowCount(0)
            for node in self.face_model.nodes:
                row = self.node_table.rowCount()
                self.node_table.insertRow(row)
                self.node_table.setItem(row, 0, _readonly_item(node.id))
                self.node_table.setItem(row, 1, _editable_number_item(node.x))
                self.node_table.setItem(row, 2, _editable_number_item(node.y))

            self.member_table.setRowCount(0)
            for member in self.face_model.members:
                row = self.member_table.rowCount()
                self.member_table.insertRow(row)
                self.member_table.setItem(row, 0, _readonly_item(member.id))
                self.member_table.setItem(row, 1, _readonly_item(member.start_node_id))
                self.member_table.setItem(row, 2, _readonly_item(member.end_node_id))
        finally:
            self._updating_tables = False

    def node_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_tables or self.face_model is None or item.column() not in (1, 2):
            return

        row = item.row()
        node_id = self.node_table.item(row, 0).text()
        try:
            value = round(float(item.text()), 4)
        except ValueError:
            QMessageBox.warning(self, "坐标格式错误", "节点坐标必须是数字。")
            self.populate_tables()
            return

        old_node = next((node for node in self.face_model.nodes if node.id == node_id), None)
        if old_node is not None:
            old_value = old_node.x if item.column() == 1 else old_node.y
            if abs(old_value - value) <= 1e-9:
                self._updating_tables = True
                try:
                    item.setText(_format4(value))
                finally:
                    self._updating_tables = False
                return
        self._push_history("节点坐标编辑")

        nodes: list[Node2D] = []
        for node in self.face_model.nodes:
            if node.id == node_id:
                x_value = value if item.column() == 1 else node.x
                z_value = value if item.column() == 2 else node.y
                nodes.append(Node2D(id=node.id, x=x_value, y=z_value))
            else:
                nodes.append(node)

        self.face_model = FaceModel(
            source_dxf=self.face_model.source_dxf,
            nodes=tuple(nodes),
            members=self.face_model.members,
            centerline_candidates=self.face_model.centerline_candidates,
            member_sources=self.face_model.member_sources,
            warnings=self.face_model.warnings,
        )

        self._updating_tables = True
        try:
            item.setText(_format4(value))
        finally:
            self._updating_tables = False
        self.preview.set_face_model(self.face_model)
        self._refresh_large_preview(reset_view=False)

    def node_table_current_item_changed(
        self,
        current: QTableWidgetItem | None,
        previous: QTableWidgetItem | None,
    ) -> None:
        if self._updating_tables or self.face_model is None or current is None:
            return
        node_item = self.node_table.item(current.row(), 0)
        node_id = node_item.text() if node_item else None
        self.preview.set_highlighted_node(node_id)
        self._set_large_highlighted_node(node_id)

    def member_table_current_item_changed(
        self,
        current: QTableWidgetItem | None,
        previous: QTableWidgetItem | None,
    ) -> None:
        if self._updating_tables or self.face_model is None or current is None:
            return
        member_item = self.member_table.item(current.row(), 0)
        member_id = member_item.text() if member_item else None
        self.preview.set_highlighted_member(member_id)
        self._set_large_highlighted_member(member_id)

    def select_node_by_id(self, node_id: str) -> None:
        for row in range(self.node_table.rowCount()):
            node_item = self.node_table.item(row, 0)
            if node_item is None or node_item.text() != node_id:
                continue
            self.node_table.selectRow(row)
            self.node_table.setCurrentCell(row, 0)
            self.node_table.scrollToItem(
                node_item,
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )
            self.preview.set_highlighted_node(node_id)
            self._set_large_highlighted_node(node_id)
            return

    def select_member_by_id(self, member_id: str) -> None:
        for row in range(self.member_table.rowCount()):
            member_item = self.member_table.item(row, 0)
            if member_item is None or member_item.text() != member_id:
                continue
            self.member_table.selectRow(row)
            self.member_table.setCurrentCell(row, 0)
            self.member_table.scrollToItem(
                member_item,
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )
            self.preview.set_highlighted_member(member_id)
            self._set_large_highlighted_member(member_id)
            return

    def select_origin_node_row(self) -> None:
        if self.face_model is None:
            return
        for row in range(self.node_table.rowCount()):
            x_item = self.node_table.item(row, 1)
            z_item = self.node_table.item(row, 2)
            node_item = self.node_table.item(row, 0)
            if x_item is None or z_item is None or node_item is None:
                continue
            if abs(float(x_item.text())) <= 1e-9 and abs(float(z_item.text())) <= 1e-9:
                self.node_table.selectRow(row)
                self.node_table.setCurrentCell(row, 0)
                self.preview.set_highlighted_node(node_item.text())
                self._set_large_highlighted_node(node_item.text())
                return

    def _selected_node_for_local_patch(self) -> tuple[str, float, float] | None:
        row = self.node_table.currentRow()
        if row < 0:
            return None
        node_item = self.node_table.item(row, 0)
        x_item = self.node_table.item(row, 1)
        z_item = self.node_table.item(row, 2)
        if node_item is None or x_item is None or z_item is None:
            return None

        try:
            return (node_item.text(), float(x_item.text()), float(z_item.text()))
        except ValueError:
            QMessageBox.warning(self, "坐标格式错误", "当前节点坐标必须是数字。")
            return None

    def _selected_node_patch_point(self, action_name: str) -> tuple[str, float, float, Point2D] | None:
        if self.face_model is None:
            QMessageBox.information(self, f"没有可{action_name}内容", "请先识别底座DXF。")
            return None
        if self.origin_source is None:
            QMessageBox.information(self, "缺少原点信息", "请重新识别底座DXF后再做修正。")
            return None

        selected = self._selected_node_for_local_patch()
        if selected is None:
            QMessageBox.information(self, "未选择节点", "请先在预览图或节点表中选择一个问题节点。")
            return None

        node_id, x_meter, z_meter = selected
        patch_point = (
            self.origin_source[0] + x_meter * MM_PER_METER,
            self.origin_source[1] - z_meter * MM_PER_METER,
        )
        return node_id, x_meter, z_meter, patch_point

    def _log_special_warnings(self, prefixes: tuple[str, ...]) -> None:
        if self.face_model is None:
            return
        for warning in self.face_model.warnings:
            if warning.code.startswith(prefixes):
                self._log(f"{warning.id} {warning.level} {warning.code}: {warning.message}")

    def _select_nearest_node(self, x_meter: float, z_meter: float) -> None:
        if self.face_model is None or not self.face_model.nodes:
            return
        node = min(
            self.face_model.nodes,
            key=lambda item: (item.x - x_meter) * (item.x - x_meter)
            + (item.y - z_meter) * (item.y - z_meter),
        )
        self.select_node_by_id(node.id)

    def fit_preview_to_view(self) -> None:
        self.preview.fit_to_view()

    def open_large_preview(self) -> None:
        if self.face_model is None:
            QMessageBox.information(self, "没有可查看内容", "请先识别底座DXF。")
            return

        if self.large_preview_dialog is None:
            self.large_preview_dialog = LargePreviewDialog(self)
            self.large_preview_dialog.preview.node_clicked.connect(self.select_node_by_id)
            self.large_preview_dialog.preview.member_clicked.connect(self.select_member_by_id)

        self.large_preview_dialog.set_preview_data(self.face_model, self.outline_segments)
        self.large_preview_dialog.show()
        self.large_preview_dialog.raise_()
        self.large_preview_dialog.activateWindow()

    def _refresh_large_preview(self, *, reset_view: bool) -> None:
        if self.large_preview_dialog is None or not self.large_preview_dialog.isVisible():
            return
        self.large_preview_dialog.preview.set_outline_segments(self.outline_segments)
        self.large_preview_dialog.preview.set_face_model(self.face_model, reset_view=reset_view)

    def _set_large_highlighted_node(self, node_id: str | None) -> None:
        if self.large_preview_dialog is not None and self.large_preview_dialog.isVisible():
            self.large_preview_dialog.set_highlighted_node(node_id)

    def _set_large_highlighted_member(self, member_id: str | None) -> None:
        if self.large_preview_dialog is not None and self.large_preview_dialog.isVisible():
            self.large_preview_dialog.set_highlighted_member(member_id)

    def _log(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _show_error(self, title: str, exc: Exception) -> None:
        self.log.appendPlainText(traceback.format_exc())
        QMessageBox.critical(self, title, str(exc))


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


def _path_row(edit: QLineEdit, callback) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    button = QPushButton("选择")
    button.clicked.connect(callback)
    layout.addWidget(edit)
    layout.addWidget(button)
    return wrapper


def _distance_spin(value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 1_000_000_000.0)
    spin.setDecimals(4)
    spin.setSingleStep(0.01)
    spin.setValue(float(value))
    return spin


def _ratio_spin(
    value: float,
    minimum: float = 0.05,
    maximum: float = 10.0,
    step: float = 0.1,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(3)
    spin.setSingleStep(step)
    spin.setValue(float(value))
    return spin


def _angle_spin(value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.1, 15.0)
    spin.setDecimals(1)
    spin.setSingleStep(0.5)
    spin.setValue(float(value))
    return spin


def _integer_spin(minimum: int, maximum: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(1)
    spin.setValue(value)
    return spin


def _add_spin_row(layout: QGridLayout, row: int, label: str, widget: QWidget) -> int:
    layout.addWidget(QLabel(label), row, 0)
    layout.addWidget(widget, row, 1)
    return row + 1


def _optional_distance_spin() -> QDoubleSpinBox:
    spin = _distance_spin(0.0)
    spin.setSpecialValueText("自动")
    return spin


def _readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    return item


def _editable_number_item(value: float) -> QTableWidgetItem:
    item = QTableWidgetItem(_format4(value))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    item.setFlags(
        Qt.ItemFlag.ItemIsSelectable
        | Qt.ItemFlag.ItemIsEnabled
        | Qt.ItemFlag.ItemIsEditable
    )
    return item


def _format4(value: float) -> str:
    return f"{value:.4f}"


def _model_bounds(
    model: FaceModel,
    outline_segments: tuple[tuple[Point2D, Point2D], ...] = (),
) -> QRectF:
    points: list[Point2D] = [(node.x, node.y) for node in model.nodes]
    for start, end in outline_segments:
        points.append(start)
        points.append(end)

    if not points:
        return QRectF(0, 0, 1, 1)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x = min(xs)
    min_y = min(ys)
    width = max(max(xs) - min_x, 1e-6)
    height = max(max(ys) - min_y, 1e-6)
    return QRectF(min_x, min_y, width, height)


def _model_delta(before: FaceModel | None, after: FaceModel) -> _ModelDelta:
    before_node_keys: set[tuple[float, float]] = set()
    before_member_keys: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    if before is not None:
        before_node_keys = {_node_key(node) for node in before.nodes}
        before_member_keys = _member_geometry_keys(before)

    node_ids = tuple(
        node.id
        for node in after.nodes
        if _node_key(node) not in before_node_keys
    )
    member_ids = tuple(
        member.id
        for member in after.members
        if _member_geometry_key(after, member) not in before_member_keys
    )
    return _ModelDelta(node_ids=node_ids, member_ids=member_ids)


def _member_geometry_keys(model: FaceModel) -> set[tuple[tuple[float, float], tuple[float, float]]]:
    keys: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for member in model.members:
        key = _member_geometry_key(model, member)
        if key is not None:
            keys.add(key)
    return keys


def _member_geometry_key(
    model: FaceModel,
    member: Member2D,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    nodes = {node.id: node for node in model.nodes}
    start = nodes.get(member.start_node_id)
    end = nodes.get(member.end_node_id)
    if start is None or end is None:
        return None
    endpoints = sorted((_node_key(start), _node_key(end)))
    return (endpoints[0], endpoints[1])


def _node_key(node: Node2D) -> tuple[float, float]:
    return (round(node.x, 4), round(node.y, 4))


def _format_id_list(ids: tuple[str, ...]) -> str:
    return "无" if not ids else ", ".join(ids)


def _distance_squared_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> float:
    dx = bx - ax
    dy = by - ay
    length_squared = dx * dx + dy * dy
    if length_squared <= 0:
        endpoint_dx = px - ax
        endpoint_dy = py - ay
        return endpoint_dx * endpoint_dx + endpoint_dy * endpoint_dy

    t = ((px - ax) * dx + (py - ay) * dy) / length_squared
    t = min(max(t, 0.0), 1.0)
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    distance_x = px - closest_x
    distance_y = py - closest_y
    return distance_x * distance_x + distance_y * distance_y


def _first_dxf_path() -> Path:
    drawings = sorted((PROJECT_ROOT / "drawings").glob("*.dxf"))
    if drawings:
        return drawings[0]
    return PROJECT_ROOT / "drawings" / "base.dxf"


if __name__ == "__main__":
    raise SystemExit(main())
