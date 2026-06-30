"""Side-wall plan-view section marker recognition."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.dxf_reader import DxfSegment2D, Point2D, read_dxf_segments
from ehouse_model.face_model import WarningRecord
from ehouse_model.part_geometry import PartGeometry, PartGeometrySource


@dataclass(frozen=True, slots=True)
class SideWallFacePlanSpec:
    face_name: str
    fixed_axis: str
    fixed_coordinate: float
    filter_axis: str
    filter_min: float
    filter_max: float
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "face_name", _non_empty_text(self.face_name, "face_name"))
        fixed_axis = _axis(self.fixed_axis, "fixed_axis")
        filter_axis = _axis(self.filter_axis, "filter_axis")
        object.__setattr__(self, "fixed_axis", fixed_axis)
        object.__setattr__(self, "filter_axis", filter_axis)
        object.__setattr__(self, "fixed_coordinate", float(self.fixed_coordinate))
        filter_min = float(self.filter_min)
        filter_max = float(self.filter_max)
        if filter_min > filter_max:
            filter_min, filter_max = filter_max, filter_min
        object.__setattr__(self, "filter_min", filter_min)
        object.__setattr__(self, "filter_max", filter_max)
        object.__setattr__(self, "enabled", bool(self.enabled))


@dataclass(frozen=True, slots=True)
class SideWallPlanOptions:
    top_y: float
    duplicate_tolerance: float = 0.001
    reuse_tolerance: float = 0.001
    face_specs: tuple[SideWallFacePlanSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "top_y", float(self.top_y))
        object.__setattr__(self, "duplicate_tolerance", float(self.duplicate_tolerance))
        object.__setattr__(self, "reuse_tolerance", float(self.reuse_tolerance))
        object.__setattr__(self, "face_specs", tuple(self.face_specs))
        if self.top_y <= 0:
            raise ValueError("top_y must be positive")
        if self.duplicate_tolerance < 0:
            raise ValueError("duplicate_tolerance cannot be negative")
        if self.reuse_tolerance < 0:
            raise ValueError("reuse_tolerance cannot be negative")
        if not any(spec.enabled for spec in self.face_specs):
            raise ValueError("at least one side-wall face spec must be enabled")


@dataclass(frozen=True, slots=True)
class SectionMarkerCentroid:
    id: str
    x: float
    z: float
    source_segment_ids: tuple[str, ...]


def extract_side_wall_plan(dxf_path: str | Path, options: SideWallPlanOptions) -> PartGeometry:
    """Recognize section-marker centroids from a side-wall top-view DXF."""
    source_path = Path(dxf_path)
    segments = read_dxf_segments(source_path)
    centroids, warnings = extract_section_marker_centroids(
        segments,
        duplicate_tolerance=options.duplicate_tolerance,
    )

    assignments: list[tuple[int, SectionMarkerCentroid, SideWallFacePlanSpec]] = []
    for centroid in centroids:
        matches = [
            (spec_index, spec)
            for spec_index, spec in enumerate(options.face_specs)
            if spec.enabled and _centroid_matches_filter(centroid, spec)
        ]
        if not matches:
            warnings.append(
                WarningRecord(
                    code="section_marker_unmatched",
                    message="A section marker centroid did not match any enabled wall-face range.",
                    entity_id=centroid.id,
                )
            )
            continue
        if len(matches) > 1:
            warnings.append(
                WarningRecord(
                    level="info",
                    code="section_marker_multiple_faces",
                    message="A section marker matched multiple wall-face ranges; the first match was used.",
                    entity_id=centroid.id,
                )
            )
        spec_index, spec = matches[0]
        assignments.append((spec_index, centroid, spec))

    nodes: list[Node3D] = []
    members: list[Member3D] = []
    assigned_index = 0
    for _spec_index, centroid, spec in sorted(
        assignments,
        key=lambda item: (item[0], item[1].x, item[1].z),
    ):
        assigned_index += 1
        x, z = _global_plan_point(centroid, spec)
        bottom_id = f"{spec.face_name}_{assigned_index}B"
        top_id = f"{spec.face_name}_{assigned_index}T"
        member_id = f"{spec.face_name}_{assigned_index}"
        nodes.append(Node3D(id=bottom_id, x=x, y=0.0, z=z))
        nodes.append(Node3D(id=top_id, x=x, y=options.top_y, z=z))
        members.append(Member3D(id=member_id, start_node_id=bottom_id, end_node_id=top_id))

    return PartGeometry(
        part_id="side_wall",
        part_type="side_wall",
        source=PartGeometrySource(
            kind="generated_from_plan_section_markers",
            path=str(source_path),
            description=f"Generated from side-wall plan section markers at top Y={options.top_y:g}.",
        ),
        nodes=tuple(nodes),
        members=tuple(members),
        warnings=_renumber_warnings(warnings),
    )


def extract_section_marker_centroids(
    segments: list[DxfSegment2D],
    *,
    duplicate_tolerance: float = 0.001,
    point_tolerance: float = 1e-6,
) -> tuple[tuple[SectionMarkerCentroid, ...], list[WarningRecord]]:
    """Find closed straight-line loops and return their polygon centroids."""
    loops, warnings = _closed_segment_loops(segments, point_tolerance=point_tolerance)
    raw_centroids: list[SectionMarkerCentroid] = []
    for index, loop in enumerate(loops, start=1):
        centroid = _polygon_centroid(loop.points)
        if centroid is None:
            warnings.append(
                WarningRecord(
                    code="invalid_section_marker_loop",
                    message="A closed section marker loop has near-zero area and was ignored.",
                    entity_id=f"loop_{index}",
                )
            )
            continue
        raw_centroids.append(
            SectionMarkerCentroid(
                id=f"S{len(raw_centroids) + 1}",
                x=centroid[0],
                z=centroid[1],
                source_segment_ids=loop.segment_ids,
            )
        )

    centroids: list[SectionMarkerCentroid] = []
    for centroid in raw_centroids:
        existing = _find_near_centroid(centroids, centroid, duplicate_tolerance)
        if existing is not None:
            warnings.append(
                WarningRecord(
                    level="info",
                    code="duplicate_section_marker_merged",
                    message="A duplicate section marker centroid was merged.",
                    entity_id=f"{existing.id},{centroid.id}",
                )
            )
            continue
        centroids.append(
            SectionMarkerCentroid(
                id=f"S{len(centroids) + 1}",
                x=centroid.x,
                z=centroid.z,
                source_segment_ids=centroid.source_segment_ids,
            )
        )

    if not centroids:
        warnings.append(
            WarningRecord(
                code="no_section_markers",
                message="No closed section marker loops were recognized from the side-wall plan DXF.",
            )
        )
    return tuple(centroids), warnings


@dataclass(frozen=True, slots=True)
class _ClosedLoop:
    points: tuple[Point2D, ...]
    segment_ids: tuple[str, ...]


def _closed_segment_loops(
    segments: list[DxfSegment2D],
    *,
    point_tolerance: float,
) -> tuple[list[_ClosedLoop], list[WarningRecord]]:
    point_by_key: dict[tuple[int, int], Point2D] = {}
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], str]]] = defaultdict(list)
    for segment in segments:
        start_key = _point_key(segment.start, point_tolerance)
        end_key = _point_key(segment.end, point_tolerance)
        point_by_key.setdefault(start_key, segment.start)
        point_by_key.setdefault(end_key, segment.end)
        adjacency[start_key].append((end_key, segment.id))
        adjacency[end_key].append((start_key, segment.id))

    loops: list[_ClosedLoop] = []
    warnings: list[WarningRecord] = []
    visited_nodes: set[tuple[int, int]] = set()
    for start_key in sorted(adjacency):
        if start_key in visited_nodes:
            continue
        component = _component_nodes(adjacency, start_key)
        visited_nodes.update(component)
        edge_count = sum(len(adjacency[node]) for node in component) // 2
        if len(component) < 3 or edge_count < 3:
            continue
        if any(len(adjacency[node]) != 2 for node in component):
            warnings.append(
                WarningRecord(
                    code="open_or_branching_section_marker",
                    message="A section-marker segment group was not a simple closed loop and was ignored.",
                )
            )
            continue
        loop = _ordered_loop(component, adjacency, point_by_key)
        if loop is not None:
            loops.append(loop)
    return loops, warnings


def _component_nodes(
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], str]]],
    start: tuple[int, int],
) -> set[tuple[int, int]]:
    seen = {start}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor, _segment_id in adjacency[current]:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return seen


def _ordered_loop(
    component: set[tuple[int, int]],
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], str]]],
    point_by_key: dict[tuple[int, int], Point2D],
) -> _ClosedLoop | None:
    start = min(component)
    previous: tuple[int, int] | None = None
    current = start
    ordered_keys = [start]
    segment_ids: list[str] = []
    used_edges: set[frozenset[tuple[int, int]]] = set()

    while True:
        choices = [
            (neighbor, segment_id)
            for neighbor, segment_id in adjacency[current]
            if neighbor != previous
        ]
        if not choices:
            return None
        next_key, segment_id = choices[0]
        edge = frozenset((current, next_key))
        if edge in used_edges:
            return None
        used_edges.add(edge)
        segment_ids.append(segment_id)
        if next_key == start:
            break
        if next_key in ordered_keys:
            return None
        ordered_keys.append(next_key)
        previous, current = current, next_key

    if len(used_edges) != len(component):
        return None
    return _ClosedLoop(
        points=tuple(point_by_key[key] for key in ordered_keys),
        segment_ids=tuple(segment_ids),
    )


def _polygon_centroid(points: tuple[Point2D, ...]) -> Point2D | None:
    area_twice = 0.0
    centroid_x = 0.0
    centroid_y = 0.0
    for left, right in zip(points, (*points[1:], points[0])):
        cross = left[0] * right[1] - right[0] * left[1]
        area_twice += cross
        centroid_x += (left[0] + right[0]) * cross
        centroid_y += (left[1] + right[1]) * cross

    if math.isclose(area_twice, 0.0, abs_tol=1e-12):
        return None
    return (centroid_x / (3.0 * area_twice), centroid_y / (3.0 * area_twice))


def _centroid_matches_filter(centroid: SectionMarkerCentroid, spec: SideWallFacePlanSpec) -> bool:
    value = centroid.x if spec.filter_axis == "X" else centroid.z
    return spec.filter_min <= value <= spec.filter_max


def _global_plan_point(centroid: SectionMarkerCentroid, spec: SideWallFacePlanSpec) -> tuple[float, float]:
    if spec.fixed_axis == "X":
        return _clean_float(spec.fixed_coordinate), _clean_float(centroid.z)
    return _clean_float(centroid.x), _clean_float(spec.fixed_coordinate)


def _find_near_centroid(
    centroids: list[SectionMarkerCentroid],
    target: SectionMarkerCentroid,
    tolerance: float,
) -> SectionMarkerCentroid | None:
    for centroid in centroids:
        if math.hypot(centroid.x - target.x, centroid.z - target.z) <= tolerance:
            return centroid
    return None


def _renumber_warnings(warnings: list[WarningRecord]) -> tuple[WarningRecord, ...]:
    return tuple(warning.with_id(f"W{index}") for index, warning in enumerate(warnings, start=1))


def _point_key(point: Point2D, tolerance: float) -> tuple[int, int]:
    return (round(point[0] / tolerance), round(point[1] / tolerance))


def _clean_float(value: float) -> float:
    return float(f"{value:.12g}")


def _axis(value: object, field_name: str) -> str:
    text = _non_empty_text(value, field_name).upper()
    if text not in {"X", "Z"}:
        raise ValueError(f"{field_name} must be X or Z")
    return text


def _non_empty_text(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} cannot be empty")
    return text
