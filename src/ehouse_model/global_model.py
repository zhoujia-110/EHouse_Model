"""Build global 3D geometry from project.json and face_model.json files."""

from __future__ import annotations

import json
from pathlib import Path

from ehouse_model.domain import Member3D, Node2D
from ehouse_model.exporters import (
    export_members_csv,
    export_nodes_csv,
    export_staad_geometry,
    export_warnings_csv,
)
from ehouse_model.face_model import WarningRecord, load_face_model_json
from ehouse_model.global_model_types import GlobalModel
from ehouse_model.global_stitching import StitchOptions, stitch_global_model
from ehouse_model.mapping import map_2d_to_3d
from ehouse_model.project_model import EHouseProject, load_project_json


def build_global_model(project: EHouseProject, base_dir: str | Path | None = None) -> GlobalModel:
    project_dir = Path(base_dir) if base_dir is not None else _project_dir(project)
    nodes: list[Node3D] = []
    members: list[Member3D] = []
    node_sources: dict[str, dict[str, str]] = {}
    member_sources: dict[str, dict[str, str]] = {}
    warnings: list[WarningRecord] = []

    for face in project.faces:
        face_model_path = _resolve_project_path(project_dir, face.face_model_path)
        face_model = load_face_model_json(face_model_path)
        plane = face.to_plane_spec(project.dimensions)

        for node in face_model.nodes:
            global_node_id = _global_id(face.id, node.id)
            mapped = map_2d_to_3d(Node2D(id=global_node_id, x=node.x, y=node.y), plane)
            nodes.append(mapped)
            node_sources[global_node_id] = {
                "face_id": face.id,
                "local_node_id": node.id,
                "face_model_path": str(face_model_path),
            }

        for member in face_model.members:
            global_member_id = _global_id(face.id, member.id)
            members.append(
                Member3D(
                    id=global_member_id,
                    start_node_id=_global_id(face.id, member.start_node_id),
                    end_node_id=_global_id(face.id, member.end_node_id),
                )
            )
            member_sources[global_member_id] = {
                "face_id": face.id,
                "local_member_id": member.id,
                "source_candidate_id": str(face_model.member_sources.get(member.id, "")),
                "face_model_path": str(face_model_path),
            }

        for warning in face_model.warnings:
            warnings.append(
                WarningRecord(
                    id=_global_id(face.id, warning.id) if warning.id else "",
                    level=warning.level,
                    code=warning.code,
                    message=warning.message,
                    entity_id=_global_id(face.id, warning.entity_id) if warning.entity_id else face.id,
                )
            )

    return GlobalModel(
        project_name=project.name,
        nodes=tuple(nodes),
        members=tuple(members),
        node_sources=node_sources,
        member_sources=member_sources,
        warnings=tuple(warnings),
    )


def build_global_outputs(
    project_json_path: str | Path = "project.json",
    output_dir: str | Path = "output_global",
    stitch_options: StitchOptions | None = None,
) -> GlobalModel:
    project_path = Path(project_json_path)
    project = load_project_json(project_path)
    model = stitch_global_model(
        build_global_model(project, base_dir=project_path.parent),
        stitch_options,
    )
    output_path = Path(output_dir)
    write_global_model_json(model, output_path / "global_model.json")
    export_nodes_csv(model.nodes, output_path / "nodes.csv")
    export_members_csv(model.members, output_path / "members.csv")
    export_warnings_csv(model.warnings, output_path / "warnings.csv")
    export_staad_geometry(model, output_path / "geometry.std")
    return model


def write_global_model_json(model: GlobalModel, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(model.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _project_dir(project: EHouseProject) -> Path:
    if project.path is not None:
        return project.path.parent
    return Path.cwd()


def _resolve_project_path(project_dir: Path, path: str) -> Path:
    result = Path(path)
    if result.is_absolute():
        return result
    return project_dir / result


def _global_id(face_id: str, local_id: str | None) -> str:
    return f"{face_id}.{local_id}" if local_id else face_id
