"""Project wizard GUI shell for the integrated E-House workflow."""

from __future__ import annotations

from pathlib import Path
import sys
import traceback

SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QMainWindow,
    QMessageBox,
    QPushButton,
    QDoubleSpinBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ehouse_model.dxf_preprocessor import preprocess_dxf
from ehouse_model.exporters import (
    export_members_csv,
    export_nodes_csv,
    export_staad_geometry,
    export_warnings_csv,
)
from ehouse_model.domain import Member2D, Node2D
from ehouse_model.face_model import FaceModel
from ehouse_model.global_model import write_global_model_json
from ehouse_model.global_model_types import GlobalModel
from ehouse_model.gui.main_window import MainWindow as BaseRecognitionWindow
from ehouse_model.gui.preprocess_window import PreprocessWorkbenchWindow
from ehouse_model.part_assembly import stitch_part_geometries
from ehouse_model.part_builders import build_base_part_from_face_model, build_roof_part_from_face_model
from ehouse_model.part_geometry import PartGeometry, write_part_geometry_json
from ehouse_model.roof_processing import RoofBoundaryOffsets, export_roof_staad
from ehouse_model.side_wall_plan_processing import (
    SideWallFacePlanSpec,
    SideWallPlanOptions,
    extract_side_wall_plan,
)
from ehouse_model.staad_import import export_part_staad_geometry, import_staad_part_geometry

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class PartModelPage(QWidget):
    """Shared page body for base, side-wall, and roof confirmed geometry."""

    def __init__(self, *, part_id: str, part_type: str, title: str) -> None:
        super().__init__()
        self.part_id = part_id
        self.part_type = part_type
        self.part_geometry: PartGeometry | None = None
        self.face_model: FaceModel | None = None
        self.face_model_source_path: str | None = None

        layout = QVBoxLayout(self)
        header = QGroupBox(title)
        header_layout = QGridLayout(header)
        self.status_label = QLabel("未确认")
        self.source_label = QLabel("-")
        self.face_model_edit = QLineEdit()
        self.face_model_edit.setPlaceholderText("face_model.json / clean DXF / modified STD")
        self.browse_button = QPushButton("选择")
        header_layout.addWidget(QLabel("状态"), 0, 0)
        header_layout.addWidget(self.status_label, 0, 1)
        header_layout.addWidget(QLabel("当前来源"), 1, 0)
        header_layout.addWidget(self.source_label, 1, 1)
        header_layout.addWidget(QLabel("输入/模型"), 2, 0)
        header_layout.addWidget(self.face_model_edit, 2, 1)
        header_layout.addWidget(self.browse_button, 2, 2)
        layout.addWidget(header)

        tables = QHBoxLayout()
        self.node_table = QTableWidget(0, 4)
        self.node_table.setHorizontalHeaderLabels(["id", "x", "y", "z"])
        self.node_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.member_table = QTableWidget(0, 3)
        self.member_table.setHorizontalHeaderLabels(["id", "start", "end"])
        self.member_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tables.addWidget(self.node_table)
        tables.addWidget(self.member_table)
        layout.addLayout(tables, 1)

    def set_part_geometry(self, geometry: PartGeometry | None) -> None:
        self.part_geometry = geometry
        if geometry is None:
            self.status_label.setText("未确认")
            self.source_label.setText("-")
            self.node_table.setRowCount(0)
            self.member_table.setRowCount(0)
            return

        self.status_label.setText("已确认")
        self.source_label.setText(geometry.source.kind)
        if geometry.source.path:
            self.face_model_edit.setText(geometry.source.path)
        _populate_nodes(self.node_table, geometry)
        _populate_members(self.member_table, geometry)

    def set_face_model_result(self, face_model: FaceModel, *, source_path: str | Path) -> None:
        self.face_model = face_model
        self.face_model_source_path = str(source_path)
        self.part_geometry = None
        self.status_label.setText("已识别待确认")
        self.source_label.setText("generated_from_dxf")
        self.face_model_edit.setText(str(source_path))
        _populate_face_nodes(self.node_table, face_model)
        _populate_face_members(self.member_table, face_model)


