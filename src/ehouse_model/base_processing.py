"""Base-face processing helpers for the first GUI workflow."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from ehouse_model.domain import Member2D, Member3D, Node2D, Node3D
from ehouse_model.dxf_reader import Point2D, read_dxf_segments, write_overlay_dxf
from ehouse_model.exporters import export_staad_geometry, export_warnings_csv
from ehouse_model.face_extractor import FaceExtractionOptions, extract_centerline_candidates
from ehouse_model.face_model import (
    CenterlineCandidate,
    FaceModel,
    WarningRecord,
    write_face_model_json,
)
from ehouse_model.face_topology import build_face_topology
from ehouse_model.global_model_types import GlobalModel

DXF_MM_TO_M = 0.001
DEFAULT_SNAP_EXTENSION_MARGIN = 5.0
DEFAULT_SNAP_EXTENSION_MARGIN_RATIO = 0.05


@dataclass(frozen=True, slots=True)
class BaseProcessingOptions:
    snap_extend_tolerance: float = 200.0
    node_merge_tolerance: float = 1e-6
    snap_extension_margin: float = DEFAULT_SNAP_EXTENSION_MARGIN
    snap_extension_margin_ratio: float = DEFAULT_SNAP_EXTENSION_MARGIN_RATIO

    def __post_init__(self) -> None:
        if self.snap_extend_tolerance < 0:
            raise ValueError("snap_extend_tolerance cannot be negative")
        if self.node_merge_tolerance <= 0:
            raise ValueError("node_merge_tolerance must be positive")
        if self.snap_extension_margin < 0:
            raise ValueError("snap_extension_margin cannot be negative")
        if self.snap_extension_margin_ratio < 0:
            raise ValueError("snap_extension_margin_ratio cannot be negative")


@dataclass(frozen=True, slots=True)
class BaseNormalizationResult:
    face_model: FaceModel
    origin: Point2D


@dataclass(frozen=True, slots=True)
class BaseExtractionResult:
    face_model: FaceModel
    global_model: GlobalModel
    origin: Point2D
    snap_count: int
    terminal_stub_removed_count: int = 0


def extract_base_face(
    dxf_path: str | Path,
    *,
    face_model_path: str | Path | None = None,
    overlay_path: str | Path | None = None,
    warnings_csv_path: str | Path | None = None,
    extraction_options: FaceExtractionOptions | None = None,
    base_options: BaseProcessingOptions | None = None,
) -> BaseExtractionResult:
    """Extract, snap/extend, normalize, and optionally save a base face model."""
    extract_opts = extraction_options or FaceExtractionOptions()
    base_opts = base_options or BaseProcessingOptions()
    source_path = Path(dxf_path)

    segments = read_dxf_segments(source_path)
    candidates, extraction_warnings = extract_centerline_candidates(segments, extract_opts)
    snapped_candidates, snap_count, snap_warnings = snap_extend_centerlines(
        candidates,
        tolerance=base_opts.snap_extend_tolerance,
        margin=base_opts.snap_extension_margin,
        margin_ratio=base_opts.snap_extension_margin_ratio,
    )
    topology = build_face_topology(snapped_candidates, base_opts.node_merge_tolerance)
    raw_model = FaceModel(
        source_dxf=str(source_path),
        nodes=topology.nodes,
        members=topology.members,
        centerline_candidates=tuple(snapped_candidates),
        member_sources=topology.member_sources,
    )
    raw_model, terminal_stub_removed_count = prune_base_terminal_stubs(
        raw_model,
        tolerance=base_opts.node_merge_tolerance,
    )
    warning_inputs = [*extraction_warnings, *snap_warnings, *topology.warnings]
    if terminal_stub_removed_count:
        warning_inputs.append(
            WarningRecord(
                level="info",
                code="base_terminal_stubs_removed",
                message=(
                    f"{terminal_stub_removed_count} terminal member(s) outside the "
                    "base left/right boundaries were removed."
                ),
            )
        )
    warnings = _renumber_warnings(warning_inputs)
    raw_model = _replace_face_model_warnings(raw_model, warnings)
    normalized = normalize_base_coordinates(raw_model)
    model = normalized.face_model
    global_model = face_model_to_base_global_model(model)

    if face_model_path is not None:
        write_face_model_json(model, face_model_path)
    if warnings_csv_path is not None:
        export_warnings_csv(model.warnings, warnings_csv_path)
    if overlay_path is not None:
        write_overlay_dxf(
            overlay_path,
            outline_segments=segments,
            centerline_segments=_member_segments(raw_model),
        )

    return BaseExtractionResult(
        face_model=model,
        global_model=global_model,
        origin=normalized.origin,
        snap_count=snap_count,
        terminal_stub_removed_count=terminal_stub_removed_count,
    )


def snap_extend_centerlines(
    centerlines: tuple[CenterlineCandidate, ...] | list[CenterlineCandidate],
    *,
    tolerance: float = 200.0,
    margin: float = DEFAULT_SNAP_EXTENSION_MARGIN,
    margin_ratio: float = DEFAULT_SNAP_EXTENSION_MARGIN_RATIO,
) -> tuple[tuple[CenterlineCandidate, ...], int, tuple[WarningRecord, ...]]:
    """Extend centerline endpoints to intersections allowed by member widths."""
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    if margin < 0:
        raise ValueError("margin cannot be negative")
    if margin_ratio < 0:
        raise ValueError("margin_ratio cannot be negative")

    candidates = tuple(centerlines)
    t_values: list[list[float]] = [[0.0, 1.0] for _ in candidates]
    warnings: list[WarningRecord] = []

    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            intersection = _infinite_line_intersection(left.start, left.end, right.start, right.end)
            if intersection is None:
                continue
            sin_angle = _line_sin_angle(left.start, left.end, right.start, right.end)
            if sin_angle is None:
                continue

            point, left_t, right_t = intersection
            left_gap = _extension_gap_to_intersection(point, left.start, left.end, left_t)
            right_gap = _extension_gap_to_intersection(point, right.start, right.end, right_t)
            left_limit = _width_based_extension_limit(
                right.width,
                max_extension=tolerance,
                margin=margin,
                margin_ratio=margin_ratio,
                sin_angle=sin_angle,
            )
            right_limit = _width_based_extension_limit(
                left.width,
                max_extension=tolerance,
                margin=margin,
                margin_ratio=margin_ratio,
                sin_angle=sin_angle,
            )
            if left_gap > left_limit + 1e-9:
                continue
            if right_gap > right_limit + 1e-9:
                continue

            t_values[left_index].append(left_t)
            t_values[right_index].append(right_t)

    snapped: list[CenterlineCandidate] = []
    snap_count = 0
    for candidate, values in zip(candidates, t_values):
        start_t = min(values)
        end_t = max(values)
        if start_t < 0.0 or end_t > 1.0:
            snap_count += int(start_t < 0.0) + int(end_t > 1.0)

        snapped.append(
            CenterlineCandidate(
                id=candidate.id,
                kind=candidate.kind,
                start=_point_at(candidate.start, candidate.end, start_t),
                end=_point_at(candidate.start, candidate.end, end_t),
                source_segment_ids=candidate.source_segment_ids,
                width=candidate.width,
                overlap=candidate.overlap,
                confidence=candidate.confidence,
            )
        )

    if snap_count:
        warnings.append(
            WarningRecord(
                level="info",
                code="base_centerlines_extended",
                message=(
                    f"{snap_count} centerline endpoint(s) were extended to intersections "
                    "using width-based limits."
                ),
            )
        )

    return tuple(snapped), snap_count, tuple(warnings)


def normalize_base_coordinates(face_model: FaceModel) -> BaseNormalizationResult:
    """Set base top-left centerline node as (0, 0), with X right and Z down."""
    if not face_model.nodes:
        raise ValueError("cannot normalize a base face without nodes")

    origin_node = _select_top_left_intersection_node(face_model)
    origin_mm = (origin_node.x, origin_node.y)
    origin_m = (_round4(origin_mm[0] * DXF_MM_TO_M), _round4(origin_mm[1] * DXF_MM_TO_M))
    nodes = tuple(
        Node2D(
            id=node.id,
            x=_round4((node.x - origin_mm[0]) * DXF_MM_TO_M),
            y=_round4((origin_mm[1] - node.y) * DXF_MM_TO_M),
        )
        for node in face_model.nodes
    )
    candidates = tuple(
        CenterlineCandidate(
            id=candidate.id,
            kind=candidate.kind,
            start=_normalize_point(candidate.start, origin_mm),
            end=_normalize_point(candidate.end, origin_mm),
            source_segment_ids=candidate.source_segment_ids,
            width=_round4(candidate.width * DXF_MM_TO_M),
            overlap=_round4(candidate.overlap * DXF_MM_TO_M),
            confidence=candidate.confidence,
        )
        for candidate in face_model.centerline_candidates
    )
    model = FaceModel(
        source_dxf=face_model.source_dxf,
        nodes=nodes,
        members=face_model.members,
        centerline_candidates=candidates,
        member_sources=face_model.member_sources,
        warnings=face_model.warnings,
    )
    return BaseNormalizationResult(face_model=model, origin=origin_m)


def prune_base_terminal_stubs(
    face_model: FaceModel,
    *,
    tolerance: float = 1e-6,
) -> tuple[FaceModel, int]:
    """Remove topology members that lie outside the base left/right boundaries."""
    if not face_model.nodes or not face_model.members:
        return face_model, 0

    nodes_by_id = {node.id: node for node in face_model.nodes}
    intersection_nodes = [
        node
        for node in face_model.nodes
        if _has_nonparallel_incident_members(node, nodes_by_id, face_model.members)
    ]
    if len(intersection_nodes) < 2:
        return face_model, 0

    left_boundary = min(node.x for node in intersection_nodes)
    right_boundary = max(node.x for node in intersection_nodes)

    kept_members: list[Member2D] = []
    removed_count = 0
    for member in face_model.members:
        start = nodes_by_id[member.start_node_id]
        end = nodes_by_id[member.end_node_id]
        if (
            start.x < left_boundary - tolerance
            or end.x < left_boundary - tolerance
            or start.x > right_boundary + tolerance
            or end.x > right_boundary + tolerance
        ):
            removed_count += 1
            continue
        kept_members.append(member)

    if removed_count == 0:
        return face_model, 0

    used_node_ids = {
        node_id
        for member in kept_members
        for node_id in (member.start_node_id, member.end_node_id)
    }
    kept_nodes = tuple(node for node in face_model.nodes if node.id in used_node_ids)
    kept_member_sources = {
        member.id: face_model.member_sources[member.id]
        for member in kept_members
        if member.id in face_model.member_sources
    }
    return (
        FaceModel(
            source_dxf=face_model.source_dxf,
            nodes=kept_nodes,
            members=tuple(kept_members),
            centerline_candidates=face_model.centerline_candidates,
            member_sources=kept_member_sources,
            warnings=face_model.warnings,
        ),
        removed_count,
    )


def _replace_face_model_warnings(
    face_model: FaceModel,
    warnings: tuple[WarningRecord, ...],
) -> FaceModel:
    return FaceModel(
        source_dxf=face_model.source_dxf,
        nodes=face_model.nodes,
        members=face_model.members,
        centerline_candidates=face_model.centerline_candidates,
        member_sources=face_model.member_sources,
        warnings=warnings,
    )


def _member_segments(face_model: FaceModel) -> list[tuple[Point2D, Point2D]]:
    nodes_by_id = {node.id: node for node in face_model.nodes}
    segments: list[tuple[Point2D, Point2D]] = []
    for member in face_model.members:
        start = nodes_by_id.get(member.start_node_id)
        end = nodes_by_id.get(member.end_node_id)
        if start is None or end is None:
            continue
        segments.append(((start.x, start.y), (end.x, end.y)))
    return segments


def _select_top_left_intersection_node(face_model: FaceModel) -> Node2D:
    nodes = {node.id: node for node in face_model.nodes}
    intersection_nodes = [
        node
        for node in face_model.nodes
        if _has_nonparallel_incident_members(node, nodes, face_model.members)
    ]
    candidates = intersection_nodes or list(face_model.nodes)
    return min(candidates, key=lambda node: (node.x, -node.y, node.id))


def _has_nonparallel_incident_members(
    node: Node2D,
    nodes: dict[str, Node2D],
    members: tuple[Member2D, ...],
) -> bool:
    directions: list[Point2D] = []
    for member in members:
        if member.start_node_id == node.id:
            other = nodes.get(member.end_node_id)
        elif member.end_node_id == node.id:
            other = nodes.get(member.start_node_id)
        else:
            continue
        if other is None:
            continue

        vector = (other.x - node.x, other.y - node.y)
        length = math.hypot(vector[0], vector[1])
        if length <= 1e-9:
            continue
        direction = (vector[0] / length, vector[1] / length)
        if any(abs(_cross(direction, existing)) > 1e-3 for existing in directions):
            return True
        directions.append(direction)

    return False


def face_model_to_base_global_model(
    face_model: FaceModel,
    *,
    project_name: str = "E-House 底座",
) -> GlobalModel:
    """Convert a normalized base face model to Y=0 global geometry."""
    nodes = tuple(
        Node3D(id=node.id, x=node.x, y=0.0, z=node.y)
        for node in face_model.nodes
    )
    members = tuple(
        Member3D(
            id=member.id,
            start_node_id=member.start_node_id,
            end_node_id=member.end_node_id,
        )
        for member in face_model.members
    )
    return GlobalModel(project_name=project_name, nodes=nodes, members=members, warnings=face_model.warnings)


def export_base_staad(face_model: FaceModel, path: str | Path) -> None:
    """Export a normalized base face model directly to geometry.std."""
    export_staad_geometry(face_model_to_base_global_model(face_model), path)


def _infinite_line_intersection(
    left_start: Point2D,
    left_end: Point2D,
    right_start: Point2D,
    right_end: Point2D,
) -> tuple[Point2D, float, float] | None:
    left_vector = _subtract(left_end, left_start)
    right_vector = _subtract(right_end, right_start)
    denominator = _cross(left_vector, right_vector)
    if math.isclose(denominator, 0.0, abs_tol=1e-12):
        return None

    delta = _subtract(right_start, left_start)
    left_t = _cross(delta, right_vector) / denominator
    right_t = _cross(delta, left_vector) / denominator
    point = _point_at(left_start, left_end, left_t)
    return point, left_t, right_t


def _distance_point_to_segment(point: Point2D, start: Point2D, end: Point2D) -> float:
    segment = _subtract(end, start)
    length_squared = _dot(segment, segment)
    if length_squared == 0:
        return _distance(point, start)

    t_value = _dot(_subtract(point, start), segment) / length_squared
    clamped_t = min(max(t_value, 0.0), 1.0)
    closest = _point_at(start, end, clamped_t)
    return _distance(point, closest)


def _normalize_point(point: Point2D, origin: Point2D) -> Point2D:
    return (
        _round4((point[0] - origin[0]) * DXF_MM_TO_M),
        _round4((origin[1] - point[1]) * DXF_MM_TO_M),
    )


def _extension_gap_to_intersection(
    point: Point2D,
    start: Point2D,
    end: Point2D,
    t_value: float,
) -> float:
    if 0.0 <= t_value <= 1.0:
        return 0.0
    if t_value < 0.0:
        return _distance(point, start)
    return _distance(point, end)


def _width_based_extension_limit(
    target_width: float,
    *,
    max_extension: float,
    margin: float,
    margin_ratio: float,
    sin_angle: float,
) -> float:
    if max_extension == 0.0:
        return 0.0
    safe_sin = max(abs(sin_angle), 1e-9)
    width = max(float(target_width), 0.0)
    geometric_limit = (width / 2.0) / safe_sin
    margin_limit = max(margin, width * margin_ratio) / safe_sin
    return min(max_extension, geometric_limit + margin_limit)


def _point_at(start: Point2D, end: Point2D, t_value: float) -> Point2D:
    return (
        start[0] + (end[0] - start[0]) * t_value,
        start[1] + (end[1] - start[1]) * t_value,
    )


def _renumber_warnings(warnings: list[WarningRecord]) -> tuple[WarningRecord, ...]:
    return tuple(
        warning.with_id(f"W{index}")
        for index, warning in enumerate(warnings, start=1)
    )


def _subtract(left: Point2D, right: Point2D) -> Point2D:
    return (left[0] - right[0], left[1] - right[1])


def _distance(left: Point2D, right: Point2D) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _dot(left: Point2D, right: Point2D) -> float:
    return left[0] * right[0] + left[1] * right[1]


def _cross(left: Point2D, right: Point2D) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _line_sin_angle(
    left_start: Point2D,
    left_end: Point2D,
    right_start: Point2D,
    right_end: Point2D,
) -> float | None:
    left = _subtract(left_end, left_start)
    right = _subtract(right_end, right_start)
    left_length = math.hypot(left[0], left[1])
    right_length = math.hypot(right[0], right[1])
    if left_length <= 1e-12 or right_length <= 1e-12:
        return None
    sin_angle = abs(_cross(left, right)) / (left_length * right_length)
    if sin_angle <= 1e-12:
        return None
    return sin_angle


def _round4(value: float) -> float:
    result = round(value, 4)
    return 0.0 if result == -0.0 else result
