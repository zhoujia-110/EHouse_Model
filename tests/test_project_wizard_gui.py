import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ehouse_model.gui.app import _prepare_qt_runtime

_prepare_qt_runtime()

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QGroupBox, QLabel, QPushButton

import ezdxf

from ehouse_model.domain import Member2D, Member3D, Node2D, Node3D
from ehouse_model.face_model import FaceModel
from ehouse_model.gui.main_window import MainWindow as BaseRecognitionWindow
from ehouse_model.gui.preprocess_window import PreprocessWorkbenchWindow
from ehouse_model.gui.project_wizard import ProjectWizardWindow, RoofRecognitionWindow, _project_iso
from ehouse_model.part_geometry import PartGeometry


def test_project_wizard_has_centralized_tool_actions():
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
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
            assert key in window.actions

        window.tabs.setCurrentWidget(window.preprocess_page)
        assert not window.actions["recognize"].isEnabled()

        window.tabs.setCurrentWidget(window.base_page)
        assert window.actions["recognize"].isEnabled()
        assert window.actions["local_patch"].isEnabled()
        assert isinstance(window.preprocess_workbench, PreprocessWorkbenchWindow)
        assert isinstance(window.base_page.workbench, BaseRecognitionWindow)
        assert isinstance(window.roof_page.workbench, RoofRecognitionWindow)
        assert app is not None
    finally:
        window.close()


def test_project_wizard_imports_modified_std_into_current_part(tmp_path):
    std_path = tmp_path / "base_modified.std"
    std_path.write_text(
        "\n".join(
            [
                "STAAD SPACE",
                "UNIT METER KN",
                "JOINT COORDINATES",
                "1 0 0 0;",
                "2 1 0 0;",
                "MEMBER INCIDENCES",
                "1 1 2;",
                "FINISH",
            ]
        ),
        encoding="utf-8",
    )
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.tabs.setCurrentWidget(window.base_page)
        part = window.import_modified_std(std_path)

        assert part.part_id == "base"
        assert window.base_page.part_geometry == part
        assert window.current_global_model is not None
        assert window.parts_table.rowCount() == 1
        assert window.actions["export_global"].isEnabled()
        assert app is not None
    finally:
        window.close()


def test_project_wizard_preprocesses_dxf_and_records_outputs(tmp_path):
    dxf_path = tmp_path / "base.dxf"
    _write_base_rectangles(dxf_path)
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        result = window.preprocess_dxf_file(dxf_path, part_id="base")

        assert result.clean_dxf_path.exists()
        assert result.overlay_dxf_path.exists()
        assert result.report_csv_path.exists()
        assert window.drawing_table.rowCount() == 1
        assert window.drawing_table.item(0, 0).text() == "base"
        assert window.drawing_table.item(0, 2).text() == str(result.clean_dxf_path)
        assert app is not None
    finally:
        window.close()


def test_project_wizard_recognizes_and_confirms_base_dxf(tmp_path):
    dxf_path = tmp_path / "base_clean.dxf"
    _write_base_rectangles(dxf_path)
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.tabs.setCurrentWidget(window.base_page)
        window.base_page.face_model_edit.setText(str(dxf_path))

        face_model = window.recognize_base_from_input()

        assert face_model.nodes
        assert window.base_page.workbench.face_model == face_model
        assert window.base_page.part_geometry is None

        part = window.confirm_base_recognition()

        assert part.part_id == "base"
        assert window.base_page.part_geometry == part
        assert (window.current_global_model is not None)
        assert (window.parts_table.rowCount() == 1)
        assert app is not None
    finally:
        window.close()