class BaseWorkflowPage(QWidget):
    """Wizard page that embeds the original base recognition workbench."""

    part_id = "base"
    part_type = "base"

    def __init__(self) -> None:
        super().__init__()
        self.part_geometry: PartGeometry | None = None
        layout = QVBoxLayout(self)

        status_row = QHBoxLayout()
        self.status_label = QLabel("未确认")
        self.source_label = QLabel("-")
        status_row.addWidget(QLabel("底座模型状态:"))
        status_row.addWidget(self.status_label)
        status_row.addWidget(QLabel("当前来源:"))
        status_row.addWidget(self.source_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.workbench = BaseRecognitionWindow()
        _prepare_embedded_main_window(self.workbench)
        layout.addWidget(self.workbench, 1)

    @property
    def face_model(self) -> FaceModel | None:
        return self.workbench.face_model

    @property
    def face_model_source_path(self) -> str:
        return self.workbench.dxf_path_edit.text().strip()

    @property
    def face_model_edit(self) -> QLineEdit:
        return self.workbench.dxf_path_edit

    def set_part_geometry(self, geometry: PartGeometry | None) -> None:
        self.part_geometry = geometry
        if geometry is None:
            self.status_label.setText("未确认")
            self.source_label.setText("-")
            return
        self.status_label.setText("已确认")
        self.source_label.setText(geometry.source.kind)

    def run_recognition(self) -> None:
        self.workbench.recognize_base()
        if self.workbench.face_model is None:
            raise ValueError("底座识别未生成模型，请检查输入图纸和日志。")
        self.part_geometry = None
        self.status_label.setText("已识别待确认")
        self.source_label.setText("generated_from_dxf")


class RoofRecognitionWindow(BaseRecognitionWindow):
    """Base-recognition workbench adapted to export roof geometry at Y."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("E-House 屋盖几何提取工具")
        self.dxf_path_edit.setText(str(_first_roof_dxf_path()))
        self.std_path_edit.setText(str(PROJECT_ROOT / "output" / "roof" / "roof_geometry.std"))

        self.roof_y_spin = QDoubleSpinBox()
        self.roof_y_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.roof_y_spin.setDecimals(4)
        self.roof_y_spin.setSingleStep(0.1)
        self.roof_y_spin.setValue(3.0)
        self.roof_left_dx_spin = _roof_boundary_offset_spin()
        self.roof_right_dx_spin = _roof_boundary_offset_spin()
        self.roof_top_dz_spin = _roof_boundary_offset_spin()
        self.roof_bottom_dz_spin = _roof_boundary_offset_spin()
        self.apply_roof_offsets_button = QPushButton("应用偏移并刷新预览/拼接")
        self._insert_roof_y_panel()
        _replace_visible_text(self, {"底座": "屋盖"})

    @property
    def roof_y_plane(self) -> float:
        return float(self.roof_y_spin.value())

    @property
    def roof_boundary_offsets(self) -> RoofBoundaryOffsets:
        return RoofBoundaryOffsets(
            left_dx=self.roof_left_dx_spin.value(),
            right_dx=self.roof_right_dx_spin.value(),
            top_dz=self.roof_top_dz_spin.value(),
            bottom_dz=self.roof_bottom_dz_spin.value(),
        )

    def export_std(self) -> None:
        if self.face_model is None:
            QMessageBox.information(self, "没有可导出内容", "请先识别屋盖DXF。")
            return
        try:
            std_path = Path(self.std_path_edit.text())
            offsets = self.roof_boundary_offsets
            export_roof_staad(
                self.face_model,
                std_path,
                y_plane=self.roof_y_plane,
                boundary_offsets=offsets,
            )
            self._log(
                f"屋盖STD已导出：{std_path}，Y={self.roof_y_plane:.4f}m，"
                f"边界偏移 L/R/T/B="
                f"{offsets.left_dx:.4f}/{offsets.right_dx:.4f}/"
                f"{offsets.top_dz:.4f}/{offsets.bottom_dz:.4f}"
            )
        except Exception as exc:
            self._show_error("导出屋盖STD失败", exc)

    def select_dxf_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择屋盖DXF", str(PROJECT_ROOT), "DXF 文件 (*.dxf)")
        if path:
            self.dxf_path_edit.setText(path)

    def save_corrections(self) -> None:
        if self.face_model is None:
            QMessageBox.information(self, "没有可保存内容", "请先识别屋盖DXF。")
            return
        try:
            path = Path(self.std_path_edit.text()).parent / "roof_face_model.json"
            from ehouse_model.face_model import write_face_model_json

            write_face_model_json(self.face_model, path)
            self._log(f"屋盖修正结果已保存：{path}")
        except Exception as exc:
            self._show_error("保存屋盖修正失败", exc)

    def set_adjusted_roof_preview(self, geometry: PartGeometry) -> None:
        """Show confirmed roof coordinates in the embedded 2D preview."""
        preview_model = _part_geometry_to_face_model(
            geometry,
            source_dxf=self.face_model.source_dxf if self.face_model is not None else geometry.source.path or "",
        )
        self.preview.set_outline_segments(())
        self.preview.set_face_model(preview_model, reset_view=True)
        if self.large_preview_dialog is not None and self.large_preview_dialog.isVisible():
            self.large_preview_dialog.set_preview_data(preview_model, ())

    def _insert_roof_y_panel(self) -> None:
        root = self.centralWidget()
        if root is None or root.layout() is None:
            return
        panel = QGroupBox("屋盖全局定位")
        layout = QGridLayout(panel)
        layout.addWidget(QLabel("屋盖全局 Y 坐标(m)"), 0, 0)
        layout.addWidget(self.roof_y_spin, 0, 1)
        layout.addWidget(QLabel("左边界 X 偏移"), 1, 0)
        layout.addWidget(self.roof_left_dx_spin, 1, 1)
        layout.addWidget(QLabel("右边界 X 偏移"), 1, 2)
        layout.addWidget(self.roof_right_dx_spin, 1, 3)
        layout.addWidget(QLabel("上边界 Z 偏移"), 2, 0)
        layout.addWidget(self.roof_top_dz_spin, 2, 1)
        layout.addWidget(QLabel("下边界 Z 偏移"), 2, 2)
        layout.addWidget(self.roof_bottom_dz_spin, 2, 3)
        layout.addWidget(QLabel("校正后左上角(Xmin/Zmin)作为屋盖坐标原点"), 3, 0, 1, 4)
        layout.addWidget(self.apply_roof_offsets_button, 4, 3)
        root.layout().insertWidget(1, panel)


class RoofWorkflowPage(QWidget):
    """Wizard page that embeds the roof recognition workbench."""

    part_id = "roof"
    part_type = "roof"

    def __init__(self) -> None:
        super().__init__()
        self.part_geometry: PartGeometry | None = None
        layout = QVBoxLayout(self)

        status_row = QHBoxLayout()
        self.status_label = QLabel("未确认")
        self.source_label = QLabel("-")
        status_row.addWidget(QLabel("屋盖模型状态:"))
        status_row.addWidget(self.status_label)
        status_row.addWidget(QLabel("当前来源:"))
        status_row.addWidget(self.source_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.workbench = RoofRecognitionWindow()
        _prepare_embedded_main_window(self.workbench)
        layout.addWidget(self.workbench, 1)

        for spin in (
            self.workbench.roof_y_spin,
            self.workbench.roof_left_dx_spin,
            self.workbench.roof_right_dx_spin,
            self.workbench.roof_top_dz_spin,
            self.workbench.roof_bottom_dz_spin,
        ):
            spin.valueChanged.connect(self._mark_offsets_pending)

    @property
    def face_model(self) -> FaceModel | None:
        return self.workbench.face_model

    @property
    def face_model_source_path(self) -> str:
        return self.workbench.dxf_path_edit.text().strip()

    @property
    def face_model_edit(self) -> QLineEdit:
        return self.workbench.dxf_path_edit

    @property
    def roof_y_plane(self) -> float:
        return self.workbench.roof_y_plane

    @property
    def roof_boundary_offsets(self) -> RoofBoundaryOffsets:
        return self.workbench.roof_boundary_offsets

    def set_part_geometry(self, geometry: PartGeometry | None) -> None:
        self.part_geometry = geometry
        if geometry is None:
            self.status_label.setText("未确认")
            self.source_label.setText("-")
            return
        self.status_label.setText("已确认")
        self.source_label.setText(geometry.source.kind)
        self.workbench.set_adjusted_roof_preview(geometry)

    def run_recognition(self) -> None:
        self.workbench.recognize_base()
        if self.workbench.face_model is None:
            raise ValueError("屋盖识别未生成模型，请检查输入图纸和日志。")
        self.part_geometry = None
        self.status_label.setText("已识别待确认")
        self.source_label.setText("generated_from_dxf")

    def _mark_offsets_pending(self) -> None:
        if self.part_geometry is not None:
            self.status_label.setText("偏移已修改待应用")

    def show_adjusted_preview(self, geometry: PartGeometry) -> None:
        self.workbench.set_adjusted_roof_preview(geometry)


class GlobalModelPreview(QGraphicsView):
    """Isometric preview for the current stitched global model."""

    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setMinimumHeight(320)
        self._model: GlobalModel | None = None

    def set_global_model(self, model: GlobalModel | None) -> None:
        self._model = model
        self._redraw()

    def _redraw(self) -> None:
        self.scene.clear()
        model = self._model
        if model is None or not model.nodes:
            self.scene.addText("尚无已确认模型")
            return

        nodes = {node.id: node for node in model.nodes}
        projected_points = [_project_iso(node.x, node.y, node.z) for node in model.nodes]

        for member in model.members:
            start = nodes.get(member.start_node_id)
            end = nodes.get(member.end_node_id)
            if start is None or end is None:
                continue
            pen = QPen(_part_color(member.id, model.member_sources.get(member.id)))
            pen.setWidthF(0)
            pen.setCosmetic(True)
            start_x, start_y = _project_iso(start.x, start.y, start.z)
            end_x, end_y = _project_iso(end.x, end.y, end.z)
            self.scene.addLine(start_x, start_y, end_x, end_y, pen)

        node_pen = QPen(QColor("#111827"))
        node_pen.setWidthF(0)
        node_pen.setCosmetic(True)
        node_brush = QBrush(QColor("#111827"))
        for node in model.nodes:
            x, y = _project_iso(node.x, node.y, node.z)
            marker = self.scene.addEllipse(-2.0, -2.0, 4.0, 4.0, node_pen, node_brush)
            marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            marker.setPos(x, y)
            marker.setToolTip(f"{node.id}: X={node.x:.4f}, Y={node.y:.4f}, Z={node.z:.4f}")

        self._draw_axes(model)

        xs = [point[0] for point in projected_points]
        ys = [point[1] for point in projected_points]
        min_x = min(xs)
        min_y = min(ys)
        width = max(max(xs) - min_x, 1e-6)
        height = max(max(ys) - min_y, 1e-6)
        margin = max(max(width, height) * 0.08, 0.5)
        rect = QRectF(min_x - margin, min_y - margin, width + 2 * margin, height + 2 * margin)
        self.scene.setSceneRect(rect)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_axes(self, model: GlobalModel) -> None:
        max_span = max(
            max((node.x for node in model.nodes), default=0.0) - min((node.x for node in model.nodes), default=0.0),
            max((node.y for node in model.nodes), default=0.0) - min((node.y for node in model.nodes), default=0.0),
            max((node.z for node in model.nodes), default=0.0) - min((node.z for node in model.nodes), default=0.0),
            1.0,
        )
        axis_length = max_span * 0.18
        origin = (0.0, 0.0, 0.0)
        axes = (
            ("X", (axis_length, 0.0, 0.0), "#dc2626"),
            ("Y", (0.0, axis_length, 0.0), "#16a34a"),
            ("Z", (0.0, 0.0, axis_length), "#2563eb"),
        )
        ox, oy = _project_iso(*origin)
        for label, end, color in axes:
            ex, ey = _project_iso(*end)
            pen = QPen(QColor(color))
            pen.setWidthF(1.6)
            pen.setCosmetic(True)
            self.scene.addLine(ox, oy, ex, ey, pen)
            text = self.scene.addText(label)
            text.setDefaultTextColor(QColor(color))
            text.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            text.setPos(ex, ey)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self.scene.sceneRect().isValid() and not self.scene.sceneRect().isNull():
            self.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


class SideWallPlanPage(QWidget):
    """Wizard page for first-pass side-wall plan-view section marker recognition."""

    part_id = "side_wall"
    part_type = "side_wall"

    def __init__(self) -> None:
        super().__init__()
        self.part_geometry: PartGeometry | None = None
        self.face_controls: dict[str, dict[str, QCheckBox | QDoubleSpinBox]] = {}

        layout = QVBoxLayout(self)

        status_row = QHBoxLayout()
        self.status_label = QLabel("未确认")
        self.source_label = QLabel("-")
        status_row.addWidget(QLabel("侧墙模型状态:"))
        status_row.addWidget(self.status_label)
        status_row.addWidget(QLabel("当前来源:"))
        status_row.addWidget(self.source_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        input_box = QGroupBox("侧墙顶视图截面识别")
        input_layout = QGridLayout(input_box)
        self.face_model_edit = QLineEdit()
        self.face_model_edit.setPlaceholderText("侧墙顶视图 DXF")
        self.browse_button = QPushButton("选择")
        self.recognize_button = QPushButton("识别侧墙顶视图")
        self.confirm_button = QPushButton("确认侧墙模型")
        self.top_y_spin = _side_wall_distance_spin(3.0)
        self.duplicate_tolerance_spin = _side_wall_distance_spin(0.001, decimals=6, step=0.001)
        self.reuse_tolerance_spin = _side_wall_distance_spin(0.001, decimals=6, step=0.001)

        input_layout.addWidget(QLabel("顶视图DXF"), 0, 0)
        input_layout.addWidget(self.face_model_edit, 0, 1, 1, 4)
        input_layout.addWidget(self.browse_button, 0, 5)
        input_layout.addWidget(QLabel("墙顶Y坐标"), 1, 0)
        input_layout.addWidget(self.top_y_spin, 1, 1)
        input_layout.addWidget(QLabel("形心去重容差"), 1, 2)
        input_layout.addWidget(self.duplicate_tolerance_spin, 1, 3)
        input_layout.addWidget(QLabel("节点复用容差"), 1, 4)
        input_layout.addWidget(self.reuse_tolerance_spin, 1, 5)
        input_layout.addWidget(self.recognize_button, 2, 4)
        input_layout.addWidget(self.confirm_button, 2, 5)
        layout.addWidget(input_box)

        faces_box = QGroupBox("四面墙定位与筛选范围")
        faces_layout = QGridLayout(faces_box)
        headers = ("启用", "墙面", "固定坐标", "筛选下限", "筛选上限")
        for column, header in enumerate(headers):
            faces_layout.addWidget(QLabel(header), 0, column)
        self._add_face_row(faces_layout, 1, "left", "左侧墙 X固定 / 按图纸X筛选", fixed_default=0.0)
        self._add_face_row(faces_layout, 2, "right", "右侧墙 X固定 / 按图纸X筛选", fixed_default=0.0)
        self._add_face_row(faces_layout, 3, "top", "上侧墙 Z固定 / 按图纸Z筛选", fixed_default=0.0)
        self._add_face_row(faces_layout, 4, "bottom", "下侧墙 Z固定 / 按图纸Z筛选", fixed_default=0.0)
        layout.addWidget(faces_box)

        preview_box = QGroupBox("侧墙识别预览（三维）")
        preview_layout = QVBoxLayout(preview_box)
        self.preview = GlobalModelPreview()
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_box, 2)

        tables = QHBoxLayout()
        self.node_table = QTableWidget(0, 4)
        self.node_table.setHorizontalHeaderLabels(["id", "x", "y", "z"])
        self.node_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.member_table = QTableWidget(0, 3)
        self.member_table.setHorizontalHeaderLabels(["id", "start", "end"])
        self.member_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tables.addWidget(self.node_table)
        tables.addWidget(self.member_table)
        layout.addLayout(tables, 1)

        self.browse_button.clicked.connect(self._choose_dxf)
        self.recognize_button.clicked.connect(self._recognize_from_button)
        self.confirm_button.clicked.connect(self._confirm_from_button)

    @property
    def reuse_tolerance(self) -> float:
        return float(self.reuse_tolerance_spin.value())

    def run_recognition(self) -> PartGeometry:
        dxf_path = self._input_path()
        geometry = extract_side_wall_plan(dxf_path, self._options())
        self.part_geometry = geometry
        self.status_label.setText("已识别待确认")
        self.source_label.setText(geometry.source.kind)
        self.face_model_edit.setText(str(dxf_path))
        self._show_geometry(geometry)
        return geometry

    def set_part_geometry(self, geometry: PartGeometry | None) -> None:
        self.part_geometry = geometry
        if geometry is None:
            self.status_label.setText("未确认")
            self.source_label.setText("-")
            self.node_table.setRowCount(0)
            self.member_table.setRowCount(0)
            self.preview.set_global_model(None)
            return
        self.status_label.setText("已确认")
        self.source_label.setText(geometry.source.kind)
        if geometry.source.path:
            self.face_model_edit.setText(geometry.source.path)
        self._show_geometry(geometry)

    def _show_geometry(self, geometry: PartGeometry) -> None:
        _populate_nodes(self.node_table, geometry)
        _populate_members(self.member_table, geometry)
        self.preview.set_global_model(_part_preview_global_model(geometry))

    def _choose_dxf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择侧墙顶视图DXF", str(PROJECT_ROOT), "DXF 文件 (*.dxf)")
        if path:
            self.face_model_edit.setText(path)

    def _recognize_from_button(self) -> None:
        try:
            self.run_recognition()
        except Exception as exc:
            QMessageBox.critical(self, "侧墙顶视图识别失败", str(exc))

    def _confirm_from_button(self) -> None:
        window = self.window()
        if isinstance(window, ProjectWizardWindow):
            try:
                window.confirm_side_wall_recognition()
            except Exception as exc:
                window._show_error("确认侧墙模型失败", exc)

    def _add_face_row(
        self,
        layout: QGridLayout,
        row: int,
        face_name: str,
        title: str,
        *,
        fixed_default: float,
    ) -> None:
        enabled = QCheckBox()
        enabled.setChecked(True)
        fixed = _side_wall_distance_spin(fixed_default)
        filter_min = _side_wall_distance_spin(0.0)
        filter_max = _side_wall_distance_spin(0.0)
        layout.addWidget(enabled, row, 0)
        layout.addWidget(QLabel(title), row, 1)
        layout.addWidget(fixed, row, 2)
        layout.addWidget(filter_min, row, 3)
        layout.addWidget(filter_max, row, 4)
        self.face_controls[face_name] = {
            "enabled": enabled,
            "fixed": fixed,
            "filter_min": filter_min,
            "filter_max": filter_max,
        }

    def _options(self) -> SideWallPlanOptions:
        return SideWallPlanOptions(
            top_y=self.top_y_spin.value(),
            duplicate_tolerance=self.duplicate_tolerance_spin.value(),
            reuse_tolerance=self.reuse_tolerance_spin.value(),
            face_specs=(
                self._face_spec("left", fixed_axis="X", filter_axis="X"),
                self._face_spec("right", fixed_axis="X", filter_axis="X"),
                self._face_spec("top", fixed_axis="Z", filter_axis="Z"),
                self._face_spec("bottom", fixed_axis="Z", filter_axis="Z"),
            ),
        )

    def _face_spec(self, face_name: str, *, fixed_axis: str, filter_axis: str) -> SideWallFacePlanSpec:
        controls = self.face_controls[face_name]
        return SideWallFacePlanSpec(
            face_name=face_name,
            fixed_axis=fixed_axis,
            fixed_coordinate=controls["fixed"].value(),  # type: ignore[union-attr]
            filter_axis=filter_axis,
            filter_min=controls["filter_min"].value(),  # type: ignore[union-attr]
            filter_max=controls["filter_max"].value(),  # type: ignore[union-attr]
            enabled=controls["enabled"].isChecked(),  # type: ignore[union-attr]
        )

    def _input_path(self) -> Path:
        text = self.face_model_edit.text().strip().strip('"')
        if not text:
            raise ValueError("请先选择侧墙顶视图DXF。")
        path = Path(text)
        if not path.exists():
            raise FileNotFoundError(path)
        return path


class ProjectWizardWindow(QMainWindow):
    """Integrated wizard with centralized public tools."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("E-House 项目向导建模工具")
        self.resize(1440, 860)
        self.confirmed_parts: dict[str, PartGeometry] = {}
        self.current_global_model: GlobalModel | None = None
        self._child_windows: list[QWidget] = []

        self.actions: dict[str, QAction] = {}
        self._create_actions()
        self._create_menus()
        self._create_toolbar()

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.preprocess_page = self._build_preprocess_page()
        self.base_page = BaseWorkflowPage()
        self.side_wall_page = SideWallPlanPage()
        self.roof_page = RoofWorkflowPage()
        self.roof_page.workbench.apply_roof_offsets_button.clicked.connect(
            self._apply_roof_offsets_from_action
        )
        self.stitch_page = self._build_stitch_page()
        self.export_page = self._build_export_page()

        self.tabs.addTab(self.preprocess_page, "图纸预处理")
        self.tabs.addTab(self.base_page, "底座")
        self.tabs.addTab(self.side_wall_page, "侧墙")
        self.tabs.addTab(self.roof_page, "屋盖")
        self.tabs.addTab(self.stitch_page, "拼接检查")
        self.tabs.addTab(self.export_page, "导出/分析")
        self.tabs.currentChanged.connect(self._refresh_action_state)
        self._refresh_action_state()

    def set_part_geometry(self, geometry: PartGeometry) -> None:
        self.confirmed_parts[geometry.part_id] = geometry
        page = self._page_for_part(geometry.part_id)
        if page is not None:
            page.set_part_geometry(geometry)
        saved_path = self._write_default_part_geometry(geometry)
        self._log(
            f"已确认 {geometry.part_id}: "
            f"{len(geometry.nodes)} 节点, {len(geometry.members)} 单元, 来源 {geometry.source.kind}"
        )
        self._log(f"part_geometry.json 已保存: {saved_path}")
        self.refresh_stitching()
        self._refresh_action_state()

    def import_modified_std(
        self,
        path: str | Path,
        *,
        part_id: str | None = None,
        part_type: str | None = None,
    ) -> PartGeometry:
        target_page = self._current_part_page()
        resolved_part_id = part_id or (target_page.part_id if target_page is not None else "base")
        resolved_part_type = part_type or (target_page.part_type if target_page is not None else resolved_part_id)
        geometry = import_staad_part_geometry(
            path,
            part_id=resolved_part_id,
            part_type=resolved_part_type,
        )
        self.set_part_geometry(geometry)
        return geometry

    def run_current_recognition(self) -> None:
        page = self._current_part_page()
        if page is None:
            return
        if page.part_id == "base":
            self.recognize_base_from_input()
            return
        if page.part_id == "roof":
            self.recognize_roof_from_input()
            return
        if page.part_id == "side_wall":
            self.recognize_side_wall_from_input()
            return
        self._log(f"{page.part_id} 识别处理器尚未接入。")

    def recognize_base_from_input(self) -> FaceModel:
        self.base_page.run_recognition()
        face_model = self.base_page.face_model
        if face_model is None:
            raise ValueError("底座识别未生成模型。")
        self._log(
            "底座识别完成: "
            f"{len(face_model.nodes)} 节点, {len(face_model.members)} 单元, "
            f"warnings {len(face_model.warnings)}"
        )
        self._refresh_action_state()
        return face_model

    def recognize_roof_from_input(self) -> FaceModel:
        self.roof_page.run_recognition()
        face_model = self.roof_page.face_model
        if face_model is None:
            raise ValueError("屋盖识别未生成模型。")
        self._log(
            "屋盖识别完成: "
            f"{len(face_model.nodes)} 节点, {len(face_model.members)} 单元, "
            f"Y={self.roof_page.roof_y_plane:.4f}m, "
            f"warnings {len(face_model.warnings)}"
        )
        self._refresh_action_state()
        return face_model

    def recognize_side_wall_from_input(self) -> PartGeometry:
        geometry = self.side_wall_page.run_recognition()
        self._log(
            "侧墙顶视图识别完成: "
            f"{len(geometry.nodes)} 节点, {len(geometry.members)} 单元, "
            f"warnings {len(geometry.warnings)}"
        )
        self._refresh_action_state()
        return geometry

    def confirm_current_part(self) -> PartGeometry:
        page = self._current_part_page()
        if page is None:
            raise ValueError("no current part page")
        if page.part_id == "base":
            return self.confirm_base_recognition()
        if page.part_id == "roof":
            return self.confirm_roof_recognition()
        if page.part_id == "side_wall":
            return self.confirm_side_wall_recognition()
        raise NotImplementedError(f"{page.part_id} confirmation is not wired yet")

    def confirm_base_recognition(self) -> PartGeometry:
        if self.base_page.face_model is None:
            raise ValueError("请先识别底座图纸，或导入修改后的底座 STD。")
        geometry = build_base_part_from_face_model(
            self.base_page.face_model,
            source_path=self.base_page.face_model_source_path,
        )
        self.set_part_geometry(geometry)
        return geometry

    def confirm_roof_recognition(self) -> PartGeometry:
        if self.roof_page.face_model is None:
            raise ValueError("请先识别屋盖图纸，或导入修改后的屋盖 STD。")
        geometry = build_roof_part_from_face_model(
            self.roof_page.face_model,
            y_plane=self.roof_page.roof_y_plane,
            boundary_offsets=self.roof_page.roof_boundary_offsets,
            source_path=self.roof_page.face_model_source_path,
        )
        self.set_part_geometry(geometry)
        return geometry

    def confirm_side_wall_recognition(self) -> PartGeometry:
        if self.side_wall_page.part_geometry is None:
            self.side_wall_page.run_recognition()
        if self.side_wall_page.part_geometry is None:
            raise ValueError("请先识别侧墙顶视图。")
        geometry = self.side_wall_page.part_geometry
        self.set_part_geometry(geometry)
        return geometry

    def preprocess_dxf_file(self, path: str | Path, *, part_id: str = ""):
        input_path = Path(path)
        output_dir = PROJECT_ROOT / "output" / "preprocess" / input_path.stem
        clean_path = output_dir / f"{input_path.stem}_clean.dxf"
        overlay_path = output_dir / f"{input_path.stem}_preprocess_overlay.dxf"
        report_path = output_dir / f"{input_path.stem}_preprocess_report.csv"
        result = preprocess_dxf(
            input_path,
            output_path=clean_path,
            overlay_path=overlay_path,
            report_csv_path=report_path,
        )
        self._add_drawing_record(
            part_id=part_id,
            original_path=result.input_path,
            clean_path=result.clean_dxf_path,
            overlay_path=result.overlay_dxf_path,
            status=f"已预处理: {result.output_segment_count} 线段",
        )
        self._log(
            f"预处理完成: {result.input_path} -> {result.clean_dxf_path}; "
            f"输出线段 {result.output_segment_count}, 删除 {result.removed_segment_count}"
        )
        return result

    def refresh_stitching(self) -> GlobalModel:
        model = stitch_part_geometries(
            self.confirmed_parts.values(),
            project_name="E-House Project",
            node_reuse_tolerance=self.side_wall_page.reuse_tolerance,
        )
        self.current_global_model = model
        self.stitch_status_label.setText(
            f"当前部分 {len(self.confirmed_parts)} 个；"
            f"全局节点 {len(model.nodes)}；全局单元 {len(model.members)}；"
            f"Warnings {len(model.warnings)}"
        )
        self.parts_table.setRowCount(0)
        for part in self.confirmed_parts.values():
            row = self.parts_table.rowCount()
            self.parts_table.insertRow(row)
            self.parts_table.setItem(row, 0, _readonly_item(part.part_id))
            self.parts_table.setItem(row, 1, _readonly_item(part.part_type))
            self.parts_table.setItem(row, 2, _readonly_item(part.source.kind))
            self.parts_table.setItem(row, 3, _readonly_item(str(len(part.nodes))))
            self.parts_table.setItem(row, 4, _readonly_item(str(len(part.members))))
        _populate_global_warnings(self.warning_table, model)
        self.global_preview.set_global_model(model)
        return model

    def _create_actions(self) -> None:
        self.actions["new_project"] = QAction("新建项目", self)
        self.actions["new_project"].triggered.connect(lambda: self._log("新建项目入口已预留"))
        self.actions["open_project"] = QAction("打开项目", self)
        self.actions["open_project"].triggered.connect(lambda: self._log("打开项目入口已预留"))
        self.actions["save_project"] = QAction("保存项目", self)
        self.actions["save_project"].triggered.connect(lambda: self._log("保存项目入口已预留"))

        self.actions["preprocess"] = QAction("图纸预处理", self)
        self.actions["preprocess"].triggered.connect(lambda: self.tabs.setCurrentWidget(self.preprocess_page))
        self.actions["recognize"] = QAction("识别当前部分", self)
        self.actions["recognize"].triggered.connect(self._run_current_recognition_from_action)

        self.actions["local_patch"] = QAction("局部补识别", self)
        self.actions["local_patch"].triggered.connect(lambda: self._log_context_tool("局部补识别"))
        self.actions["short_member"] = QAction("短构件补全", self)
        self.actions["short_member"].triggered.connect(lambda: self._log_context_tool("短构件补全"))
        self.actions["realign"] = QAction("中心线重对齐", self)
        self.actions["realign"].triggered.connect(lambda: self._log_context_tool("中心线重对齐"))
        self.actions["undo"] = QAction("撤销", self)
        self.actions["undo"].triggered.connect(lambda: self._log("撤销入口已预留"))
        self.actions["redo"] = QAction("重做", self)
        self.actions["redo"].triggered.connect(lambda: self._log("重做入口已预留"))

        self.actions["confirm_part"] = QAction("确认当前部分", self)
        self.actions["confirm_part"].triggered.connect(self._confirm_current_part_from_action)
        self.actions["export_part_std"] = QAction("导出部分STD", self)
        self.actions["export_part_std"].triggered.connect(self._choose_export_part_std)
        self.actions["import_modified_std"] = QAction("导入修改STD", self)
        self.actions["import_modified_std"].triggered.connect(self._choose_import_modified_std)

        self.actions["refresh_stitch"] = QAction("刷新拼接", self)
        self.actions["refresh_stitch"].triggered.connect(lambda: self.refresh_stitching())
        self.actions["export_global"] = QAction("导出全局结果", self)
        self.actions["export_global"].triggered.connect(self._choose_export_global_outputs)

    def _create_menus(self) -> None:
        menu_specs = [
            ("文件", ["new_project", "open_project", "save_project"]),
            ("图纸", ["preprocess"]),
            ("识别", ["recognize"]),
            ("修正", ["local_patch", "short_member", "realign", "undo", "redo"]),
            ("模型", ["confirm_part", "export_part_std", "import_modified_std"]),
            ("拼接", ["refresh_stitch"]),
            ("导出", ["export_global"]),
        ]
        for menu_title, action_keys in menu_specs:
            menu = self.menuBar().addMenu(menu_title)
            for key in action_keys:
                menu.addAction(self.actions[key])

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("公共工具箱", self)
        toolbar.setObjectName("common_tools_toolbar")
        self.addToolBar(toolbar)
        for key in (
            "preprocess",
            "recognize",
            "local_patch",
            "short_member",
            "realign",
            "confirm_part",
            "export_part_std",
            "import_modified_std",
            "refresh_stitch",
            "export_global",
        ):
            toolbar.addAction(self.actions[key])

    def _build_preprocess_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.preprocess_workbench = PreprocessWorkbenchWindow()
        _prepare_embedded_main_window(self.preprocess_workbench)
        layout.addWidget(self.preprocess_workbench, 1)

        records_box = QGroupBox("向导预处理记录")
        records_layout = QVBoxLayout(records_box)
        self.drawing_table = QTableWidget(0, 5)
        self.drawing_table.setHorizontalHeaderLabels(["部分", "原始DXF", "clean DXF", "overlay", "状态"])
        self.drawing_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.drawing_table.setMaximumHeight(150)
        records_layout.addWidget(self.drawing_table)
        button_row = QHBoxLayout()
        preprocess_button = QPushButton("选择DXF并运行默认预处理")
        preprocess_button.clicked.connect(self._choose_and_preprocess_dxf)
        add_button = QPushButton("添加图纸记录")
        add_button.clicked.connect(self._add_empty_drawing_row)
        open_preprocess_button = QPushButton("弹出独立预处理工作台")
        open_preprocess_button.clicked.connect(self._open_preprocess_workbench)
        button_row.addWidget(preprocess_button)
        button_row.addWidget(add_button)
        button_row.addWidget(open_preprocess_button)
        button_row.addStretch(1)
        records_layout.addLayout(button_row)
        layout.addWidget(records_box)
        return page

    def _build_stitch_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.stitch_status_label = QLabel("当前部分 0 个；全局节点 0；全局单元 0；Warnings 0")
        layout.addWidget(self.stitch_status_label)

        preview_box = QGroupBox("当前拼接预览（三维轴测）")
        preview_layout = QVBoxLayout(preview_box)
        self.global_preview = GlobalModelPreview()
        preview_layout.addWidget(self.global_preview)
        layout.addWidget(preview_box, 2)

        self.parts_table = QTableWidget(0, 5)
        self.parts_table.setHorizontalHeaderLabels(["part_id", "part_type", "source", "nodes", "members"])
        self.parts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.parts_table)
        self.warning_table = QTableWidget(0, 5)
        self.warning_table.setHorizontalHeaderLabels(["id", "level", "code", "message", "entity"])
        self.warning_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.warning_table, 1)
        refresh_button = QPushButton("刷新当前拼接状态")
        refresh_button.clicked.connect(lambda: self.refresh_stitching())
        layout.addWidget(refresh_button)
        return page

    def _build_export_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        export_box = QGroupBox("全局导出")
        export_layout = QGridLayout(export_box)
        self.output_dir_edit = QLineEdit(str(PROJECT_ROOT / "output_global"))
        export_button = QPushButton("导出 global_model / CSV / STD")
        export_button.clicked.connect(self._choose_export_global_outputs)
        export_layout.addWidget(QLabel("输出目录"), 0, 0)
        export_layout.addWidget(self.output_dir_edit, 0, 1)
        export_layout.addWidget(export_button, 1, 1)
        layout.addWidget(export_box)
        analysis_box = QGroupBox("分析与校核")
        analysis_layout = QVBoxLayout(analysis_box)
        analysis_layout.addWidget(QLabel("规范、荷载、校核计算模块已预留，当前版本只处理几何。"))
        layout.addWidget(analysis_box)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        layout.addWidget(QLabel("日志"))
        layout.addWidget(self.log, 1)
        return page

    def _add_empty_drawing_row(self) -> None:
        row = self.drawing_table.rowCount()
        self.drawing_table.insertRow(row)
        for column, text in enumerate(("", "", "", "", "未处理")):
            self.drawing_table.setItem(row, column, QTableWidgetItem(text))

    def _add_drawing_record(
        self,
        *,
        part_id: str,
        original_path: str | Path,
        clean_path: str | Path,
        overlay_path: str | Path,
        status: str,
    ) -> None:
        row = self.drawing_table.rowCount()
        self.drawing_table.insertRow(row)
        values = (
            part_id,
            str(original_path),
            str(clean_path),
            str(overlay_path),
            status,
        )
        for column, text in enumerate(values):
            self.drawing_table.setItem(row, column, _readonly_item(text))

    def _choose_and_preprocess_dxf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择需要预处理的DXF", str(PROJECT_ROOT), "DXF 文件 (*.dxf)")
        if not path:
            return
        try:
            self.preprocess_dxf_file(path)
        except Exception as exc:
            self._show_error("图纸预处理失败", exc)

    def _open_preprocess_workbench(self) -> None:
        try:
            from ehouse_model.gui.preprocess_window import PreprocessWorkbenchWindow

            window = PreprocessWorkbenchWindow()
            window.show()
            self._child_windows.append(window)
            self._log("已打开独立预处理工作台。")
        except Exception as exc:
            self._show_error("打开预处理工作台失败", exc)

    def _choose_current_part_input(self) -> None:
        page = self._current_part_page()
        if page is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择当前部分输入文件",
            str(PROJECT_ROOT),
            "模型输入 (*.dxf *.std *.json);;DXF 文件 (*.dxf);;STAAD 文件 (*.std);;JSON 文件 (*.json)",
        )
        if path:
            page.face_model_edit.setText(path)

    def _current_input_path(self, page: PartModelPage, *, action_name: str) -> Path:
        text = page.face_model_edit.text().strip().strip('"')
        if not text:
            self._choose_current_part_input()
            text = page.face_model_edit.text().strip().strip('"')
        if not text:
            raise ValueError(f"{action_name}需要先选择输入文件。")
        path = Path(text)
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def _run_current_recognition_from_action(self, checked: bool = False) -> None:
        try:
            self.run_current_recognition()
        except Exception as exc:
            self._show_error("识别当前部分失败", exc)

    def _confirm_current_part_from_action(self, checked: bool = False) -> None:
        try:
            self.confirm_current_part()
        except NotImplementedError as exc:
            QMessageBox.information(self, "暂未接入", str(exc))
        except Exception as exc:
            self._show_error("确认当前部分失败", exc)

    def _apply_roof_offsets_from_action(self, checked: bool = False) -> None:
        if self.roof_page.face_model is None:
            QMessageBox.information(self, "尚未识别屋盖", "请先识别屋盖DXF，再应用偏移。")
            return
        try:
            self.confirm_roof_recognition()
            self._log("屋盖偏移已应用，拼接预览已刷新。")
        except Exception as exc:
            self._show_error("应用屋盖偏移失败", exc)

    def _write_default_part_geometry(self, geometry: PartGeometry) -> Path:
        path = PROJECT_ROOT / "output" / geometry.part_id / f"{geometry.part_id}_part_geometry.json"
        write_part_geometry_json(geometry, path)
        return path

    def _current_part_page(self) -> QWidget | None:
        widget = self.tabs.currentWidget()
        return widget if hasattr(widget, "part_id") and hasattr(widget, "part_type") else None

    def _page_for_part(self, part_id: str) -> QWidget | None:
        pages = {
            self.base_page.part_id: self.base_page,
            self.side_wall_page.part_id: self.side_wall_page,
            self.roof_page.part_id: self.roof_page,
        }
        return pages.get(part_id)

    def _refresh_action_state(self) -> None:
        has_part_context = self._current_part_page() is not None
        for key in (
            "recognize",
            "local_patch",
            "short_member",
            "realign",
            "confirm_part",
            "export_part_std",
            "import_modified_std",
        ):
            self.actions[key].setEnabled(has_part_context)
        self.actions["export_global"].setEnabled(bool(self.confirmed_parts))

    def _choose_import_modified_std(self) -> None:
        page = self._current_part_page()
        if page is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入修改后的STD", str(PROJECT_ROOT), "STAAD 文件 (*.std)")
        if not path:
            return
        try:
            self.import_modified_std(path, part_id=page.part_id, part_type=page.part_type)
        except Exception as exc:
            self._show_error("导入STD失败", exc)

    def _choose_export_part_std(self) -> None:
        page = self._current_part_page()
        if page is None or page.part_geometry is None:
            QMessageBox.information(self, "没有可导出的部分", "请先确认当前部分模型。")
            return
        default = PROJECT_ROOT / "output" / page.part_id / f"{page.part_id}.std"
        path, _ = QFileDialog.getSaveFileName(self, "导出部分STD", str(default), "STAAD 文件 (*.std)")
        if not path:
            return
        try:
            export_part_staad_geometry(page.part_geometry, path)
            self._log(f"已导出部分STD: {path}")
        except Exception as exc:
            self._show_error("导出部分STD失败", exc)

    def _choose_export_global_outputs(self) -> None:
        output_dir = Path(self.output_dir_edit.text().strip() or PROJECT_ROOT / "output_global")
        try:
            model = self.refresh_stitching()
            output_dir.mkdir(parents=True, exist_ok=True)
            write_global_model_json(model, output_dir / "global_model.json")
            export_nodes_csv(model.nodes, output_dir / "nodes.csv")
            export_members_csv(model.members, output_dir / "members.csv")
            export_warnings_csv(model.warnings, output_dir / "warnings.csv")
            export_staad_geometry(model, output_dir / "geometry.std")
            for part in self.confirmed_parts.values():
                write_part_geometry_json(part, output_dir / f"{part.part_id}_part_geometry.json")
            self._log(f"已导出全局结果: {output_dir}")
        except Exception as exc:
            self._show_error("导出全局结果失败", exc)

    def _log_context_tool(self, tool_name: str) -> None:
        page = self._current_part_page()
        target = page.part_id if page is not None else "全局模型"
        self._log(f"{tool_name} 将作用于当前上下文: {target}")

    def _log(self, message: str) -> None:
        if hasattr(self, "log"):
            self.log.appendPlainText(message)

    def _show_error(self, title: str, exc: Exception) -> None:
        self._log(traceback.format_exc())
        QMessageBox.critical(self, title, str(exc))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = ProjectWizardWindow()
    window.show()
    return int(app.exec())


