import csv
import json

from ehouse_model.domain import Member2D, Node2D
from ehouse_model.face_model import FaceModel, WarningRecord, write_face_model_json
from ehouse_model.global_model import build_global_model, build_global_outputs
from ehouse_model.global_stitching import StitchOptions
from ehouse_model.project_model import EHouseProject, ProjectDimensions, ProjectFaceSpec, write_project_json


def test_build_global_model_maps_face_nodes_to_3d(tmp_path):
    face_model_path = tmp_path / "base_face_model.json"
    write_face_model_json(
        FaceModel(
            source_dxf="base.dxf",
            nodes=(Node2D(id="N1", x=0, y=0), Node2D(id="N2", x=10, y=5)),
            members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
            centerline_candidates=(),
            member_sources={"M1": "C1"},
        ),
        face_model_path,
    )
    project = EHouseProject(
        name="Demo",
        dimensions=ProjectDimensions(length=100, height=20, width=30),
        faces=(
            ProjectFaceSpec(
                id="base",
                plane_type="base",
                face_model_path=str(face_model_path),
                center_offset=2,
            ),
        ),
    )

    model = build_global_model(project, base_dir=tmp_path)

    assert [(node.id, node.x, node.y, node.z) for node in model.nodes] == [
        ("base.N1", 0.0, 2.0, 0.0),
        ("base.N2", 10.0, 2.0, 5.0),
    ]
    assert [(member.id, member.start_node_id, member.end_node_id) for member in model.members] == [
        ("base.M1", "base.N1", "base.N2")
    ]
    assert model.member_sources["base.M1"]["source_candidate_id"] == "C1"


def test_build_global_outputs_writes_intermediate_files(tmp_path):
    face_dir = tmp_path / "faces" / "right"
    face_model_path = face_dir / "face_model.json"
    write_face_model_json(
        FaceModel(
            source_dxf="right.dxf",
            nodes=(Node2D(id="N1", x=1, y=2), Node2D(id="N2", x=3, y=4)),
            members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
            centerline_candidates=(),
            warnings=(
                WarningRecord(
                    id="W1",
                    code="manual_review",
                    message="Needs manual review.",
                    entity_id="M1",
                ),
            ),
        ),
        face_model_path,
    )
    project_path = tmp_path / "project.json"
    write_project_json(
        EHouseProject(
            name="Demo",
            dimensions=ProjectDimensions(length=100, height=20, width=30),
            faces=(
                ProjectFaceSpec(
                    id="right",
                    plane_type="right_wall",
                    face_model_path="faces/right/face_model.json",
                    center_offset=3,
                ),
            ),
            path=project_path,
        ),
        project_path,
    )
    output_dir = tmp_path / "global"

    model = build_global_outputs(
        project_path,
        output_dir,
        stitch_options=StitchOptions(merge_tolerance=0, review_tolerance=0),
    )

    assert len(model.nodes) == 2
    assert (output_dir / "global_model.json").exists()
    assert (output_dir / "nodes.csv").exists()
    assert (output_dir / "members.csv").exists()
    assert (output_dir / "warnings.csv").exists()
    assert (output_dir / "geometry.std").exists()

    global_json = json.loads((output_dir / "global_model.json").read_text(encoding="utf-8"))
    assert global_json["nodes"][0]["id"] == "right.N1"
    assert global_json["nodes"][0]["z"] == 27.0

    with (output_dir / "nodes.csv").open("r", encoding="utf-8", newline="") as file:
        node_rows = list(csv.DictReader(file))
    assert node_rows == [
        {"id": "right.N1", "x": "1", "y": "2", "z": "27"},
        {"id": "right.N2", "x": "3", "y": "4", "z": "27"},
    ]

    with (output_dir / "warnings.csv").open("r", encoding="utf-8", newline="") as file:
        warning_rows = list(csv.DictReader(file))
    assert warning_rows == [
        {
            "id": "W1",
            "level": "warning",
            "code": "manual_review",
            "message": "Needs manual review.",
            "entity_id": "right.M1",
        }
    ]
