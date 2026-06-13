"""Domain data models shared by the geometry pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


def normalize_axis(axis: str) -> str:
    """Return a canonical axis token: X, Y, Z, -X, -Y, or -Z."""
    if not isinstance(axis, str):
        raise TypeError("axis must be a string")

    token = axis.strip().upper()
    if not token:
        raise ValueError("axis cannot be empty")

    sign = ""
    if token[0] in "+-":
        sign = "-" if token[0] == "-" else ""
        token = token[1:]

    if token not in _AXIS_INDEX:
        raise ValueError(f"unsupported axis {axis!r}; expected X, Y, Z, -X, -Y, or -Z")

    return f"{sign}{token}"


def axis_vector(axis: str) -> tuple[float, float, float]:
    """Convert an axis token to a unit vector in global XYZ coordinates."""
    token = normalize_axis(axis)
    sign = -1.0 if token.startswith("-") else 1.0
    name = token[1:] if token.startswith("-") else token
    vector = [0.0, 0.0, 0.0]
    vector[_AXIS_INDEX[name]] = sign
    return tuple(vector)


def _axis_name(axis: str) -> str:
    token = normalize_axis(axis)
    return token[1:] if token.startswith("-") else token


def _coerce_float(value: object, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc


def _coerce_float_tuple(
    values: Iterable[object],
    *,
    length: int,
    field_name: str,
) -> tuple[float, ...]:
    try:
        result = tuple(float(value) for value in values)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a sequence of {length} numbers") from exc
    except ValueError as exc:
        raise ValueError(f"{field_name} must contain only numbers") from exc

    if len(result) != length:
        raise ValueError(f"{field_name} must contain exactly {length} numbers")
    return result


def _coerce_id(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text


@dataclass(frozen=True, slots=True)
class PlaneSpec:
    """Mapping from a face-local 2D coordinate system into global XYZ."""

    name: str
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    local_x_axis: str = "X"
    local_y_axis: str = "Y"
    dxf_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _coerce_id(self.name, "name"))
        object.__setattr__(
            self,
            "origin",
            _coerce_float_tuple(self.origin, length=3, field_name="origin"),
        )
        object.__setattr__(self, "local_x_axis", normalize_axis(self.local_x_axis))
        object.__setattr__(self, "local_y_axis", normalize_axis(self.local_y_axis))

        if _axis_name(self.local_x_axis) == _axis_name(self.local_y_axis):
            raise ValueError("local_x_axis and local_y_axis must use different global axes")

        if self.dxf_path is not None:
            object.__setattr__(self, "dxf_path", str(self.dxf_path))

    @property
    def local_x_vector(self) -> tuple[float, float, float]:
        return axis_vector(self.local_x_axis)

    @property
    def local_y_vector(self) -> tuple[float, float, float]:
        return axis_vector(self.local_y_axis)


@dataclass(frozen=True, slots=True)
class StitchRule:
    """Declared relationship between two named face edges."""

    source_plane: str
    target_plane: str
    source_edge: str
    target_edge: str
    tolerance: float = 0.001

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_plane", _coerce_id(self.source_plane, "source_plane"))
        object.__setattr__(self, "target_plane", _coerce_id(self.target_plane, "target_plane"))
        object.__setattr__(self, "source_edge", _coerce_id(self.source_edge, "source_edge"))
        object.__setattr__(self, "target_edge", _coerce_id(self.target_edge, "target_edge"))
        object.__setattr__(self, "tolerance", _coerce_float(self.tolerance, "tolerance"))

        if self.tolerance <= 0:
            raise ValueError("tolerance must be positive")


@dataclass(frozen=True, slots=True)
class Node2D:
    id: str
    x: float
    y: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _coerce_id(self.id, "id"))
        object.__setattr__(self, "x", _coerce_float(self.x, "x"))
        object.__setattr__(self, "y", _coerce_float(self.y, "y"))


@dataclass(frozen=True, slots=True)
class Member2D:
    id: str
    start_node_id: str
    end_node_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _coerce_id(self.id, "id"))
        object.__setattr__(self, "start_node_id", _coerce_id(self.start_node_id, "start_node_id"))
        object.__setattr__(self, "end_node_id", _coerce_id(self.end_node_id, "end_node_id"))

        if self.start_node_id == self.end_node_id:
            raise ValueError("member start_node_id and end_node_id must be different")


@dataclass(frozen=True, slots=True)
class Node3D:
    id: str
    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _coerce_id(self.id, "id"))
        object.__setattr__(self, "x", _coerce_float(self.x, "x"))
        object.__setattr__(self, "y", _coerce_float(self.y, "y"))
        object.__setattr__(self, "z", _coerce_float(self.z, "z"))


@dataclass(frozen=True, slots=True)
class Member3D:
    id: str
    start_node_id: str
    end_node_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _coerce_id(self.id, "id"))
        object.__setattr__(self, "start_node_id", _coerce_id(self.start_node_id, "start_node_id"))
        object.__setattr__(self, "end_node_id", _coerce_id(self.end_node_id, "end_node_id"))

        if self.start_node_id == self.end_node_id:
            raise ValueError("member start_node_id and end_node_id must be different")