def _populate_nodes(table: QTableWidget, geometry: PartGeometry) -> None:
    table.setRowCount(0)
    for node in geometry.nodes:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, _readonly_item(node.id))
        table.setItem(row, 1, _readonly_item(_format_float(node.x)))
        table.setItem(row, 2, _readonly_item(_format_float(node.y)))
        table.setItem(row, 3, _readonly_item(_format_float(node.z)))


def _populate_members(table: QTableWidget, geometry: PartGeometry) -> None:
    table.setRowCount(0)
    for member in geometry.members:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, _readonly_item(member.id))
        table.setItem(row, 1, _readonly_item(member.start_node_id))
        table.setItem(row, 2, _readonly_item(member.end_node_id))


def _populate_face_nodes(table: QTableWidget, face_model: FaceModel) -> None:
    table.setRowCount(0)
    for node in face_model.nodes:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, _readonly_item(node.id))
        table.setItem(row, 1, _readonly_item(_format_float(node.x)))
        table.setItem(row, 2, _readonly_item(_format_float(node.y)))
        table.setItem(row, 3, _readonly_item("-"))


def _populate_face_members(table: QTableWidget, face_model: FaceModel) -> None:
    table.setRowCount(0)
    for member in face_model.members:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, _readonly_item(member.id))
        table.setItem(row, 1, _readonly_item(member.start_node_id))
        table.setItem(row, 2, _readonly_item(member.end_node_id))


