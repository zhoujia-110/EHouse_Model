import pytest

from ehouse_model import load_project


def test_load_project_reads_planes_and_stitch_rules(tmp_path):
    project_yaml = tmp_path / "project.yaml"
    project_yaml.write_text(
        """
planes:
  front:
    dxf: faces/front.dxf
    origin: [0, 0, 0]
    local_x_axis: X
    local_y_axis: Y
  right:
    dxf_path: faces/right.dxf
    origin: [12, 0, 0]
    local_x_axis: Z
    local_y_axis: Y
stitch_rules:
  - source_plane: front
    target_plane: right
    source_edge: right
    target_edge: left
    tolerance: 0.01
""",
        encoding="utf-8",
    )

    project = load_project(project_yaml)

    assert set(project.planes) == {"front", "right"}
    assert project.planes["front"].dxf_path == "faces/front.dxf"
    assert project.planes["right"].origin == (12.0, 0.0, 0.0)
    assert project.planes["right"].local_x_axis == "Z"
    assert len(project.stitch_rules) == 1
    assert project.stitch_rules[0].source_plane == "front"
    assert project.stitch_rules[0].target_edge == "left"
    assert project.stitch_rules[0].tolerance == pytest.approx(0.01)


def test_load_project_rejects_stitch_rule_with_unknown_plane(tmp_path):
    project_yaml = tmp_path / "project.yaml"
    project_yaml.write_text(
        """
planes:
  front:
    origin: [0, 0, 0]
    local_x_axis: X
    local_y_axis: Y
stitch_rules:
  - source_plane: front
    target_plane: missing
    source_edge: right
    target_edge: left
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown plane"):
        load_project(project_yaml)