def test_project_wizard_recognizes_and_confirms_roof_dxf_with_y_plane(tmp_path):
    dxf_path = tmp_path / "roof_clean.dxf"
    _write_base_rectangles(dxf_path)
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.tabs.setCurrentWidget(window.roof_page)
        window.roof_page.face_model_edit.setText(str(dxf_path))
        window.roof_page.workbench.roof_y_spin.setValue(4.25)

        face_model = window.recognize_roof_from_input()

        assert face_model.nodes
        assert window.roof_page.workbench.face_model == face_model
        assert window.roof_page.part_geometry is None

        part = window.confirm_roof_recognition()

        assert part.part_id == "roof"
        assert window.roof_page.part_geometry == part
        assert {node.y for node in part.nodes} == {4.25}
        assert window.current_global_model is not None
        assert window.parts_table.rowCount() == 1
        assert app is not None
    finally:
        window.close()


def test_project_wizard_applies_roof_boundary_offsets_without_moving_base():
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.base_page.workbench.face_model = FaceModel(
            source_dxf="base.dxf",
            nodes=(Node2D(id="BN1", x=5.0, y=7.0), Node2D(id="BN2", x=15.0, y=17.0)),
            members=(Member2D(id="BM1", start_node_id="BN1", end_node_id="BN2"),),
            centerline_candidates=(),
        )
        base_part = window.confirm_base_recognition()
        base_coordinates = tuple((node.id, node.x, node.y, node.z) for node in base_part.nodes)

        window.roof_page.workbench.face_model = FaceModel(
            source_dxf="roof.dxf",
            nodes=(
                Node2D(id="LT", x=10.0, y=20.0),
                Node2D(id="RT", x=110.0, y=20.0),
                Node2D(id="LB", x=10.0, y=70.0),
                Node2D(id="RB", x=110.0, y=70.0),
                Node2D(id="MID", x=60.0, y=45.0),
            ),
            members=(Member2D(id="RM1", start_node_id="LT", end_node_id="RB"),),
            centerline_candidates=(),
        )
        window.roof_page.workbench.roof_y_spin.setValue(6.0)
        window.roof_page.workbench.roof_left_dx_spin.setValue(-2.0)
        window.roof_page.workbench.roof_right_dx_spin.setValue(3.0)
        window.roof_page.workbench.roof_top_dz_spin.setValue(5.0)
        window.roof_page.workbench.roof_bottom_dz_spin.setValue(-1.0)

        roof_part = window.confirm_roof_recognition()

        assert tuple((node.id, node.x, node.y, node.z) for node in window.confirmed_parts["base"].nodes) == base_coordinates
        assert [(node.id, node.x, node.y, node.z) for node in roof_part.nodes] == [
            ("LT", 0.0, 6.0, 0.0),
            ("RT", 105.0, 6.0, 0.0),
            ("LB", 0.0, 6.0, 44.0),
            ("RB", 105.0, 6.0, 44.0),
            ("MID", 52.0, 6.0, 20.0),
        ]
        model = window.refresh_stitching()
        assert [node.id for node in model.nodes[:2]] == ["10001", "10002"]
        assert model.nodes[2].id == "20001"
        assert app is not None
    finally:
        window.close()


def test_global_preview_projection_uses_3d_axes():
    origin = _project_iso(0.0, 0.0, 0.0)
    x_axis = _project_iso(1.0, 0.0, 0.0)
    y_axis = _project_iso(0.0, 1.0, 0.0)
    z_axis = _project_iso(0.0, 0.0, 1.0)
    base_point = _project_iso(2.0, 0.0, 1.0)
    roof_point = _project_iso(2.0, 3.0, 1.0)

    assert len({origin, x_axis, y_axis, z_axis}) == 4
    assert base_point[0] == roof_point[0]
    assert roof_point[1] < base_point[1]


def test_roof_page_visible_labels_do_not_use_base_word():
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        texts: list[str] = []
        texts.extend(widget.text() for widget in window.roof_page.findChildren(QLabel))
        texts.extend(widget.text() for widget in window.roof_page.findChildren(QPushButton))
        texts.extend(widget.title() for widget in window.roof_page.findChildren(QGroupBox))

        assert not any("底座" in text for text in texts)
        assert any("屋盖" in text for text in texts)
        assert app is not None
    finally:
        window.close()