def _populate_global_warnings(table: QTableWidget, model: GlobalModel) -> None:
    table.setRowCount(0)
    for warning in model.warnings:
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, _readonly_item(warning.id))
        table.setItem(row, 1, _readonly_item(warning.level))
        table.setItem(row, 2, _readonly_item(warning.code))
        table.setItem(row, 3, _readonly_item(warning.message))
        table.setItem(row, 4, _readonly_item(warning.entity_id or ""))


def _part_geometry_to_face_model(geometry: PartGeometry, *, source_dxf: str) -> FaceModel:
    """Convert global part X/Z coordinates to a 2D preview-only face model."""
    return FaceModel(
        source_dxf=source_dxf,
        nodes=tuple(Node2D(id=node.id, x=node.x, y=node.z) for node in geometry.nodes),
        members=tuple(
            Member2D(
                id=member.id,
                start_node_id=member.start_node_id,
                end_node_id=member.end_node_id,
            )
            for member in geometry.members
        ),
        centerline_candidates=(),
        warnings=geometry.warnings,
    )


def _part_preview_global_model(geometry: PartGeometry) -> GlobalModel:
    return GlobalModel(
        project_name=f"{geometry.part_id} preview",
        nodes=geometry.nodes,
        members=geometry.members,
        member_sources={
            member.id: {"part_id": geometry.part_id, "part_type": geometry.part_type}
            for member in geometry.members
        },
        warnings=geometry.warnings,
    )


