"""Assemble confirmed part geometries into the current global model."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.exporters import (
    export_members_csv,
    export_nodes_csv,
    export_staad_geometry,
    export_warnings_csv,
)
from ehouse_model.face_model import WarningRecord
from ehouse_model.global_model import write_global_model_json
from ehouse_model.global_model_types import GlobalModel
from ehouse_model.global_stitching import StitchOptions
from ehouse_model.part_geometry import PartGeometry, load_part_geometry_json

PART_NUMBER_BASES = {
    "base": 10000,
    "roof": 20000,
    "left_wall": 30000,
    "right_wall": 40000,
    "front_wall": 50000,
    "back_wall": 60000,
    "side_wall": 30000,
    "internal": 70000,
}


def load_part_geometries(paths: Iterable[str | Path]) -> tuple[PartGeometry, ...]:
    return tuple(load_part_geometry_json(path) for path in paths)


def build_global_model_from_parts(
    parts: Iterable[PartGeometry],
    *,
    project_name: str = "E-House Project",
    node_reuse_tolerance: float = 0.001,
) -> GlobalModel:
    """Combine confirmed parts directly using fixed numeric id ranges.

    The confirmed part geometries already live in global coordinates. For the
    base/roof workflow no node snapping or member de-duplication is needed:
    base coordinates stay at ``Y=0`` and roof coordinates stay at the selected
    ``Y`` plane. IDs are reassigned only to keep STAAD node/member namespaces
    distinct across parts.
    """
    nodes: list[Node3D] = []
    members: list[Member3D] = []
    node_sources: dict[str, dict[str, str]] = {}
    member_sources: dict[str, dict[str, str]] = {}
    warnings: list[WarningRecord] = []

    ordered_parts = _ordered_parts(tuple(parts))
    for fallback_index, part in enumerate(ordered_parts, start=1):
        number_base = _part_number_base(part, fallback_index)
        _ensure_part_fits_number_range(part, number_base)
        node_id_map: dict[str, str] = {}
        node_reuse_map: dict[str, dict[str, str]] = {}
        member_id_map = {
            member.id: str(number_base + index)
            for index, member in enumerate(part.members, start=1)
        }

        created_node_index = 0
        for local_index, node in enumerate(part.nodes, start=1):
            reuse_match, candidate_count = _find_reusable_node(
                nodes,
                node,
                tolerance=node_reuse_tolerance,
                enabled=_should_reuse_existing_nodes(part),
            )
            if reuse_match is not None:
                node_id_map[node.id] = reuse_match.id
                distance = _distance_3d(node, reuse_match)
                node_reuse_map[node.id] = {
                    "reused_node_id": reuse_match.id,
                    "reuse_distance": _format_float(distance),
                }
                if candidate_count > 1:
                    warnings.append(
                        WarningRecord(
                            level="info",
                            code="multiple_reuse_candidates",
                            message="A side-wall node matched multiple existing nodes; the nearest node was reused.",
                            entity_id=node.id,
                        )
                    )
                continue

            created_node_index += 1
            global_node_id = str(number_base + created_node_index)
            node_id_map[node.id] = global_node_id
            nodes.append(Node3D(id=global_node_id, x=node.x, y=node.y, z=node.z))
            node_sources[global_node_id] = {
                "part_id": part.part_id,
                "part_type": part.part_type,
                "local_node_id": node.id,
                "part_local_index": str(local_index),
                "number_base": str(number_base),
                "source_kind": part.source.kind,
                "source_path": part.source.path or "",
            }

        for local_index, member in enumerate(part.members, start=1):
            global_member_id = member_id_map[member.id]
            start_node_id = node_id_map[member.start_node_id]
            end_node_id = node_id_map[member.end_node_id]
            if start_node_id == end_node_id:
                warnings.append(
                    WarningRecord(
                        level="warning",
                        code="zero_length_member_removed",
                        message="A side-wall member mapped both ends to the same reused node and was removed.",
                        entity_id=member.id,
                    )
                )
                continue
            members.append(
                Member3D(
                    id=global_member_id,
                    start_node_id=start_node_id,
                    end_node_id=end_node_id,
                )
            )
            source = {
                "part_id": part.part_id,
                "part_type": part.part_type,
                "local_member_id": member.id,
                "part_local_index": str(local_index),
                "number_base": str(number_base),
                "source_kind": part.source.kind,
                "source_path": part.source.path or "",
            }
            if member.start_node_id in node_reuse_map:
                source["start_reused_node_id"] = node_reuse_map[member.start_node_id]["reused_node_id"]
                source["start_reuse_distance"] = node_reuse_map[member.start_node_id]["reuse_distance"]
            if member.end_node_id in node_reuse_map:
                source["end_reused_node_id"] = node_reuse_map[member.end_node_id]["reused_node_id"]
                source["end_reuse_distance"] = node_reuse_map[member.end_node_id]["reuse_distance"]
            member_sources[global_member_id] = source

        for warning in part.warnings:
            warnings.append(
                WarningRecord(
                    id=_global_warning_id(part.part_id, warning.id) if warning.id else "",
                    level=warning.level,
                    code=warning.code,
                    message=warning.message,
                    entity_id=_global_warning_id(part.part_id, warning.entity_id)
                    if warning.entity_id
                    else part.part_id,
                )
            )

    return GlobalModel(
        project_name=project_name,
        nodes=tuple(nodes),
        members=tuple(members),
        node_sources=node_sources,
        member_sources=member_sources,
        warnings=tuple(warnings),
    )


def stitch_part_geometries(
    parts: Iterable[PartGeometry],
    *,
    project_name: str = "E-House Project",
    stitch_options: StitchOptions | None = None,
    node_reuse_tolerance: float = 0.001,
) -> GlobalModel:
    """Build the current global model from any confirmed parts available.

    ``stitch_options`` is accepted for API compatibility with the future wall
    stitching workflow, but base and roof parts are intentionally assembled by
    direct concatenation.
    """
    return build_global_model_from_parts(
        parts,
        project_name=project_name,
        node_reuse_tolerance=node_reuse_tolerance,
    )


def build_part_assembly_outputs(
    parts: Iterable[PartGeometry],
    output_dir: str | Path,
    *,
    project_name: str = "E-House Project",
    stitch_options: StitchOptions | None = None,
    node_reuse_tolerance: float = 0.001,
) -> GlobalModel:
    """Write the current global model outputs from confirmed parts."""
    model = stitch_part_geometries(
        parts,
        project_name=project_name,
        stitch_options=stitch_options,
        node_reuse_tolerance=node_reuse_tolerance,
    )
    output_path = Path(output_dir)
    write_global_model_json(model, output_path / "global_model.json")
    export_nodes_csv(model.nodes, output_path / "nodes.csv")
    export_members_csv(model.members, output_path / "members.csv")
    export_warnings_csv(model.warnings, output_path / "warnings.csv")
    export_staad_geometry(model, output_path / "geometry.std")
    return model


def _part_number_base(part: PartGeometry, fallback_index: int) -> int:
    if part.part_id in PART_NUMBER_BASES:
        return PART_NUMBER_BASES[part.part_id]
    if part.part_type in PART_NUMBER_BASES:
        return PART_NUMBER_BASES[part.part_type]
    return 80000 + fallback_index * 10000


def _ordered_parts(parts: tuple[PartGeometry, ...]) -> tuple[PartGeometry, ...]:
    priority = {
        "base": 0,
        "roof": 1,
        "side_wall": 2,
    }
    return tuple(
        part
        for _index, part in sorted(
            enumerate(parts),
            key=lambda item: (priority.get(item[1].part_id, priority.get(item[1].part_type, 10)), item[0]),
        )
    )


def _should_reuse_existing_nodes(part: PartGeometry) -> bool:
    return part.part_id == "side_wall" or part.part_type == "side_wall"


def _find_reusable_node(
    existing_nodes: list[Node3D],
    node: Node3D,
    *,
    tolerance: float,
    enabled: bool,
) -> tuple[Node3D | None, int]:
    if not enabled or tolerance < 0:
        return None, 0
    candidates = [
        (existing, _distance_3d(node, existing))
        for existing in existing_nodes
        if _distance_3d(node, existing) <= tolerance
    ]
    if not candidates:
        return None, 0
    candidates.sort(key=lambda item: item[1])
    return candidates[0][0], len(candidates)


def _distance_3d(left: Node3D, right: Node3D) -> float:
    return math.sqrt(
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )


def _format_float(value: float) -> str:
    text = f"{value:.12g}"
    return "0" if text in ("", "-0") else text


def _ensure_part_fits_number_range(part: PartGeometry, number_base: int) -> None:
    if len(part.nodes) > 9999 or len(part.members) > 9999:
        raise ValueError(
            f"part {part.part_id!r} exceeds the 9999 item capacity of number range "
            f"{number_base + 1}-{number_base + 9999}"
        )


def _global_warning_id(part_id: str, local_id: str | None) -> str:
    return f"{part_id}.{local_id}" if local_id else part_id