def test_roof_page_has_boundary_offset_inputs():
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        assert isinstance(window.roof_page.workbench.roof_left_dx_spin, QDoubleSpinBox)
        assert isinstance(window.roof_page.workbench.roof_right_dx_spin, QDoubleSpinBox)
        assert isinstance(window.roof_page.workbench.roof_top_dz_spin, QDoubleSpinBox)
        assert isinstance(window.roof_page.workbench.roof_bottom_dz_spin, QDoubleSpinBox)
        assert window.roof_page.workbench.roof_boundary_offsets.left_dx == 0.0
        assert window.roof_page.workbench.roof_boundary_offsets.right_dx == 0.0
        assert window.roof_page.workbench.roof_boundary_offsets.top_dz == 0.0
        assert window.roof_page.workbench.roof_boundary_offsets.bottom_dz == 0.0
        assert window.roof_page.workbench.apply_roof_offsets_button.text() == "应用偏移并刷新预览/拼接"
        assert app is not None
    finally:
        window.close()


def test_roof_apply_offsets_button_reconfirms_and_refreshes_stitching():
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.roof_page.workbench.face_model = FaceModel(
            source_dxf="roof.dxf",
            nodes=(
                Node2D(id="LT", x=10.0, y=20.0),
                Node2D(id="RB", x=110.0, y=70.0),
            ),
            members=(Member2D(id="RM1", start_node_id="LT", end_node_id="RB"),),
            centerline_candidates=(),
        )
        window.roof_page.workbench.roof_y_spin.setValue(4.0)
        initial_part = window.confirm_roof_recognition()

        assert [(node.x, node.y, node.z) for node in initial_part.nodes] == [
            (0.0, 4.0, 0.0),
            (100.0, 4.0, 50.0),
        ]
        assert [(node.x, node.y) for node in window.roof_page.workbench.preview._model.nodes] == [
            (0.0, 0.0),
            (100.0, 50.0),
        ]

        window.roof_page.workbench.roof_left_dx_spin.setValue(-2.0)
        window.roof_page.workbench.roof_right_dx_spin.setValue(3.0)
        window.roof_page.workbench.roof_top_dz_spin.setValue(5.0)
        window.roof_page.workbench.roof_bottom_dz_spin.setValue(-1.0)

        assert window.roof_page.status_label.text() == "偏移已修改待应用"

        window.roof_page.workbench.apply_roof_offsets_button.click()
        updated_part = window.confirmed_parts["roof"]

        assert [(node.x, node.y, node.z) for node in updated_part.nodes] == [
            (0.0, 4.0, 0.0),
            (105.0, 4.0, 44.0),
        ]
        assert [(node.x, node.y) for node in window.roof_page.workbench.preview._model.nodes] == [
            (0.0, 0.0),
            (105.0, 44.0),
        ]
        assert [(node.x, node.y) for node in window.roof_page.workbench.face_model.nodes] == [
            (10.0, 20.0),
            (110.0, 70.0),
        ]
        assert window.current_global_model is not None
        assert [(node.x, node.y, node.z) for node in window.current_global_model.nodes] == [
            (0.0, 4.0, 0.0),
            (105.0, 4.0, 44.0),
        ]
        assert app is not None
    finally:
        window.close()


