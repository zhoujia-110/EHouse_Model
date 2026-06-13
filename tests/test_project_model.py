import json

import pytest

from ehouse_model.project_model import (
    EHouseProject,
    ProjectDimensions,
    ProjectFaceSpec,
    load_project_json,
)


def test_project_face_spec_maps_standard_planes_with_center_offsets():
    dimensions = ProjectDimensions(length=100.0, height=20.0, width=30.0)

    base = ProjectFaceSpec(
        id="base",
        plane_type="base",
        face_model_path="faces/base/face_model.json",
        center_offset=2.0,
    ).to_plane_spec(dimensions)
    right = ProjectFaceSpec(
        id="right",
        plane_type="right_wall",
        face_model_path="faces/right/face_model.json",
        center_offset=3.0,
    ).to_plane_spec(dimensions)
    front = ProjectFaceSpec(
        id="front",
        plane_type="front_wall",
        face_model_path="faces/front/face_model.json",
        center_offset=4.0,
    ).to_plane_spec(dimensions)

    assert base.origin == (0.0, 2.0, 0.0)
    assert base.local_x_axis == "X"
    assert base.local_y_axis == "Z"
    assert right.origin == (0.0, 0.0, 27.0)
    assert right.local_x_axis == "X"
    assert right.local_y_axis == "Y"
    assert front.origin == (4.0, 0.0, 0.0)
    assert front.local_x_axis == "Z"
    assert front.local_y_axis == "Y"


def test_load_project_json_reads_gui_internal_project(tmp_path):
    project_json = tmp_path / "project.json"
    project_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Demo",
                "dimensions": {"length": 100, "height": 20, "width": 30},
                "faces": [
                    {
                        "id": "base",
                        "plane_type": "底座",
                        "face_model_path": "faces/base/face_model.json",
                        "center_offset": 0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    project = load_project_json(project_json)

    assert project == EHouseProject(
        name="Demo",
        dimensions=ProjectDimensions(length=100, height=20, width=30),
        faces=(
            ProjectFaceSpec(
                id="base",
                plane_type="base",
                face_model_path="faces/base/face_model.json",
                center_offset=0,
            ),
        ),
        path=project_json,
    )


def test_internal_section_requires_explicit_mapping():
    face = ProjectFaceSpec(
        id="section",
        plane_type="internal_section",
        face_model_path="faces/section/face_model.json",
    )

    with pytest.raises(ValueError, match="internal_section"):
        face.to_plane_spec(ProjectDimensions(length=100, height=20, width=30))
