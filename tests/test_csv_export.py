import csv

from ehouse_model import Member3D, Node3D
from ehouse_model.exporters import export_members_csv, export_nodes_csv


def test_export_nodes_csv(tmp_path):
    output = tmp_path / "nodes.csv"

    export_nodes_csv(
        [
            Node3D(id="N1", x=0, y=1.25, z=2),
            Node3D(id="N2", x=10, y=0, z=-3.5),
        ],
        output,
    )

    with output.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    assert rows == [
        {"id": "N1", "x": "0", "y": "1.25", "z": "2"},
        {"id": "N2", "x": "10", "y": "0", "z": "-3.5"},
    ]


def test_export_members_csv(tmp_path):
    output = tmp_path / "members.csv"

    export_members_csv(
        [
            Member3D(id="M1", start_node_id="N1", end_node_id="N2"),
            Member3D(id="M2", start_node_id="N2", end_node_id="N3"),
        ],
        output,
    )

    with output.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    assert rows == [
        {"id": "M1", "start_node_id": "N1", "end_node_id": "N2"},
        {"id": "M2", "start_node_id": "N2", "end_node_id": "N3"},
    ]
