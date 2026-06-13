"""Single-face topology generation from centerline candidates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from ehouse_model.domain import Member2D, Node2D
from ehouse_model.face_model import CenterlineCandidate, Point2D, WarningRecord


@dataclass(frozen=True, slots=True)
class FaceTopology:
    nodes: tuple[Node2D, ...]
    members: tuple[Member2D, ...]
    member_sources: dict[str, str]
    warnings: tuple[WarningRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class _SplitPoint:
    t: float
    point: Point2D


@dataclass(frozen=True, slots=True)
class _Intersection:
    point: Point2D
    left_t: float
    right_t: float


def build_face_topology(
    centerlines: Iterable[CenterlineCandidate],
    node_merge_tolerance: float = 1e-6,
) -> FaceTopology:
    """Build Node2D/Member2D topology and split members at intersections."""
    candidates = tuple(centerlines)
    split_points: list[list[_SplitPoint]] = [
        [_SplitPoint(0.0, candidate.start), _SplitPoint(1.0, candidate.end)]
        for candidate in candidates
    ]
    warnings: list[WarningRecord] = []

    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            intersection = _segment_intersection(left, right, node_merge_tolerance)
            if intersection == "overlap":
                warnings.append(
                    WarningRecord(
                        code="overlapping_centerlines",
                        message="Two centerline candidates overlap and need manual review.",
                        entity_id=f"{left.id},{right.id}",
                    )
                )
            elif intersection is not None:
                split_points[left_index].append(
                    _SplitPoint(intersection.left_t, intersection.point)
                )
                split_points[right_index].append(
                    _SplitPoint(intersection.right_t, intersection.point)
                )

    nodes: list[Node2D] = []
    members: list[Member2D] = []
    member_sources: dict[str, str] = {}

    for candidate, raw_points in zip(candidates, split_points):
        ordered_points = _dedupe_split_points(raw_points, node_merge_tolerance)
        for start, end in zip(ordered_points, ordered_points[1:]):
            if _distance(start.point, end.point) <= node_merge_tolerance:
                continue

            start_node_id = _node_id_for_point(nodes, start.point, node_merge_tolerance)
            end_node_id = _node_id_for_point(nodes, end.point, node_merge_tolerance)
            if start_node_id == end_node_id:
                continue

            member = Member2D(
                id=f"M{len(members) + 1}",
                start_node_id=start_node_id,
                end_node_id=end_node_id,
            )
            members.append(member)
            member_sources[member.id] = candidate.id

    return FaceTopology(
        nodes=tuple(nodes),
        members=tuple(members),
        member_sources=member_sources,
        warnings=tuple(warnings),
    )


def _segment_intersection(
    left: CenterlineCandidate,
    right: CenterlineCandidate,
    tolerance: float,
) -> _Intersection | str | None:
    p = left.start
    r = _subtract(left.end, left.start)
    q = right.start
    s = _subtract(right.end, right.start)
    r_cross_s = _cross(r, s)
    q_minus_p = _subtract(q, p)

    if abs(r_cross_s) <= tolerance:
        if abs(_cross(q_minus_p, r)) <= tolerance:
            return "overlap" if _has_collinear_overlap(p, r, q, s, tolerance) else None
        return None

    left_t = _cross(q_minus_p, s) / r_cross_s
    right_t = _cross(q_minus_p, r) / r_cross_s
    if not _within_unit_interval(left_t, tolerance):
        return None
    if not _within_unit_interval(right_t, tolerance):
        return None

    clamped_left_t = _clamp(left_t, 0.0, 1.0)
    clamped_right_t = _clamp(right_t, 0.0, 1.0)
    point = (p[0] + clamped_left_t * r[0], p[1] + clamped_left_t * r[1])
    return _Intersection(point=point, left_t=clamped_left_t, right_t=clamped_right_t)


def _has_collinear_overlap(
    p: Point2D,
    r: Point2D,
    q: Point2D,
    s: Point2D,
    tolerance: float,
) -> bool:
    r_length_squared = _dot(r, r)
    if r_length_squared <= tolerance:
        return False

    start_t = _dot(_subtract(q, p), r) / r_length_squared
    end_t = _dot(_subtract((q[0] + s[0], q[1] + s[1]), p), r) / r_length_squared
    overlap_start = max(0.0, min(start_t, end_t))
    overlap_end = min(1.0, max(start_t, end_t))
    return overlap_end - overlap_start > tolerance


def _dedupe_split_points(
    split_points: list[_SplitPoint],
    tolerance: float,
) -> list[_SplitPoint]:
    result: list[_SplitPoint] = []
    for point in sorted(split_points, key=lambda item: item.t):
        if result and _distance(result[-1].point, point.point) <= tolerance:
            continue
        result.append(point)
    return result


def _node_id_for_point(nodes: list[Node2D], point: Point2D, tolerance: float) -> str:
    for node in nodes:
        if math.hypot(node.x - point[0], node.y - point[1]) <= tolerance:
            return node.id

    node = Node2D(id=f"N{len(nodes) + 1}", x=point[0], y=point[1])
    nodes.append(node)
    return node.id


def _subtract(left: Point2D, right: Point2D) -> Point2D:
    return (left[0] - right[0], left[1] - right[1])


def _distance(left: Point2D, right: Point2D) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _dot(left: Point2D, right: Point2D) -> float:
    return left[0] * right[0] + left[1] * right[1]


def _cross(left: Point2D, right: Point2D) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _within_unit_interval(value: float, tolerance: float) -> bool:
    return -tolerance <= value <= 1.0 + tolerance


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
