import json

from ehouse_model.project_model import (
    EHouseProject,
    ProjectDimensions,
    ProjectPartSpec,
    load_project_json,
)


def test_load_project_json_reads_wizard_parts(tmp_path):
    project_json = tmp_path / "project.json"
    project_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Wizard",
                "dimensions": {"length": 12, "height": 3, "width": 2.4},
                "parts": [
                    {
                        "id": "base",
                        "part_type": "底座",
                        "status": "confirmed",
                        "face_model_path": "models/base/face_model.json",
                        "part_geometry_path": "models/base/part_geometry.json",
                        "active_source": "generated_from_dxf",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    project = load_project_json(project_json)

    assert project == EHouseProject(
        name="Wizard",
        dimensions=ProjectDimensions(length=12, height=3, width=2.4),
        parts=(
            ProjectPartSpec(
                id="base",
                part_type="base",
                status="confirmed",
                face_model_path="models/base/face_model.json",
                part_geometry_path="models/base/part_geometry.json",
                active_source="generated_from_dxf",
            ),
        ),
        path=project_json,
    )


def test_project_part_spec_serializes_optional_paths():
    part = ProjectPartSpec(
        id="roof",
        part_type="屋盖",
        status="confirmed",
        clean_dxf_path="drawings/roof_clean.dxf",
        modified_std_path="models/roof/roof_modified.std",
        active_source="imported_modified_std",
    )

    assert part.to_dict() == {
        "id": "roof",
        "part_type": "roof",
        "status": "confirmed",
        "active_source": "imported_modified_std",
        "clean_dxf_path": "drawings/roof_clean.dxf",
        "modified_std_path": "models/roof/roof_modified.std",
    }
