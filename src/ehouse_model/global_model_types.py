"""Shared global model data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.face_model import WarningRecord


@dataclass(frozen=True, slots=True)
class GlobalModel:
    project_name: str
    nodes: tuple[Node3D, ...]
    members: tuple[Member3D, ...]
    node_sources: Mapping[str, dict[str, str]] = field(default_factory=dict)
    member_sources: Mapping[str, dict[str, str]] = field(default_factory=dict)
    warnings: tuple[WarningRecord, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "project_name": self.project_name,
            "nodes": [
                {
                    "id": node.id,
                    "x": _clean_float(node.x),
                    "y": _clean_float(node.y),
                    "z": _clean_float(node.z),
                    "source": self.node_sources.get(node.id, {}),
                }
                for node in self.nodes
            ],
            "members": [
                {
                    "id": member.id,
                    "start_node_id": member.start_node_id,
                    "end_node_id": member.end_node_id,
                    "source": self.member_sources.get(member.id, {}),
                }
                for member in self.members
            ],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def _clean_float(value: float) -> float:
    return float(f"{value:.12g}")