def _prepare_embedded_main_window(window: QMainWindow) -> None:
    window.setWindowFlags(Qt.WindowType.Widget)
    window.setParent(None)
    window.menuBar().setNativeMenuBar(False)


def _first_roof_dxf_path() -> Path:
    drawings = PROJECT_ROOT / "drawings"
    roof_files = sorted(drawings.glob("*roof*.dxf"))
    if roof_files:
        return roof_files[0]
    dxf_files = sorted(drawings.glob("*.dxf"))
    if dxf_files:
        return dxf_files[0]
    return drawings / "roof.dxf"


def _roof_boundary_offset_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(-1_000_000.0, 1_000_000.0)
    spin.setDecimals(4)
    spin.setSingleStep(0.01)
    spin.setValue(0.0)
    return spin


def _side_wall_distance_spin(
    value: float,
    *,
    decimals: int = 4,
    step: float = 0.1,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(-1_000_000.0, 1_000_000.0)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setValue(value)
    return spin


def _project_iso(x: float, y: float, z: float) -> tuple[float, float]:
    """Project global XYZ coordinates into a simple isometric screen plane."""
    return (float(x) - float(z), (float(x) + float(z)) * 0.5 - float(y))


def _part_color(entity_id: str, source: dict[str, str] | None = None) -> QColor:
    part_id = (source or {}).get("part_id", "")
    part_type = (source or {}).get("part_type", "")
    if part_id == "base" or part_type == "base":
        return QColor("#4b5563")
    if part_id == "roof" or part_type == "roof":
        return QColor("#16a34a")
    if "wall" in part_id or "wall" in part_type:
        return QColor("#2563eb")
    if entity_id.startswith("base."):
        return QColor("#4b5563")
    if entity_id.startswith("roof."):
        return QColor("#16a34a")
    if "wall" in entity_id:
        return QColor("#2563eb")
    return QColor("#6b7280")


def _replace_visible_text(root: QWidget, replacements: dict[str, str]) -> None:
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if hasattr(widget, "text") and hasattr(widget, "setText"):
            text = widget.text()  # type: ignore[attr-defined]
            if isinstance(text, str):
                for old, new in replacements.items():
                    text = text.replace(old, new)
                widget.setText(text)  # type: ignore[attr-defined]
        if hasattr(widget, "title") and hasattr(widget, "setTitle"):
            title = widget.title()  # type: ignore[attr-defined]
            if isinstance(title, str):
                for old, new in replacements.items():
                    title = title.replace(old, new)
                widget.setTitle(title)  # type: ignore[attr-defined]
        if isinstance(widget, QMainWindow):
            title = widget.windowTitle()
            for old, new in replacements.items():
                title = title.replace(old, new)
            widget.setWindowTitle(title)


def _readonly_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
    return item


def _format_float(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


if __name__ == "__main__":
    raise SystemExit(main())
