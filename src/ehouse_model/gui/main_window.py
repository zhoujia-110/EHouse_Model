"""PySide6 GUI for the first base-only workflow."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ehouse_model.base_processing import (
    BaseProcessingOptions,
    export_base_staad,
    extract_base_face,
)
from ehouse_model.domain import Node2D
from ehouse_model.face_extractor import FaceExtractionOptions
from ehouse_model.face_model import FaceModel, write_face_model_json

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MM_PER_METER = 1000.0


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
        self._highlighted_node_id: str | None = None
        self._highlighted_member_id: str | None = None
        self._view_bounds = QRectF(0, 0, 1, 1)
        self._pick_radius_pixels = 10.0
        self._member_pick_radius_pixels = 8.0

    def set_face_model(self, model: FaceModel | None) -> None:
        self._model = model
        self._redraw()

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
        line_pen = QPen(QColor("#4b5563"))
        line_pen.setWidthF(0)
        line_pen.setCosmetic(True)
        node_pen = QPen(QColor("#111827"))
        node_pen.setWidthF(0)
        node_pen.setCosmetic(True)
        node_brush = QBrush(QColor("#111827"))

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

        bounds = _model_bounds(model)
        margin = max(max(bounds.width(), bounds.height()) * 0.05, 0.5)
        self._view_bounds = bounds.adjusted(-margin, -margin, margin, margin)
        self.scene.setSceneRect(self._view_bounds)
        self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._view_bounds.isValid() and not self._view_bounds.isNull():
            self.fitInView(self._view_bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("E-House 底座几何提取工具")
        self.resize(1220, 820)
        self.face_model: FaceModel | None = None
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
        self.snap_tolerance_spin = _distance_spin(0.2)

        grid.addWidget(QLabel("底座DXF"), 0, 0)
        grid.addWidget(_path_row(self.dxf_path_edit, self.select_dxf_file), 0, 1, 1, 3)
        grid.addWidget(QLabel("输出STD"), 1, 0)
        grid.addWidget(_path_row(self.std_path_edit, self.select_std_file), 1, 1, 1, 3)
        grid.addWidget(QLabel("最大配对宽度(m)"), 2, 0)
        grid.addWidget(self.max_pair_width_spin, 2, 1)
        grid.addWidget(QLabel("最大延伸上限(m)"), 2, 2)
        grid.addWidget(self.snap_tolerance_spin, 2, 3)

        button_row = QHBoxLayout()
        recognize_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "识别底座")
        recognize_button.clicked.connect(self.recognize_base)
        save_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "保存修正")
        save_button.clicked.connect(self.save_corrections)
        export_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon), "导出STD")
        export_button.clicked.connect(self.export_std)
        open_button = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "打开输出文件夹")
        open_button.clicked.connect(self.open_output_folder)
        button_row.addWidget(recognize_button)
        button_row.addWidget(save_button)
        button_row.addWidget(export_button)
        button_row.addWidget(open_button)
        button_row.addStretch()
        grid.addLayout(button_row, 3, 0, 1, 4)

        main_layout.addWidget(box)

    def _build_result_panel(self, main_layout: QVBoxLayout) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        preview_box = QGroupBox("中心线预览")
        preview_layout = QVBoxLayout(preview_box)
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
            dxf_path = Path(self.dxf_path_edit.text())
            std_path = Path(self.std_path_edit.text())
            output_dir = std_path.parent
            max_pair_width_m = self.max_pair_width_spin.value()
            extraction_options = FaceExtractionOptions(
                max_pair_width=None if max_pair_width_m == 0 else max_pair_width_m * MM_PER_METER
            )
            result = extract_base_face(
                dxf_path,
                face_model_path=output_dir / "face_model.json",
                overlay_path=output_dir / "centerline_overlay.dxf",
                warnings_csv_path=output_dir / "warnings.csv",
                extraction_options=extraction_options,
                base_options=BaseProcessingOptions(
                    snap_extend_tolerance=self.snap_tolerance_spin.value() * MM_PER_METER
                ),
            )
            self.face_model = result.face_model
            self.preview.set_face_model(self.face_model)
            self.populate_tables()
            self.select_origin_node_row()
            self._log(
                f"识别完成：节点 {len(self.face_model.nodes)} 个，构件 {len(self.face_model.members)} 个，"
                f"吸附延伸端点 {result.snap_count} 个，"
                f"裁剪端部构件 {result.terminal_stub_removed_count} 根，"
                f"原点=({result.origin[0]:.4f}, {result.origin[1]:.4f})m。"
            )
            if self.face_model.warnings:
                for warning in self.face_model.warnings:
                    self._log(f"{warning.id} {warning.level} {warning.code}: {warning.message}")
        except Exception as exc:
            self._show_error("识别底座失败", exc)

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

    def node_table_current_item_changed(
        self,
        current: QTableWidgetItem | None,
        previous: QTableWidgetItem | None,
    ) -> None:
        if self._updating_tables or self.face_model is None or current is None:
            return
        node_item = self.node_table.item(current.row(), 0)
        self.preview.set_highlighted_node(node_item.text() if node_item else None)

    def member_table_current_item_changed(
        self,
        current: QTableWidgetItem | None,
        previous: QTableWidgetItem | None,
    ) -> None:
        if self._updating_tables or self.face_model is None or current is None:
            return
        member_item = self.member_table.item(current.row(), 0)
        self.preview.set_highlighted_member(member_item.text() if member_item else None)

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
                return

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


def _model_bounds(model: FaceModel) -> QRectF:
    if not model.nodes:
        return QRectF(0, 0, 1, 1)
    xs = [node.x for node in model.nodes]
    ys = [node.y for node in model.nodes]
    min_x = min(xs)
    min_y = min(ys)
    width = max(max(xs) - min_x, 1e-6)
    height = max(max(ys) - min_y, 1e-6)
    return QRectF(min_x, min_y, width, height)


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
