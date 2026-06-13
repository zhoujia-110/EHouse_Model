import pytest

from ehouse_model.base_processing import (
    export_base_staad,
    face_model_to_base_global_model,
    normalize_base_coordinates,
    prune_base_terminal_stubs,
    snap_extend_centerlines,
)
from ehouse_model.domain import Member2D, Node2D
from ehouse_model.face_model import CenterlineCandidate, FaceModel


def test_normalize_base_coordinates_uses_top_left_node_as_origin():
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(
            Node2D(id="N1", x=10, y=100),
            Node2D(id="N2", x=30, y=100),
            Node2D(id="N3", x=10, y=80),
        ),
        members=(
            Member2D(id="M1", start_node_id="N1", end_node_id="N2"),
            Member2D(id="M2", start_node_id="N1", end_node_id="N3"),
        ),
        centerline_candidates=(),
    )

    result = normalize_base_coordinates(model)

    assert result.origin == (0.01, 0.1)
    assert [(node.id, node.x, node.y) for node in result.face_model.nodes] == [
        ("N1", 0.0, 0.0),
        ("N2", 0.02, 0.0),
        ("N3", 0.0, 0.02),
    ]


def test_normalize_base_coordinates_uses_top_left_intersection_not_dangling_endpoint():
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(
            Node2D(id="N0", x=0, y=100),
            Node2D(id="N1", x=10, y=100),
            Node2D(id="N2", x=10, y=80),
            Node2D(id="N3", x=30, y=100),
        ),
        members=(
            Member2D(id="M0", start_node_id="N0", end_node_id="N1"),
            Member2D(id="M1", start_node_id="N1", end_node_id="N2"),
            Member2D(id="M2", start_node_id="N1", end_node_id="N3"),
        ),
        centerline_candidates=(),
    )

    result = normalize_base_coordinates(model)

    assert result.origin == (0.01, 0.1)
    assert [(node.id, node.x, node.y) for node in result.face_model.nodes] == [
        ("N0", -0.01, 0.0),
        ("N1", 0.0, 0.0),
        ("N2", 0.0, 0.02),
        ("N3", 0.02, 0.0),
    ]


def test_prune_base_terminal_stubs_removes_members_outside_left_right_boundaries():
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(
            Node2D(id="NL", x=-10, y=100),
            Node2D(id="N1", x=0, y=100),
            Node2D(id="N2", x=0, y=0),
            Node2D(id="N3", x=100, y=100),
            Node2D(id="N4", x=100, y=0),
            Node2D(id="NR", x=110, y=100),
        ),
        members=(
            Member2D(id="ML", start_node_id="NL", end_node_id="N1"),
            Member2D(id="M1", start_node_id="N1", end_node_id="N2"),
            Member2D(id="M2", start_node_id="N1", end_node_id="N3"),
            Member2D(id="M3", start_node_id="N3", end_node_id="N4"),
            Member2D(id="MR", start_node_id="N3", end_node_id="NR"),
        ),
        centerline_candidates=(),
        member_sources={
            "ML": "C0",
            "M1": "C1",
            "M2": "C2",
            "M3": "C3",
            "MR": "C4",
        },
    )

    pruned, removed_count = prune_base_terminal_stubs(model)

    assert removed_count == 2
    assert [member.id for member in pruned.members] == ["M1", "M2", "M3"]
    assert [node.id for node in pruned.nodes] == ["N1", "N2", "N3", "N4"]
    assert pruned.member_sources == {"M1": "C1", "M2": "C2", "M3": "C3"}


def test_snap_extend_centerlines_extends_endpoint_to_near_intersection():
    horizontal = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(9, 0),
        source_segment_ids=("A", "B"),
        width=1,
        overlap=9,
    )
    vertical = CenterlineCandidate(
        id="C2",
        start=(10, -5),
        end=(10, 5),
        source_segment_ids=("C", "D"),
        width=1,
        overlap=10,
    )

    snapped, snap_count, warnings = snap_extend_centerlines(
        [horizontal, vertical],
        tolerance=2,
    )

    assert snap_count == 1
    assert warnings[0].code == "base_centerlines_extended"
    assert snapped[0].start == pytest.approx((0, 0))
    assert snapped[0].end == pytest.approx((10, 0))
    assert snapped[1].start == pytest.approx((10, -5))
    assert snapped[1].end == pytest.approx((10, 5))


def test_snap_extend_centerlines_uses_intersecting_member_width():
    horizontal = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(75, 0),
        source_segment_ids=("A", "B"),
        width=50,
        overlap=75,
    )
    vertical = CenterlineCandidate(
        id="C2",
        start=(100, -50),
        end=(100, 50),
        source_segment_ids=("C", "D"),
        width=50,
        overlap=100,
    )

    snapped, snap_count, _ = snap_extend_centerlines(
        [horizontal, vertical],
        tolerance=200,
    )

    assert snap_count == 1
    assert snapped[0].end == pytest.approx((100, 0))


def test_snap_extend_centerlines_rejects_gap_beyond_member_half_width_margin():
    horizontal = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(69, 0),
        source_segment_ids=("A", "B"),
        width=50,
        overlap=69,
    )
    vertical = CenterlineCandidate(
        id="C2",
        start=(100, -50),
        end=(100, 50),
        source_segment_ids=("C", "D"),
        width=50,
        overlap=100,
    )

    snapped, snap_count, warnings = snap_extend_centerlines(
        [horizontal, vertical],
        tolerance=200,
    )

    assert snap_count == 0
    assert warnings == ()
    assert snapped[0].end == pytest.approx((69, 0))


def test_snap_extend_centerlines_allows_larger_gap_for_wider_member():
    horizontal = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(100, 0),
        source_segment_ids=("A", "B"),
        width=50,
        overlap=100,
    )
    vertical = CenterlineCandidate(
        id="C2",
        start=(200, -50),
        end=(200, 50),
        source_segment_ids=("C", "D"),
        width=200,
        overlap=100,
    )

    snapped, snap_count, _ = snap_extend_centerlines(
        [horizontal, vertical],
        tolerance=200,
    )

    assert snap_count == 1
    assert snapped[0].end == pytest.approx((200, 0))


def test_base_global_model_maps_local_z_to_global_z():
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(Node2D(id="N1", x=1.25, y=2.5),),
        members=(),
        centerline_candidates=(),
    )

    global_model = face_model_to_base_global_model(model)

    assert [(node.id, node.x, node.y, node.z) for node in global_model.nodes] == [
        ("N1", 1.25, 0.0, 2.5)
    ]


def test_export_base_staad_uses_edited_meter_coordinates_with_four_decimals(tmp_path):
    output = tmp_path / "geometry.std"
    model = FaceModel(
        source_dxf="base.dxf",
        nodes=(
            Node2D(id="N1", x=0, y=0),
            Node2D(id="N2", x=12.3456, y=7.8912),
        ),
        members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
        centerline_candidates=(),
    )

    export_base_staad(model, output)

    text = output.read_text(encoding="utf-8")
    assert "UNIT METER KN" in text
    assert "2 12.3456 0 7.8912;" in text
    assert "MEMBER PROPERTY" not in text
    assert "DEFINE MATERIAL" not in text
    assert "SUPPORTS" not in text
    assert "LOAD" not in text
