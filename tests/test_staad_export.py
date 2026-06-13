from ehouse_model.domain import Member3D, Node3D
from ehouse_model.exporters import export_staad_geometry
from ehouse_model.global_model_types import GlobalModel


def test_export_staad_geometry_writes_minimal_std(tmp_path):
    output = tmp_path / "geometry.std"
    model = GlobalModel(
        project_name="Demo",
        nodes=(
            Node3D(id="N1", x=0, y=0, z=0),
            Node3D(id="N2", x=10.5, y=0, z=2),
        ),
        members=(Member3D(id="M1", start_node_id="N1", end_node_id="N2"),),
    )

    export_staad_geometry(model, output)

    assert output.read_text(encoding="utf-8") == (
        "STAAD SPACE\n"
        "UNIT METER KN\n"
        "JOINT COORDINATES\n"
        "1 0 0 0;\n"
        "2 10.5 0 2;\n"
        "MEMBER INCIDENCES\n"
        "1 1 2;\n"
        "FINISH\n"
    )
