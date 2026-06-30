import json

import pytest

from ehouse_model.domain import Member2D, Member3D, Node2D, Node3D
from ehouse_model.face_model import FaceModel
from ehouse_model.global_stitching import StitchOptions
from ehouse_model.part_assembly import build_global_model_from_parts, stitch_part_geometries
from ehouse_model.part_builders import (
    build_base_part_from_face_model,
    build_roof_part_from_face_model,
    build_vertical_wall_part_from_plan_points,
)
from ehouse_model.part_geometry import (
    PartGeometry,
    PartGeometrySource,
    load_part_geometry_json,
    write_part_geometry_json,
)
from ehouse_model.project_model import ProjectDimensions
from ehouse_model.staad_import import import_staad_part_geometry


def test_import_modified_std_converts_to_part_geometry(tmp_path):
    std_path = tmp_path / "left_wall_modified.std"
    std_path.write_text(
        "\n".join(
            [
                "STAAD SPACE",
                "UNIT METER KN",
                "JOINT COORDINATES",
                "1 0 0 0;",
                "2 0 3 0;",
                "MEMBER INCIDENCES",
                "1 1 2;",
                "FINISH",
            ]
        ),
        encoding="utf-8",
    )

    part = import_staad_part_geometry(std_path, part_id="left_wall", part_type="side_wall")

    assert part.part_id == "left_wall"
    assert part.source.kind == "imported_modified_std"
    assert [(node.id, node.x, node.y, node.z) for node in part.nodes] == [
        ("1", 0.0, 0.0, 0.0),
        ("2", 0.0, 3.0, 0.0),
    ]
    assert [(member.id, member.start_node_id, member.end_node_id) for member in part.members] == [
        ("1", "1", "2")
    ]


def test_part_geometry_json_round_trips(tmp_path):
    output = tmp_path / "base_part_geometry.json"
    part = PartGeometry(
        part_id="base",
        part_type="base",
        source=PartGeometrySource(kind="generated_from_dxf", path="base.dxf"),
        nodes=(Node3D(id="N1", x=0, y=0, z=0), Node3D(id="N2", x=1, y=0, z=0)),
        members=(Member3D(id="M1", start_node_id="N1", end_node_id="N2"),),
    )

    write_part_geometry_json(part, output)
    loaded = load_part_geometry_json(output)

    assert loaded == part
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["coordinate_space"] == "global"
    assert data["unit"] == "meter"


def test_confirmed_base_face_model_becomes_part_geometry():
    face = FaceModel(
        source_dxf="base.dxf",
        nodes=(Node2D(id="N1", x=0, y=0), Node2D(id="N2", x=2, y=1)),
        members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
        centerline_candidates=(),
    )

    part = build_base_part_from_face_model(face)

    assert part.part_type == "base"
    assert [(node.id, node.x, node.y, node.z) for node in part.nodes] == [
        ("N1", 0.0, 0.0, 0.0),
        ("N2", 2.0, 0.0, 1.0),
    ]


def test_roof_face_model_maps_to_project_height():
    face = FaceModel(
        source_dxf="roof.dxf",
        nodes=(Node2D(id="N1", x=1.5, y=2.5),),
        members=(),
        centerline_candidates=(),
    )

    part = build_roof_part_from_face_model(
        face,
        ProjectDimensions(length=10, height=3, width=4),
    )

    assert [(node.x, node.y, node.z) for node in part.nodes] == [(0.0, 3.0, 0.0)]


def test_side_wall_plan_centroids_generate_vertical_members():
    part = build_vertical_wall_part_from_plan_points(
        [(1.0, 0.05), (5.0, 0.05)],
        part_id="left_wall",
        wall_type="left_wall",
        height=3.0,
    )

    assert len(part.nodes) == 4
    assert len(part.members) == 2
    assert part.nodes[1] == Node3D(id="N1T", x=1.0, y=3.0, z=0.05)


def test_assembly_allows_missing_parts_and_directly_combines_confirmed_parts():
    base = PartGeometry(
        part_id="base",
        part_type="base",
        nodes=(Node3D(id="N1", x=0, y=0, z=0),),
        members=(),
    )
    wall = PartGeometry(
        part_id="left_wall",
        part_type="side_wall",
        nodes=(Node3D(id="N1", x=0.25, y=0, z=0), Node3D(id="N2", x=0.25, y=3, z=0)),
        members=(Member3D(id="M1", start_node_id="N1", end_node_id="N2"),),
    )

    direct = build_global_model_from_parts([base, wall])
    assembled = stitch_part_geometries(
        [base, wall],
        stitch_options=StitchOptions(merge_tolerance=0.5, review_tolerance=1.0),
    )

    assert [node.id for node in direct.nodes] == ["10001", "30001", "30002"]
    assert [member.id for member in direct.members] == ["30001"]
    assert direct.members[0].start_node_id == "30001"
    assert direct.node_sources["10001"]["local_node_id"] == "N1"
    assert assembled == direct
    assert assembled.warnings == ()


def test_side_wall_nodes_reuse_existing_base_and_roof_nodes():
    base = PartGeometry(
        part_id="base",
        part_type="base",
        nodes=(Node3D(id="B1", x=0.0, y=0.0, z=2.0),),
        members=(),
    )
    roof = PartGeometry(
        part_id="roof",
        part_type="roof",
        nodes=(Node3D(id="R1", x=0.0, y=3.0, z=2.0),),
        members=(),
    )
    wall = PartGeometry(
        part_id="side_wall",
        part_type="side_wall",
        nodes=(
            Node3D(id="W1B", x=0.0002, y=0.0, z=2.0002),
            Node3D(id="W1T", x=0.0003, y=3.0002, z=2.0001),
        ),
        members=(Member3D(id="W1", start_node_id="W1B", end_node_id="W1T"),),
    )

    model = build_global_model_from_parts(
        [wall, roof, base],
        node_reuse_tolerance=0.001,
    )

    assert [node.id for node in model.nodes] == ["10001", "20001"]
    assert [(member.id, member.start_node_id, member.end_node_id) for member in model.members] == [
        ("30001", "10001", "20001")
    ]
    assert model.member_sources["30001"]["start_reused_node_id"] == "10001"
    assert model.member_sources["30001"]["end_reused_node_id"] == "20001"


def test_side_wall_nodes_outside_reuse_tolerance_get_new_numbers():
    base = PartGeometry(
        part_id="base",
        part_type="base",
        nodes=(Node3D(id="B1", x=0.0, y=0.0, z=2.0),),
        members=(),
    )
    wall = PartGeometry(
        part_id="side_wall",
        part_type="side_wall",
        nodes=(
            Node3D(id="W1B", x=0.1, y=0.0, z=2.0),
            Node3D(id="W1T", x=0.1, y=3.0, z=2.0),
        ),
        members=(Member3D(id="W1", start_node_id="W1B", end_node_id="W1T"),),
    )

    model = build_global_model_from_parts([base, wall], node_reuse_tolerance=0.001)

    assert [node.id for node in model.nodes] == ["10001", "30001", "30002"]
    assert [(member.id, member.start_node_id, member.end_node_id) for member in model.members] == [
        ("30001", "30001", "30002")
    ]


def test_part_geometry_rejects_members_with_missing_nodes():
    with pytest.raises(ValueError, match="missing end node"):
        PartGeometry(
            part_id="bad",
            part_type="base",
            nodes=(Node3D(id="N1", x=0, y=0, z=0),),
            members=(Member3D(id="M1", start_node_id="N1", end_node_id="N2"),),
        )
