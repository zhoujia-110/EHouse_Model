import ezdxf

from ehouse_model.side_wall_plan_processing import (
    SideWallFacePlanSpec,
    SideWallPlanOptions,
    extract_section_marker_centroids,
    extract_side_wall_plan,
)
from ehouse_model.dxf_reader import read_dxf_segments


def test_extract_section_marker_centroids_merges_duplicate_inner_outer_loops(tmp_path):
    dxf_path = tmp_path / "markers.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    _add_closed_rectangle(modelspace, center=(1.0, 2.0), width=1.0, height=1.0)
    _add_closed_rectangle(modelspace, center=(1.0, 2.0), width=0.5, height=0.5)
    doc.saveas(dxf_path)

    centroids, warnings = extract_section_marker_centroids(
        read_dxf_segments(dxf_path),
        duplicate_tolerance=0.01,
    )

    assert [(centroid.x, centroid.z) for centroid in centroids] == [(1.0, 2.0)]
    assert any(warning.code == "duplicate_section_marker_merged" for warning in warnings)


def test_side_wall_plan_assigns_four_faces_and_generates_vertical_members(tmp_path):
    dxf_path = tmp_path / "side_wall_plan.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    _add_closed_rectangle(modelspace, center=(0.2, 2.0), width=0.1, height=0.1)
    _add_closed_rectangle(modelspace, center=(9.8, 3.0), width=0.1, height=0.1)
    _add_closed_rectangle(modelspace, center=(4.0, 0.2), width=0.1, height=0.1)
    _add_closed_rectangle(modelspace, center=(5.0, 7.8), width=0.1, height=0.1)
    doc.saveas(dxf_path)

    part = extract_side_wall_plan(
        dxf_path,
        SideWallPlanOptions(
            top_y=3.5,
            duplicate_tolerance=0.001,
            face_specs=(
                SideWallFacePlanSpec("left", "X", 0.0, "X", 0.0, 0.5),
                SideWallFacePlanSpec("right", "X", 10.0, "X", 9.5, 10.0),
                SideWallFacePlanSpec("top", "Z", 0.0, "Z", 0.0, 0.5),
                SideWallFacePlanSpec("bottom", "Z", 8.0, "Z", 7.5, 8.0),
            ),
        ),
    )

    assert part.part_id == "side_wall"
    assert len(part.nodes) == 8
    assert len(part.members) == 4
    assert [(node.x, node.y, node.z) for node in part.nodes] == [
        (0.0, 0.0, 2.0),
        (0.0, 3.5, 2.0),
        (10.0, 0.0, 3.0),
        (10.0, 3.5, 3.0),
        (4.0, 0.0, 0.0),
        (4.0, 3.5, 0.0),
        (5.0, 0.0, 8.0),
        (5.0, 3.5, 8.0),
    ]


def test_side_wall_plan_warns_for_unmatched_section_marker(tmp_path):
    dxf_path = tmp_path / "side_wall_plan.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    _add_closed_rectangle(modelspace, center=(5.0, 5.0), width=0.1, height=0.1)
    doc.saveas(dxf_path)

    part = extract_side_wall_plan(
        dxf_path,
        SideWallPlanOptions(
            top_y=3.5,
            face_specs=(
                SideWallFacePlanSpec("left", "X", 0.0, "X", 0.0, 0.5),
            ),
        ),
    )

    assert part.nodes == ()
    assert part.members == ()
    assert any(warning.code == "section_marker_unmatched" for warning in part.warnings)


def _add_closed_rectangle(modelspace, *, center, width, height):
    cx, cy = center
    half_w = width / 2.0
    half_h = height / 2.0
    modelspace.add_lwpolyline(
        [
            (cx - half_w, cy - half_h),
            (cx + half_w, cy - half_h),
            (cx + half_w, cy + half_h),
            (cx - half_w, cy + half_h),
        ],
        close=True,
    )
