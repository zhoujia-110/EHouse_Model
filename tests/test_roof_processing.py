import ezdxf
import pytest

from ehouse_model.domain import Member2D, Node2D
from ehouse_model.face_model import FaceModel
from ehouse_model.part_builders import build_roof_part_from_face_model
from ehouse_model.roof_processing import (
    RoofBoundaryOffsets,
    export_roof_staad,
    extract_roof_face,
    face_model_to_roof_global_model,
)


def test_roof_global_model_uses_user_selected_y_plane():
    model = FaceModel(
        source_dxf="roof.dxf",
        nodes=(Node2D(id="N1", x=1.25, y=2.5),),
        members=(),
        centerline_candidates=(),
    )

    global_model = face_model_to_roof_global_model(model, y_plane=3.75)

    assert [(node.id, node.x, node.y, node.z) for node in global_model.nodes] == [
        ("N1", 0.0, 3.75, 0.0)
    ]


def test_roof_boundary_offsets_rebase_only_roof_nodes():
    model = FaceModel(
        source_dxf="roof.dxf",
        nodes=(
            Node2D(id="LT", x=10.0, y=20.0),
            Node2D(id="RT", x=110.0, y=20.0),
            Node2D(id="LB", x=10.0, y=70.0),
            Node2D(id="RB", x=110.0, y=70.0),
            Node2D(id="MID", x=60.0, y=45.0),
        ),
        members=(),
        centerline_candidates=(),
    )

    global_model = face_model_to_roof_global_model(
        model,
        y_plane=4.0,
        boundary_offsets=RoofBoundaryOffsets(
            left_dx=-2.0,
            right_dx=3.0,
            top_dz=5.0,
            bottom_dz=-1.0,
        ),
    )

    assert [(node.id, node.x, node.y, node.z) for node in global_model.nodes] == [
        ("LT", 0.0, 4.0, 0.0),
        ("RT", 105.0, 4.0, 0.0),
        ("LB", 0.0, 4.0, 44.0),
        ("RB", 105.0, 4.0, 44.0),
        ("MID", 52.0, 4.0, 20.0),
    ]


def test_extract_roof_face_reuses_base_algorithm_but_places_nodes_at_y(tmp_path):
    dxf_path = tmp_path / "roof_clean.dxf"
    _write_roof_rectangles(dxf_path)

    result = extract_roof_face(
        dxf_path,
        y_plane=4.2,
        face_model_path=tmp_path / "roof_face_model.json",
        overlay_path=tmp_path / "roof_overlay.dxf",
        warnings_csv_path=tmp_path / "roof_warnings.csv",
    )

    assert result.y_plane == pytest.approx(4.2)
    assert result.face_model.nodes
    assert result.global_model.nodes
    assert {node.y for node in result.global_model.nodes} == {4.2}
    assert (tmp_path / "roof_face_model.json").exists()
    assert (tmp_path / "roof_overlay.dxf").exists()
    assert (tmp_path / "roof_warnings.csv").exists()


def test_export_roof_staad_writes_selected_y_coordinate(tmp_path):
    output = tmp_path / "roof.std"
    model = FaceModel(
        source_dxf="roof.dxf",
        nodes=(Node2D(id="N1", x=0, y=0), Node2D(id="N2", x=1.5, y=2.5)),
        members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
        centerline_candidates=(),
    )

    export_roof_staad(model, output, y_plane=3.6)

    text = output.read_text(encoding="utf-8")
    assert "UNIT METER KN" in text
    assert "2 1.5 3.6 2.5;" in text


def test_export_roof_staad_applies_boundary_offsets(tmp_path):
    output = tmp_path / "roof.std"
    model = FaceModel(
        source_dxf="roof.dxf",
        nodes=(
            Node2D(id="N1", x=10, y=20),
            Node2D(id="N2", x=30, y=40),
        ),
        members=(Member2D(id="M1", start_node_id="N1", end_node_id="N2"),),
        centerline_candidates=(),
    )

    export_roof_staad(
        model,
        output,
        y_plane=3.6,
        boundary_offsets=RoofBoundaryOffsets(left_dx=-1.0, right_dx=2.0, top_dz=4.0, bottom_dz=-3.0),
    )

    assert output.read_text(encoding="utf-8") == (
        "STAAD SPACE\n"
        "UNIT METER KN\n"
        "JOINT COORDINATES\n"
        "1 0 3.6 0;\n"
        "2 23 3.6 13;\n"
        "MEMBER INCIDENCES\n"
        "1 1 2;\n"
        "FINISH\n"
    )


def test_build_roof_part_accepts_explicit_y_plane():
    model = FaceModel(
        source_dxf="roof.dxf",
        nodes=(Node2D(id="N1", x=0.5, y=0.75),),
        members=(),
        centerline_candidates=(),
    )

    part = build_roof_part_from_face_model(model, y_plane=2.9)

    assert part.part_type == "roof"
    assert [(node.x, node.y, node.z) for node in part.nodes] == [(0.0, 2.9, 0.0)]
    assert "Y=2.9" in part.source.description


def _write_roof_rectangles(path):
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (1000, 0))
    modelspace.add_line((0, 100), (1000, 100))
    modelspace.add_line((0, 0), (0, 100))
    modelspace.add_line((1000, 0), (1000, 100))
    modelspace.add_line((400, -300), (400, 400))
    modelspace.add_line((500, -300), (500, 400))
    doc.saveas(path)
