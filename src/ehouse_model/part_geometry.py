"""Confirmed per-part global geometry used by the project wizard."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.face_model import WarningRecord


@dataclass(frozen=True, slots=True)
class PartGeometrySource:
    """Origin metadata for a confirmed part geometry."""

    kind: str
    path: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_text(self.kind, "kind"))
        if self.path is not None:
            object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "description", str(self.description))

    def to_dict(self) -> dict[str, str]:
        data = {"kind": self.kind}
        if self.path:
            data["path"] = self.path
        if self.description:
            data["description"] = self.description
        return data


@dataclass(frozen=True, slots=True)
class PartGeometry:
    """Global geometry for one confirmed model part.

    This is the handoff format between part pages and the global stitching page.
    It may come from DXF recognition or from a user-modified STD file.
    """

    part_id: str
    part_type: str
    nodes: tuple[Node3D, ...]
    members: tuple[Member3D, ...]
    source: PartGeometrySource = field(
        default_factory=lambda: PartGeometrySource(kind="generated")
    )
    coordinate_space: str = "global"
    unit: str = "meter"
    warnings: tuple[WarningRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "part_id", _non_empty_text(self.part_id, "part_id"))
        object.__setattr__(self, "part_type", _non_empty_text(self.part_type, "part_type"))
        object.__setattr__(
            self,
            "coordinate_space",
            _non_empty_text(self.coordinate_space, "coordinate_space"),
        )
        object.__setattr__(self, "unit", _non_empty_text(self.unit, "unit"))

        if self.coordinate_space != "global":
            raise ValueError("part geometry must use global coordinates")
        if self.unit != "meter":
            raise ValueError("part geometry currently supports only meter units")

        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("part geometry node ids must be unique")

        member_ids = [member.id for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("part geometry member ids must be unique")

        node_id_set = set(node_ids)
        for member in self.members:
            if member.start_node_id not in node_id_set:
                raise ValueError(f"member {member.id!r} references missing start node")
            if member.end_node_id not in node_id_set:
                raise ValueError(f"member {member.id!r} references missing end node")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "part_id": self.part_id,
            "part_type": self.part_type,
            "source": self.source.to_dict(),
            "coordinate_space": self.coordinate_space,
            "unit": self.unit,
            "nodes": [
                {
                    "id": node.id,
                    "x": _clean_float(node.x),
                    "y": _clean_float(node.y),
                    "z": _clean_float(node.z),
                }
                for node in self.nodes
            ],
            "members": [
                {
                    "id": member.id,
                    "start_node_id": member.start_node_id,
                    "end_node_id": member.end_node_id,
                }
                for member in self.members
            ],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def write_part_geometry_json(model: PartGeometry, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(model.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_part_geometry_json(path: str | Path) -> PartGeometry:
    input_path = Path(path)
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("part_geometry.json must contain a mapping")

    source = _parse_source(raw.get("source", {}))
    nodes = tuple(
        Node3D(id=value["id"], x=value["x"], y=value["y"], z=value["z"])
        for value in _require_list(raw, "nodes")
    )
    members = tuple(
        Member3D(
            id=value["id"],
            start_node_id=value["start_node_id"],
            end_node_id=value["end_node_id"],
        )
        for value in _require_list(raw, "members")
    )
    warnings = tuple(
        WarningRecord(
            id=value.get("id", ""),
            level=value.get("level", "warning"),
            code=value["code"],
            message=value["message"],
            entity_id=value.get("entity_id"),
        )
        for value in raw.get("warnings", [])
    )

    return PartGeometry(
        part_id=raw.get("part_id"),
        part_type=raw.get("part_type"),
        source=source,
        coordinate_space=str(raw.get("coordinate_space", "global")),
        unit=str(raw.get("unit", "meter")),
        nodes=nodes,
        members=members,
        warnings=warnings,
    )


def part_geometry_from_mapping(raw: Mapping[str, object]) -> PartGeometry:
    """Build a part geometry from an already-decoded JSON mapping."""
    source = _parse_source(raw.get("source", {}))
    nodes = tuple(
        Node3D(id=value["id"], x=value["x"], y=value["y"], z=value["z"])
        for value in _require_list(raw, "nodes")
    )
    members = tuple(
        Member3D(
            id=value["id"],
            start_node_id=value["start_node_id"],
            end_node_id=value["end_node_id"],
        )
        for value in _require_list(raw, "members")
    )
    return PartGeometry(
        part_id=raw.get("part_id"),
        part_type=raw.get("part_type"),
        source=source,
        coordinate_space=str(raw.get("coordinate_space", "global")),
        unit=str(raw.get("unit", "meter")),
        nodes=nodes,
        members=members,
    )


def _parse_source(raw: object) -> PartGeometrySource:
    if not isinstance(raw, Mapping):
        return PartGeometrySource(kind="unknown")
    return PartGeometrySource(
        kind=str(raw.get("kind", "unknown")),
        path=raw.get("path"),
        description=str(raw.get("description", "")),
    )


def _require_list(raw: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"part_geometry.json must define {key} as a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"part_geometry.json {key} entries must be mappings")
    return value


def _non_empty_text(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text or text == "None":
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _clean_float(value: float) -> float:
    return float(f"{value:.12g}")
