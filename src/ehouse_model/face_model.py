"""Single-face intermediate model structures."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ehouse_model.domain import Member2D, Node2D

Point2D = tuple[float, float]


@dataclass(frozen=True, slots=True)
class WarningRecord:
    code: str
    message: str
    id: str = ""
    level: str = "warning"
    entity_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _coerce_text(self.code, "code"))
        object.__setattr__(self, "message", _coerce_text(self.message, "message"))
        object.__setattr__(self, "level", _coerce_text(self.level, "level"))
        object.__setattr__(self, "id", str(self.id).strip())
        if self.entity_id is not None:
            object.__setattr__(self, "entity_id", str(self.entity_id).strip() or None)

    def with_id(self, warning_id: str) -> "WarningRecord":
        return WarningRecord(
            id=warning_id,
            level=self.level,
            code=self.code,
            message=self.message,
            entity_id=self.entity_id,
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "entity_id": self.entity_id,
        }


@dataclass(frozen=True, slots=True)
class CenterlineCandidate:
    id: str
    start: Point2D
    end: Point2D
    source_segment_ids: tuple[str, str]
    width: float
    overlap: float
    kind: str = "outline_member"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _coerce_text(self.id, "id"))
        object.__setattr__(self, "start", _coerce_point(self.start, "start"))
        object.__setattr__(self, "end", _coerce_point(self.end, "end"))
        object.__setattr__(
            self,
            "source_segment_ids",
            tuple(_coerce_text(value, "source_segment_id") for value in self.source_segment_ids),
        )
        if len(self.source_segment_ids) != 2:
            raise ValueError("source_segment_ids must contain exactly two ids")
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "overlap", float(self.overlap))
        object.__setattr__(self, "kind", _coerce_text(self.kind, "kind"))
        object.__setattr__(self, "confidence", float(self.confidence))


@dataclass(frozen=True, slots=True)
class FaceModel:
    source_dxf: str
    nodes: tuple[Node2D, ...]
    members: tuple[Member2D, ...]
    centerline_candidates: tuple[CenterlineCandidate, ...]
    member_sources: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[WarningRecord, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "source_dxf": self.source_dxf,
            "nodes": [
                {"id": node.id, "x": _clean_float(node.x), "y": _clean_float(node.y)}
                for node in self.nodes
            ],
            "members": [
                _member_to_dict(member, self.member_sources)
                for member in self.members
            ],
            "centerline_candidates": [
                {
                    "id": candidate.id,
                    "kind": candidate.kind,
                    "start": [_clean_float(candidate.start[0]), _clean_float(candidate.start[1])],
                    "end": [_clean_float(candidate.end[0]), _clean_float(candidate.end[1])],
                    "source_segment_ids": list(candidate.source_segment_ids),
                    "width": _clean_float(candidate.width),
                    "overlap": _clean_float(candidate.overlap),
                    "confidence": _clean_float(candidate.confidence),
                }
                for candidate in self.centerline_candidates
            ],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def write_face_model_json(model: FaceModel, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(model.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_face_model_json(path: str | Path) -> FaceModel:
    input_path = Path(path)
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("face_model.json must contain a mapping")

    nodes = tuple(
        Node2D(id=value["id"], x=value["x"], y=value["y"])
        for value in _require_list(raw, "nodes")
    )
    members = tuple(
        Member2D(
            id=value["id"],
            start_node_id=value["start_node_id"],
            end_node_id=value["end_node_id"],
        )
        for value in _require_list(raw, "members")
    )
    member_sources = {
        str(value["id"]): str(value["source_candidate_id"])
        for value in _require_list(raw, "members")
        if value.get("source_candidate_id")
    }
    candidates = tuple(
        CenterlineCandidate(
            id=value["id"],
            kind=value.get("kind", "outline_member"),
            start=value["start"],
            end=value["end"],
            source_segment_ids=tuple(value["source_segment_ids"]),
            width=value["width"],
            overlap=value["overlap"],
            confidence=value.get("confidence", 1.0),
        )
        for value in raw.get("centerline_candidates", [])
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

    return FaceModel(
        source_dxf=str(raw.get("source_dxf", "")),
        nodes=nodes,
        members=members,
        centerline_candidates=candidates,
        member_sources=member_sources,
        warnings=warnings,
    )


def _member_to_dict(member: Member2D, member_sources: Mapping[str, str]) -> dict[str, str]:
    data = {
        "id": member.id,
        "start_node_id": member.start_node_id,
        "end_node_id": member.end_node_id,
    }
    source_candidate_id = member_sources.get(member.id)
    if source_candidate_id:
        data["source_candidate_id"] = source_candidate_id
    return data


def _coerce_text(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


def _coerce_point(value: object, field_name: str) -> Point2D:
    try:
        x, y = value  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain exactly two numbers") from exc
    return (float(x), float(y))


def _clean_float(value: float) -> float:
    return float(f"{value:.12g}")


def _require_list(raw: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"face_model.json must define {key} as a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"face_model.json {key} entries must be mappings")
    return value
