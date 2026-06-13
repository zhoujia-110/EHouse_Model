"""Internal project.json model used by the future GUI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ehouse_model.domain import PlaneSpec

_PLANE_ALIASES = {
    "base": "base",
    "bottom": "base",
    "底座": "base",
    "roof": "roof",
    "top": "roof",
    "顶盖": "roof",
    "left": "left_wall",
    "left_wall": "left_wall",
    "左侧墙": "left_wall",
    "right": "right_wall",
    "right_wall": "right_wall",
    "右侧墙": "right_wall",
    "front": "front_wall",
    "front_wall": "front_wall",
    "前端墙": "front_wall",
    "back": "back_wall",
    "rear": "back_wall",
    "back_wall": "back_wall",
    "后端墙": "back_wall",
    "internal": "internal_section",
    "internal_section": "internal_section",
    "内部剖面": "internal_section",
}


@dataclass(frozen=True, slots=True)
class ProjectDimensions:
    length: float
    height: float
    width: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "length", _positive_float(self.length, "length"))
        object.__setattr__(self, "height", _positive_float(self.height, "height"))
        object.__setattr__(self, "width", _positive_float(self.width, "width"))

    def to_dict(self) -> dict[str, float]:
        return {"length": self.length, "height": self.height, "width": self.width}


@dataclass(frozen=True, slots=True)
class ProjectFaceSpec:
    id: str
    plane_type: str
    face_model_path: str
    center_offset: float = 0.0
    dxf_path: str | None = None
    origin: tuple[float, float, float] | None = None
    local_u_axis: str | None = None
    local_v_axis: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _non_empty_text(self.id, "id"))
        object.__setattr__(self, "plane_type", _canonical_plane_type(self.plane_type))
        object.__setattr__(self, "face_model_path", _non_empty_text(self.face_model_path, "face_model_path"))
        object.__setattr__(self, "center_offset", float(self.center_offset))
        if self.center_offset < 0:
            raise ValueError("center_offset cannot be negative")
        if self.dxf_path is not None:
            object.__setattr__(self, "dxf_path", str(self.dxf_path))
        if self.origin is not None:
            object.__setattr__(self, "origin", _float_tuple(self.origin, 3, "origin"))

    def to_plane_spec(self, dimensions: ProjectDimensions) -> PlaneSpec:
        if self.plane_type == "internal_section":
            if self.origin is None or self.local_u_axis is None or self.local_v_axis is None:
                raise ValueError("internal_section faces require origin, local_u_axis, and local_v_axis")
            return PlaneSpec(
                name=self.id,
                origin=self.origin,
                local_x_axis=self.local_u_axis,
                local_y_axis=self.local_v_axis,
                dxf_path=self.dxf_path,
            )

        origin, local_u_axis, local_v_axis = _default_plane_mapping(
            self.plane_type,
            dimensions,
            self.center_offset,
        )
        if self.origin is not None:
            origin = self.origin
        if self.local_u_axis is not None:
            local_u_axis = self.local_u_axis
        if self.local_v_axis is not None:
            local_v_axis = self.local_v_axis

        return PlaneSpec(
            name=self.id,
            origin=origin,
            local_x_axis=local_u_axis,
            local_y_axis=local_v_axis,
            dxf_path=self.dxf_path,
        )

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "id": self.id,
            "plane_type": self.plane_type,
            "face_model_path": self.face_model_path,
            "center_offset": self.center_offset,
        }
        if self.dxf_path is not None:
            data["dxf_path"] = self.dxf_path
        if self.origin is not None:
            data["origin"] = list(self.origin)
        if self.local_u_axis is not None:
            data["local_u_axis"] = self.local_u_axis
        if self.local_v_axis is not None:
            data["local_v_axis"] = self.local_v_axis
        return data


@dataclass(frozen=True, slots=True)
class EHouseProject:
    name: str
    dimensions: ProjectDimensions
    faces: tuple[ProjectFaceSpec, ...]
    path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty_text(self.name, "name"))
        if not self.faces:
            raise ValueError("project must contain at least one face")
        face_ids = [face.id for face in self.faces]
        if len(face_ids) != len(set(face_ids)):
            raise ValueError("project face ids must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "name": self.name,
            "dimensions": self.dimensions.to_dict(),
            "faces": [face.to_dict() for face in self.faces],
        }


def load_project_json(path: str | Path = "project.json") -> EHouseProject:
    project_path = Path(path)
    raw = json.loads(project_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("project.json must contain a mapping")

    dimensions = _parse_dimensions(raw.get("dimensions"))
    faces = tuple(_parse_face(value, index) for index, value in enumerate(_require_list(raw, "faces")))
    return EHouseProject(
        name=str(raw.get("name", "E-House Project")),
        dimensions=dimensions,
        faces=faces,
        path=project_path,
    )


def write_project_json(project: EHouseProject, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _parse_dimensions(raw: Any) -> ProjectDimensions:
    if not isinstance(raw, dict):
        raise ValueError("project.json must define dimensions")
    return ProjectDimensions(
        length=raw.get("length"),
        height=raw.get("height"),
        width=raw.get("width"),
    )


def _parse_face(raw: dict[str, Any], index: int) -> ProjectFaceSpec:
    try:
        return ProjectFaceSpec(
            id=raw.get("id"),
            plane_type=raw.get("plane_type"),
            face_model_path=raw.get("face_model_path"),
            center_offset=raw.get("center_offset", raw.get("center_plane_offset", 0.0)),
            dxf_path=raw.get("dxf_path"),
            origin=raw.get("origin"),
            local_u_axis=raw.get("local_u_axis"),
            local_v_axis=raw.get("local_v_axis"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid faces[{index}]: {exc}") from exc


def _default_plane_mapping(
    plane_type: str,
    dimensions: ProjectDimensions,
    center_offset: float,
) -> tuple[tuple[float, float, float], str, str]:
    if plane_type == "base":
        return (0.0, center_offset, 0.0), "X", "Z"
    if plane_type == "roof":
        return (0.0, dimensions.height - center_offset, 0.0), "X", "Z"
    if plane_type == "left_wall":
        return (0.0, 0.0, center_offset), "X", "Y"
    if plane_type == "right_wall":
        return (0.0, 0.0, dimensions.width - center_offset), "X", "Y"
    if plane_type == "front_wall":
        return (center_offset, 0.0, 0.0), "Z", "Y"
    if plane_type == "back_wall":
        return (dimensions.length - center_offset, 0.0, 0.0), "Z", "Y"
    raise ValueError(f"unsupported plane_type {plane_type!r}")


def _canonical_plane_type(value: object) -> str:
    text = _non_empty_text(value, "plane_type")
    key = text.strip().lower().replace("-", "_").replace(" ", "_")
    return _PLANE_ALIASES.get(key, _PLANE_ALIASES.get(text, key))


def _require_list(raw: dict[str, object], key: str) -> list[dict[str, Any]]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise ValueError(f"project.json must define {key} as a list")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"project.json {key} entries must be mappings")
    return value


def _positive_float(value: object, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if result <= 0:
        raise ValueError(f"{field_name} must be positive")
    return result


def _float_tuple(value: object, length: int, field_name: str) -> tuple[float, ...]:
    try:
        result = tuple(float(item) for item in value)  # type: ignore[operator]
    except TypeError as exc:
        raise ValueError(f"{field_name} must contain exactly {length} numbers") from exc
    if len(result) != length:
        raise ValueError(f"{field_name} must contain exactly {length} numbers")
    return result


def _non_empty_text(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text or text == "None":
        raise ValueError(f"{field_name} cannot be empty")
    return text
