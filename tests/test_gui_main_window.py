import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ehouse_model.gui.app import _prepare_qt_runtime

_prepare_qt_runtime()

from PySide6.QtWidgets import QApplication

from ehouse_model.correction_tools import CORRECTION_SHORT_MEMBER
from ehouse_model.domain import Member2D, Node2D
from ehouse_model.face_model import FaceModel
from ehouse_model.gui.main_window import CorrectionToolDialog, MainWindow, _model_delta


def test_main_window_maps_initial_width_ratio_to_extraction_options():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.max_pair_width_spin.setValue(0.25)
        window.pair_width_ratio_spin.setValue(0.8)
        window.snap_tolerance_spin.setValue(0.35)

        extraction_options = window._current_extraction_options()
        base_options = window._current_base_options()

        assert extraction_options.max_pair_width == pytest.approx(250.0)
        assert extraction_options.max_pair_width_to_length_ratio == pytest.approx(0.8)
        assert base_options.snap_extend_tolerance == pytest.approx(350.0)
        assert app is not None
    finally:
        window.close()


def test_short_member_dialog_builds_adjustable_correction_step():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    dialog = CorrectionToolDialog(
        CORRECTION_SHORT_MEMBER,
        "短构件修正",
        window._current_extraction_options(),
        window._current_base_options(),
        window,
    )
    try:
        dialog.short_radius_spin.setValue(0.45)
        dialog.short_max_length_spin.setValue(0.85)
        dialog.short_width_ratio_spin.setValue(1.75)
        dialog.short_overlap_ratio_spin.setValue(0.5)
        dialog.short_max_candidates_spin.setValue(4)

        step = dialog.build_step((100.0, 200.0))
        cleanup = step.base_options.centerline_cleanup_options

        assert step.kind == CORRECTION_SHORT_MEMBER
        assert step.point == pytest.approx((100.0, 200.0))
        assert cleanup.short_member_radius == pytest.approx(450.0)
        assert cleanup.short_member_max_length == pytest.approx(850.0)
        assert cleanup.short_member_max_width_to_length_ratio == pytest.approx(1.75)
        assert cleanup.min_overlap_ratio == pytest.approx(0.5)
        assert cleanup.short_member_max_candidates_per_point == 4
        assert app is not None
    finally:
        dialog.close()
        window.close()


def test_main_window_undo_restores_node_coordinate_edit():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(Node2D(id="N1", x=0.0, y=0.0), Node2D(id="N2", x=1.0, y=0.0)),
        members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
        centerline_candidates=(),
    )
    try:
        window._set_model_state(model, (), (0.0, 0.0), reset_view=True)
        window.node_table.setCurrentCell(0, 1)
        window.node_table.item(0, 1).setText("2.0000")

        assert window.face_model.nodes[0].x == pytest.approx(2.0)
        assert len(window.undo_stack) == 1

        window.undo_last_action(silent=True)

        assert window.face_model.nodes[0].x == pytest.approx(0.0)
        assert window.node_table.item(0, 1).text() == "0.0000"
        assert app is not None
    finally:
        window.close()


def test_model_delta_reports_geometry_added_node_and_member_ids():
    before = FaceModel(
        source_dxf="base.dxf",
        nodes=(Node2D(id="N1", x=0.0, y=0.0), Node2D(id="N2", x=1.0, y=0.0)),
        members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
        centerline_candidates=(),
    )
    after = FaceModel(
        source_dxf="base.dxf",
        nodes=(
            Node2D(id="N7", x=0.0, y=0.0),
            Node2D(id="N8", x=1.0, y=0.0),
            Node2D(id="N9", x=1.0, y=1.0),
        ),
        members=(
            Member2D(id="M7", start_node_id="N7", end_node_id="N8"),
            Member2D(id="M8", start_node_id="N8", end_node_id="N9"),
        ),
        centerline_candidates=(),
    )

    delta = _model_delta(before, after)

    assert delta.node_ids == ("N9",)
    assert delta.member_ids == ("M8",)


def test_main_window_jump_to_delta_selects_new_rows():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(
            Node2D(id="N1", x=0.0, y=0.0),
            Node2D(id="N2", x=1.0, y=0.0),
            Node2D(id="N3", x=1.0, y=1.0),
        ),
        members=(
            Member2D(id="M1", start_node_id="N1", end_node_id="N2"),
            Member2D(id="M2", start_node_id="N2", end_node_id="N3"),
        ),
        centerline_candidates=(),
    )
    try:
        window._set_model_state(model, (), (0.0, 0.0), reset_view=True)

        window._jump_to_delta(
            _model_delta(
                FaceModel(
                    source_dxf="base.dxf",
                    nodes=(Node2D(id="N1", x=0.0, y=0.0), Node2D(id="N2", x=1.0, y=0.0)),
                    members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
                    centerline_candidates=(),
                ),
                model,
            ),
            fallback_point=(0.0, 0.0),
        )

        assert window.node_table.item(window.node_table.currentRow(), 0).text() == "N3"
        assert window.member_table.item(window.member_table.currentRow(), 0).text() == "M2"
        assert app is not None
    finally:
        window.close()