def test_project_wizard_recognizes_confirms_side_wall_plan_and_reuses_nodes(tmp_path):
    dxf_path = tmp_path / "side_wall_plan.dxf"
    _write_side_wall_marker(dxf_path, center=(0.2, 2.0))
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.set_part_geometry(
            PartGeometry(
                part_id="base",
                part_type="base",
                nodes=(Node3D(id="B1", x=0.0, y=0.0, z=2.0),),
                members=(),
            )
        )
        window.set_part_geometry(
            PartGeometry(
                part_id="roof",
                part_type="roof",
                nodes=(Node3D(id="R1", x=0.0, y=3.5, z=2.0),),
                members=(),
            )
        )

        window.tabs.setCurrentWidget(window.side_wall_page)
        window.side_wall_page.face_model_edit.setText(str(dxf_path))
        window.side_wall_page.top_y_spin.setValue(3.5)
        window.side_wall_page.reuse_tolerance_spin.setValue(0.001)
        window.side_wall_page.face_controls["left"]["fixed"].setValue(0.0)
        window.side_wall_page.face_controls["left"]["filter_min"].setValue(0.0)
        window.side_wall_page.face_controls["left"]["filter_max"].setValue(0.5)

        part = window.recognize_side_wall_from_input()

        assert part.part_id == "side_wall"
        assert [(node.x, node.y, node.z) for node in part.nodes] == [
            (0.0, 0.0, 2.0),
            (0.0, 3.5, 2.0),
        ]
        assert window.side_wall_page.preview._model is not None

        confirmed = window.confirm_side_wall_recognition()
        model = window.current_global_model

        assert window.side_wall_page.part_geometry == confirmed
        assert model is not None
        assert [node.id for node in model.nodes] == ["10001", "20001"]
        assert [(member.id, member.start_node_id, member.end_node_id) for member in model.members] == [
            ("30001", "10001", "20001")
        ]
        assert app is not None
    finally:
        window.close()


def test_project_wizard_stitches_and_exports_confirmed_base_and_roof(tmp_path):
    base_dxf = tmp_path / "base_clean.dxf"
    roof_dxf = tmp_path / "roof_clean.dxf"
    _write_base_rectangles(base_dxf)
    _write_base_rectangles(roof_dxf)
    output_dir = tmp_path / "global_output"
    app = QApplication.instance() or QApplication([])
    window = ProjectWizardWindow()
    try:
        window.tabs.setCurrentWidget(window.base_page)
        window.base_page.face_model_edit.setText(str(base_dxf))
        window.recognize_base_from_input()
        window.confirm_base_recognition()

        window.tabs.setCurrentWidget(window.roof_page)
        window.roof_page.face_model_edit.setText(str(roof_dxf))
        window.roof_page.workbench.roof_y_spin.setValue(3.5)
        window.recognize_roof_from_input()
        window.confirm_roof_recognition()

        model = window.refresh_stitching()

        assert set(window.confirmed_parts) == {"base", "roof"}
        assert window.parts_table.rowCount() == 2
        assert {node.y for node in window.confirmed_parts["roof"].nodes} == {3.5}
        assert model.nodes[0].id == "10001"
        assert model.nodes[len(window.confirmed_parts["base"].nodes)].id == "20001"
        assert {node.y for node in model.nodes if node.id.startswith("200")} == {3.5}
        assert all(node.y == 0.0 for node in model.nodes if node.id.startswith("100"))
        assert model.member_sources[model.members[0].id]["part_id"] == "base"
        assert window.global_preview._model == model

        window.output_dir_edit.setText(str(output_dir))
        window._choose_export_global_outputs()

        assert (output_dir / "global_model.json").exists()
        assert (output_dir / "nodes.csv").exists()
        assert (output_dir / "members.csv").exists()
        assert (output_dir / "warnings.csv").exists()
        assert (output_dir / "geometry.std").exists()
        assert (output_dir / "base_part_geometry.json").exists()
        assert (output_dir / "roof_part_geometry.json").exists()
        assert app is not None
    finally:
        window.close()


def _write_base_rectangles(path):
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (1000, 0))
    modelspace.add_line((0, 100), (1000, 100))
    modelspace.add_line((0, 0), (0, 100))
    modelspace.add_line((1000, 0), (1000, 100))
    modelspace.add_line((400, -300), (400, 400))
    modelspace.add_line((500, -300), (500, 400))
    doc.saveas(path)


def _write_side_wall_marker(path, *, center):
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    cx, cy = center
    modelspace.add_lwpolyline(
        [
            (cx - 0.05, cy - 0.05),
            (cx + 0.05, cy - 0.05),
            (cx + 0.05, cy + 0.05),
            (cx - 0.05, cy + 0.05),
        ],
        close=True,
    )
    doc.saveas(path)
