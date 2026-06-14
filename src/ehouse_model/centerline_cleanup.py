"""Special cleanup rules for centerline candidates before topology building."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from ehouse_model.dxf_reader import DxfSegment2D
from ehouse_model.face_model import CenterlineCandidate, Point2D, WarningRecord


@dataclass(frozen=True, slots=True)
class CenterlineCleanupOptions:
    merge_collinear_overlaps: bool = True
    angle_tolerance_degrees: float = 1.0
    min_pair_width: float = 5.0
    min_overlap_ratio: float = 0.75
    line_distance_tolerance: float = 2.0
    overlap_gap_tolerance: float = 5.0
    width_tolerance: float = 10.0
    width_tolerance_ratio: float = 0.05
    duplicate_centerline_tolerance: float = 1.0
    short_member_radius: float = 300.0
    short_member_max_length: float = 600.0
    short_member_max_width_to_length_ratio: float = 1.0
    short_member_max_candidates_per_point: int = 2
    cluster_realign_radius: float = 800.0
    cluster_realign_max_search_candidates: int = 20
    cluster_realign_orientation: str = "auto"
    min_length: float = 1e-6

    def __post_init__(self) -> None:
        if self.angle_tolerance_degrees <= 0:
            raise ValueError("angle_tolerance_degrees must be positive")
        if self.min_pair_width <= 0:
            raise ValueError("min_pair_width must be positive")
        if not 0 < self.min_overlap_ratio <= 1:
            raise ValueError("min_overlap_ratio must be between 0 and 1")
        if self.line_distance_tolerance < 0:
            raise ValueError("line_distance_tolerance cannot be negative")
        if self.overlap_gap_tolerance < 0:
            raise ValueError("overlap_gap_tolerance cannot be negative")
        if self.width_tolerance < 0:
            raise ValueError("width_tolerance cannot be negative")
        if self.width_tolerance_ratio < 0:
            raise ValueError("width_tolerance_ratio cannot be negative")
        if self.duplicate_centerline_tolerance < 0:
            raise ValueError("duplicate_centerline_tolerance cannot be negative")
        if self.short_member_radius <= 0:
            raise ValueError("short_member_radius must be positive")
        if self.short_member_max_length <= 0:
            raise ValueError("short_member_max_length must be positive")
        if self.short_member_max_width_to_length_ratio <= 0:
            raise ValueError("short_member_max_width_to_length_ratio must be positive")
        if self.short_member_max_candidates_per_point <= 0:
            raise ValueError("short_member_max_candidates_per_point must be positive")
        if self.cluster_realign_radius <= 0:
            raise ValueError("cluster_realign_radius must be positive")
        if self.cluster_realign_max_search_candidates <= 0:
            raise ValueError("cluster_realign_max_search_candidates must be positive")
        if self.cluster_realign_orientation not in {"auto", "horizontal", "vertical"}:
            raise ValueError("cluster_realign_orientation must be auto, horizontal, or vertical")
        if self.min_length <= 0:
            raise ValueError("min_length must be positive")


@dataclass(frozen=True, slots=True)
class CenterlineCleanupResult:
    centerlines: tuple[CenterlineCandidate, ...]
    merged_group_count: int = 0
    removed_candidate_count: int = 0
    warnings: tuple[WarningRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class CenterlineSpecialFixResult:
    centerlines: tuple[CenterlineCandidate, ...]
    added_count: int = 0
    removed_count: int = 0
    replaced_group_count: int = 0
    warnings: tuple[WarningRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class _ProjectedCandidate:
    index: int
    candidate: CenterlineCandidate
    direction: Point2D
    normal: Point2D
    interval: tuple[float, float]
    length: float


@dataclass(frozen=True, slots=True)
class _ProjectedSegment:
    index: int
    segment: DxfSegment2D
    direction: Point2D
    normal: Point2D
    interval: tuple[float, float]
    offset: float
    length: float


@dataclass(frozen=True, slots=True)
class _SegmentPairCandidate:
    left: _ProjectedSegment
    right: _ProjectedSegment
    start_t: float
    end_t: float
    width: float
    overlap: float
    score: float
    distance_to_patch: float


@dataclass(frozen=True, slots=True)
class _ShortPatchCandidate:
    centerline: CenterlineCandidate
    distance_to_patch: float
    score: float


def cleanup_centerline_candidates(
    centerlines: Iterable[CenterlineCandidate],
    options: CenterlineCleanupOptions | None = None,
) -> CenterlineCleanupResult:
    """Apply automatic special-case cleanup before snapping/topology."""
    opts = options or CenterlineCleanupOptions()
    candidates = tuple(centerlines)
    if not candidates or not opts.merge_collinear_overlaps:
        return CenterlineCleanupResult(centerlines=candidates)

    return merge_collinear_centerlines(candidates, opts)


def supplement_short_member_centerlines(
    segments: Iterable[DxfSegment2D],
    centerlines: Iterable[CenterlineCandidate],
    patch_points: Iterable[Point2D],
    options: CenterlineCleanupOptions | None = None,
) -> CenterlineSpecialFixResult:
    """Add short centerlines near user-picked points using relaxed width/length ratio."""
    opts = options or CenterlineCleanupOptions()
    existing = list(centerlines)
    points = tuple(patch_points)
    if not points:
        return CenterlineSpecialFixResult(centerlines=tuple(existing))

    projected = _project_segments(tuple(segments), opts)
    added_count = 0
    warnings: list[WarningRecord] = []
    for point_index, patch_point in enumerate(points, start=1):
        pair_candidates = _find_segment_pair_candidates(
            projected,
            patch_point=patch_point,
            radius=opts.short_member_radius,
            options=opts,
            max_width_to_length_ratio=opts.short_member_max_width_to_length_ratio,
            max_pair_length=opts.short_member_max_length,
        )
        connector_candidates = _find_short_connector_candidates(
            existing,
            patch_point=patch_point,
            options=opts,
        )
        patch_candidates = [
            _ShortPatchCandidate(
                centerline=_centerline_from_segment_pair("short_patch", pair, "short_member_patch"),
                distance_to_patch=pair.distance_to_patch,
                score=pair.score,
            )
            for pair in pair_candidates
        ]
        patch_candidates.extend(connector_candidates)
        added_for_point = 0
        for patch_candidate in sorted(
            patch_candidates,
            key=lambda item: (item.distance_to_patch, item.score, item.centerline.width),
        ):
            if added_for_point >= opts.short_member_max_candidates_per_point:
                break
            candidate = _replace_centerline_id(
                patch_candidate.centerline,
                f"C{len(existing) + 1}",
            )
            if any(
                _is_duplicate_centerline(existing_candidate, candidate, opts.duplicate_centerline_tolerance)
                for existing_candidate in existing
            ):
                continue
            existing.append(candidate)
            added_for_point += 1
            added_count += 1

        if added_for_point == 0:
            warnings.append(
                WarningRecord(
                    level="info",
                    code="short_member_patch_no_candidate",
                    message=(
                        f"No short member centerline candidate was added near patch point "
                        f"{point_index} at ({patch_point[0]:.3f}, {patch_point[1]:.3f})."
                    ),
                )
            )

    if added_count:
        warnings.append(
            WarningRecord(
                level="info",
                code="short_member_patch_centerlines_added",
                message=f"{added_count} short member centerline candidate(s) were added near user-picked nodes.",
            )
        )

    return CenterlineSpecialFixResult(
        centerlines=_renumber_centerlines(tuple(existing)),
        added_count=added_count,
        warnings=tuple(warnings),
    )


def realign_centerline_cluster_near_points(
    segments: Iterable[DxfSegment2D],
    centerlines: Iterable[CenterlineCandidate],
    patch_points: Iterable[Point2D],
    options: CenterlineCleanupOptions | None = None,
) -> CenterlineSpecialFixResult:
    """Locally reselect competing parallel pairs near user-picked points."""
    opts = options or CenterlineCleanupOptions()
    current = list(centerlines)
    points = tuple(patch_points)
    if not points:
        return CenterlineSpecialFixResult(centerlines=tuple(current))

    projected = _project_segments(tuple(segments), opts)
    total_added = 0
    total_removed = 0
    replaced_groups = 0
    warnings: list[WarningRecord] = []

    for point_index, patch_point in enumerate(points, start=1):
        pair_candidates = _find_segment_pair_candidates(
            projected,
            patch_point=patch_point,
            radius=opts.cluster_realign_radius,
            options=opts,
            max_width_to_length_ratio=0.35,
            max_pair_length=None,
        )
        orientations = _cluster_realign_orientations(opts.cluster_realign_orientation)
        orientation_candidates = {
            orientation: [pair for pair in pair_candidates if _pair_orientation(pair) == orientation]
            for orientation in orientations
        }
        best_orientation: str | None = None
        best_pairs: tuple[_SegmentPairCandidate, ...] = ()
        best_change_score = 0
        for orientation, candidates_for_orientation in orientation_candidates.items():
            optimized = _select_best_non_overlapping_pairs(
                candidates_for_orientation,
                opts.cluster_realign_max_search_candidates,
            )
            if not optimized:
                continue
            new_sources = {
                frozenset((pair.left.segment.id, pair.right.segment.id))
                for pair in optimized
            }
            existing_sources = {
                frozenset(candidate.source_segment_ids)
                for candidate in current
                if _candidate_orientation(candidate) == orientation
                and _distance_point_to_segment(patch_point, candidate.start, candidate.end)
                <= opts.cluster_realign_radius
            }
            change_score = len(new_sources.symmetric_difference(existing_sources))
            if change_score > best_change_score:
                best_change_score = change_score
                best_orientation = orientation
                best_pairs = optimized

        if best_orientation is None or not best_pairs:
            warnings.append(
                WarningRecord(
                    level="info",
                    code="cluster_realign_no_candidate",
                    message=(
                        f"No competing centerline cluster was realigned near patch point "
                        f"{point_index} at ({patch_point[0]:.3f}, {patch_point[1]:.3f})."
                    ),
                )
            )
            continue

        replacement_source_ids = {
            source_id
            for pair in best_pairs
            for source_id in (pair.left.segment.id, pair.right.segment.id)
        }
        kept: list[CenterlineCandidate] = []
        removed_for_point = 0
        for candidate in current:
            if _candidate_orientation(candidate) != best_orientation:
                kept.append(candidate)
                continue
            if not (set(candidate.source_segment_ids) & replacement_source_ids):
                kept.append(candidate)
                continue
            removed_for_point += 1

        added_for_point = 0
        for pair in best_pairs:
            candidate = _centerline_from_segment_pair(
                f"C{len(kept) + added_for_point + 1}",
                pair,
                "cluster_realign_patch",
            )
            kept.append(candidate)
            added_for_point += 1

        current = list(_renumber_centerlines(tuple(kept)))
        total_added += added_for_point
        total_removed += removed_for_point
        replaced_groups += 1

    if replaced_groups:
        warnings.append(
            WarningRecord(
                level="info",
                code="cluster_realign_centerlines_replaced",
                message=(
                    f"{replaced_groups} local centerline cluster(s) were realigned; "
                    f"{total_removed} candidate(s) were removed and {total_added} candidate(s) were added."
                ),
            )
        )

    return CenterlineSpecialFixResult(
        centerlines=tuple(current),
        added_count=total_added,
        removed_count=total_removed,
        replaced_group_count=replaced_groups,
        warnings=tuple(warnings),
    )


def _cluster_realign_orientations(value: str) -> tuple[str, ...]:
    if value == "horizontal":
        return ("H",)
    if value == "vertical":
        return ("V",)
    return ("H", "V")


def _project_segments(
    segments: tuple[DxfSegment2D, ...],
    options: CenterlineCleanupOptions,
) -> list[_ProjectedSegment]:
    return [
        projection
        for index, segment in enumerate(segments)
        if (projection := _project_segment(index, segment, options)) is not None
    ]


def _project_segment(
    index: int,
    segment: DxfSegment2D,
    options: CenterlineCleanupOptions,
) -> _ProjectedSegment | None:
    vector = _subtract(segment.end, segment.start)
    length = math.hypot(vector[0], vector[1])
    if length < options.min_length:
        return None

    direction = (vector[0] / length, vector[1] / length)
    if direction[0] < -1e-12 or (abs(direction[0]) <= 1e-12 and direction[1] < 0):
        direction = (-direction[0], -direction[1])
    normal = (-direction[1], direction[0])

    return _ProjectedSegment(
        index=index,
        segment=segment,
        direction=direction,
        normal=normal,
        interval=_point_interval_on_direction(segment.start, segment.end, direction),
        offset=_segment_offset_on_normal(segment, normal),
        length=length,
    )


def _find_segment_pair_candidates(
    projected: list[_ProjectedSegment],
    *,
    patch_point: Point2D,
    radius: float,
    options: CenterlineCleanupOptions,
    max_width_to_length_ratio: float,
    max_pair_length: float | None,
) -> tuple[_SegmentPairCandidate, ...]:
    min_dot = math.cos(math.radians(options.angle_tolerance_degrees))
    pair_candidates: list[_SegmentPairCandidate] = []

    nearby = [
        segment
        for segment in projected
        if _distance_point_to_segment(patch_point, segment.segment.start, segment.segment.end) <= radius
    ]
    for left_index, left in enumerate(nearby):
        for right in nearby[left_index + 1 :]:
            if _dot(left.direction, right.direction) < min_dot:
                continue

            right_interval = _point_interval_on_direction(right.segment.start, right.segment.end, left.direction)
            start_t = max(left.interval[0], right_interval[0])
            end_t = min(left.interval[1], right_interval[1])
            overlap = end_t - start_t
            if overlap <= options.min_length:
                continue

            min_length = min(left.length, right.length)
            overlap_ratio = overlap / min_length
            if overlap_ratio < options.min_overlap_ratio:
                continue

            right_offset = _segment_offset_on_normal(right.segment, left.normal)
            width = abs(left.offset - right_offset)
            if width < options.min_pair_width:
                continue
            if width > min_length * max_width_to_length_ratio:
                continue
            if max_pair_length is not None and overlap > max_pair_length:
                continue

            preview = _centerline_from_pair_data(
                "preview",
                left,
                right,
                start_t,
                end_t,
                width,
                overlap,
                "preview",
            )
            distance_to_patch = _distance_point_to_segment(patch_point, preview.start, preview.end)
            if distance_to_patch > radius:
                continue

            score = (1.0 - overlap_ratio) + width / min_length
            pair_candidates.append(
                _SegmentPairCandidate(
                    left=left,
                    right=right,
                    start_t=start_t,
                    end_t=end_t,
                    width=width,
                    overlap=overlap,
                    score=score,
                    distance_to_patch=distance_to_patch,
                )
            )

    return tuple(sorted(pair_candidates, key=lambda pair: (pair.score, pair.distance_to_patch, pair.width)))


def _find_short_connector_candidates(
    centerlines: list[CenterlineCandidate],
    *,
    patch_point: Point2D,
    options: CenterlineCleanupOptions,
) -> list[_ShortPatchCandidate]:
    projected = [
        projection
        for index, candidate in enumerate(centerlines)
        if (projection := _project_candidate(index, candidate, options)) is not None
    ]
    min_dot = math.cos(math.radians(options.angle_tolerance_degrees))
    candidates: list[_ShortPatchCandidate] = []

    for left_index, left in enumerate(projected):
        for right in projected[left_index + 1 :]:
            if _dot(left.direction, right.direction) < min_dot:
                continue
            if not _width_matches(left.candidate.width, right.candidate.width, options):
                continue
            if _line_distance(left, right) > options.line_distance_tolerance:
                continue

            right_interval = _point_interval_on_direction(
                right.candidate.start,
                right.candidate.end,
                left.direction,
            )
            if left.interval[1] <= right_interval[0]:
                start_t = left.interval[1]
                end_t = right_interval[0]
            elif right_interval[1] <= left.interval[0]:
                start_t = right_interval[1]
                end_t = left.interval[0]
            else:
                continue

            gap = end_t - start_t
            if gap <= options.duplicate_centerline_tolerance:
                continue
            if gap > options.short_member_max_length:
                continue

            left_offset = _candidate_offset_on_normal(left.candidate, left.normal)
            right_offset = _candidate_offset_on_normal(right.candidate, left.normal)
            offset = (left_offset + right_offset) / 2.0
            connector = CenterlineCandidate(
                id="short_connector_patch",
                kind="short_member_connector_patch",
                start=_point_from_projection(left.direction, left.normal, start_t, offset),
                end=_point_from_projection(left.direction, left.normal, end_t, offset),
                source_segment_ids=(left.candidate.id, right.candidate.id),
                width=(left.candidate.width + right.candidate.width) / 2.0,
                overlap=gap,
                confidence=min(left.candidate.confidence, right.candidate.confidence, 0.7),
            )
            distance_to_patch = _distance_point_to_segment(
                patch_point,
                connector.start,
                connector.end,
            )
            if distance_to_patch > options.short_member_radius:
                continue

            candidates.append(
                _ShortPatchCandidate(
                    centerline=connector,
                    distance_to_patch=distance_to_patch,
                    score=distance_to_patch / options.short_member_radius + gap / options.short_member_max_length,
                )
            )

    return candidates


def _select_best_non_overlapping_pairs(
    pair_candidates: list[_SegmentPairCandidate],
    max_search_candidates: int,
) -> tuple[_SegmentPairCandidate, ...]:
    candidates = tuple(pair_candidates[:max_search_candidates])
    best: tuple[_SegmentPairCandidate, ...] = ()
    best_key = (0, float("inf"), float("inf"))

    def visit(
        index: int,
        used_source_ids: set[str],
        selected: list[_SegmentPairCandidate],
        score: float,
        distance: float,
    ) -> None:
        nonlocal best, best_key
        if index >= len(candidates):
            key = (len(selected), score, distance)
            if key[0] > best_key[0] or (
                key[0] == best_key[0] and (key[1], key[2]) < (best_key[1], best_key[2])
            ):
                best = tuple(selected)
                best_key = key
            return

        remaining = len(candidates) - index
        if len(selected) + remaining < best_key[0]:
            return

        pair = candidates[index]
        source_ids = {pair.left.segment.id, pair.right.segment.id}
        if not (used_source_ids & source_ids):
            selected.append(pair)
            used_source_ids.update(source_ids)
            visit(
                index + 1,
                used_source_ids,
                selected,
                score + pair.score,
                distance + pair.distance_to_patch,
            )
            selected.pop()
            used_source_ids.difference_update(source_ids)

        visit(index + 1, used_source_ids, selected, score, distance)

    visit(0, set(), [], 0.0, 0.0)
    return best


def _centerline_from_segment_pair(
    candidate_id: str,
    pair: _SegmentPairCandidate,
    kind: str,
) -> CenterlineCandidate:
    return _centerline_from_pair_data(
        candidate_id,
        pair.left,
        pair.right,
        pair.start_t,
        pair.end_t,
        pair.width,
        pair.overlap,
        kind,
    )


def _centerline_from_pair_data(
    candidate_id: str,
    left: _ProjectedSegment,
    right: _ProjectedSegment,
    start_t: float,
    end_t: float,
    width: float,
    overlap: float,
    kind: str,
) -> CenterlineCandidate:
    right_offset = _segment_offset_on_normal(right.segment, left.normal)
    center_offset = (left.offset + right_offset) / 2.0
    return CenterlineCandidate(
        id=candidate_id,
        kind=kind,
        start=_point_from_projection(left.direction, left.normal, start_t, center_offset),
        end=_point_from_projection(left.direction, left.normal, end_t, center_offset),
        source_segment_ids=(left.segment.id, right.segment.id),
        width=width,
        overlap=overlap,
        confidence=0.75,
    )


def _pair_orientation(pair: _SegmentPairCandidate) -> str:
    vector = _subtract(
        _point_from_projection(pair.left.direction, pair.left.normal, pair.end_t, pair.left.offset),
        _point_from_projection(pair.left.direction, pair.left.normal, pair.start_t, pair.left.offset),
    )
    return "V" if abs(vector[1]) > abs(vector[0]) else "H"


def _candidate_orientation(candidate: CenterlineCandidate) -> str:
    vector = _subtract(candidate.end, candidate.start)
    return "V" if abs(vector[1]) > abs(vector[0]) else "H"


def _segment_offset_on_normal(segment: DxfSegment2D, normal: Point2D) -> float:
    start_offset = _dot(segment.start, normal)
    end_offset = _dot(segment.end, normal)
    return (start_offset + end_offset) / 2.0


def merge_collinear_centerlines(
    centerlines: Iterable[CenterlineCandidate],
    options: CenterlineCleanupOptions | None = None,
) -> CenterlineCleanupResult:
    """Merge same-line centerline candidates whose projected intervals overlap."""
    opts = options or CenterlineCleanupOptions()
    candidates = tuple(centerlines)
    if len(candidates) < 2:
        return CenterlineCleanupResult(centerlines=candidates)

    projected = {
        projection.index: projection
        for index, candidate in enumerate(candidates)
        if (projection := _project_candidate(index, candidate, opts)) is not None
    }
    parents = list(range(len(candidates)))
    min_dot = math.cos(math.radians(opts.angle_tolerance_degrees))

    projected_items = list(projected.values())
    for left_index, left in enumerate(projected_items):
        for right in projected_items[left_index + 1 :]:
            if _can_merge(left, right, opts, min_dot):
                _union(parents, left.index, right.index)

    groups: dict[int, list[int]] = {}
    for index in range(len(candidates)):
        groups.setdefault(_find(parents, index), []).append(index)

    output: list[tuple[int, CenterlineCandidate]] = []
    merged_group_count = 0
    removed_candidate_count = 0
    for group in groups.values():
        group = sorted(group)
        mergeable_members = [projected[index] for index in group if index in projected]
        if len(group) > 1 and len(mergeable_members) > 1:
            output.append((group[0], _merge_group(mergeable_members)))
            merged_group_count += 1
            removed_candidate_count += len(group) - 1
        else:
            output.append((group[0], candidates[group[0]]))

    merged = tuple(candidate for _, candidate in sorted(output, key=lambda item: item[0]))
    if merged_group_count == 0:
        return CenterlineCleanupResult(centerlines=candidates)

    renumbered = _renumber_centerlines(merged)
    warnings = (
        WarningRecord(
            level="info",
            code="centerline_collinear_candidates_merged",
            message=(
                f"{merged_group_count} collinear overlapping centerline group(s) were merged; "
                f"{removed_candidate_count} redundant centerline candidate(s) were removed."
            ),
        ),
    )
    return CenterlineCleanupResult(
        centerlines=renumbered,
        merged_group_count=merged_group_count,
        removed_candidate_count=removed_candidate_count,
        warnings=warnings,
    )


def _can_merge(
    left: _ProjectedCandidate,
    right: _ProjectedCandidate,
    options: CenterlineCleanupOptions,
    min_dot: float,
) -> bool:
    if _dot(left.direction, right.direction) < min_dot:
        return False
    if not _width_matches(left.candidate.width, right.candidate.width, options):
        return False
    if _line_distance(left, right) > options.line_distance_tolerance:
        return False

    right_interval = _point_interval_on_direction(
        right.candidate.start,
        right.candidate.end,
        left.direction,
    )
    gap = max(left.interval[0], right_interval[0]) - min(left.interval[1], right_interval[1])
    return gap <= options.overlap_gap_tolerance


def _merge_group(group: list[_ProjectedCandidate]) -> CenterlineCandidate:
    reference = max(group, key=lambda item: item.length)
    direction = reference.direction
    normal = reference.normal
    intervals = [
        _point_interval_on_direction(item.candidate.start, item.candidate.end, direction)
        for item in group
    ]
    start_t = min(interval[0] for interval in intervals)
    end_t = max(interval[1] for interval in intervals)
    offset = _candidate_offset_on_normal(reference.candidate, normal)
    source = reference.candidate
    total_length = sum(item.length for item in group)
    width = sum(item.candidate.width * item.length for item in group) / total_length
    confidence = min(item.candidate.confidence for item in group)

    return CenterlineCandidate(
        id=source.id,
        kind="merged_collinear_centerline",
        start=_point_from_projection(direction, normal, start_t, offset),
        end=_point_from_projection(direction, normal, end_t, offset),
        source_segment_ids=source.source_segment_ids,
        width=width,
        overlap=end_t - start_t,
        confidence=confidence,
    )


def _project_candidate(
    index: int,
    candidate: CenterlineCandidate,
    options: CenterlineCleanupOptions,
) -> _ProjectedCandidate | None:
    vector = _subtract(candidate.end, candidate.start)
    length = math.hypot(vector[0], vector[1])
    if length < options.min_length:
        return None

    direction = (vector[0] / length, vector[1] / length)
    if direction[0] < -1e-12 or (abs(direction[0]) <= 1e-12 and direction[1] < 0):
        direction = (-direction[0], -direction[1])
    normal = (-direction[1], direction[0])

    return _ProjectedCandidate(
        index=index,
        candidate=candidate,
        direction=direction,
        normal=normal,
        interval=_point_interval_on_direction(candidate.start, candidate.end, direction),
        length=length,
    )


def _line_distance(left: _ProjectedCandidate, right: _ProjectedCandidate) -> float:
    return max(
        _distance_point_to_infinite_line(right.candidate.start, left.candidate.start, left.candidate.end),
        _distance_point_to_infinite_line(right.candidate.end, left.candidate.start, left.candidate.end),
        _distance_point_to_infinite_line(left.candidate.start, right.candidate.start, right.candidate.end),
        _distance_point_to_infinite_line(left.candidate.end, right.candidate.start, right.candidate.end),
    )


def _width_matches(
    left_width: float,
    right_width: float,
    options: CenterlineCleanupOptions,
) -> bool:
    reference = max(abs(left_width), abs(right_width), 1.0)
    return abs(left_width - right_width) <= max(
        options.width_tolerance,
        reference * options.width_tolerance_ratio,
    )


def _renumber_centerlines(
    centerlines: tuple[CenterlineCandidate, ...],
) -> tuple[CenterlineCandidate, ...]:
    return tuple(
        CenterlineCandidate(
            id=f"C{index}",
            kind=candidate.kind,
            start=candidate.start,
            end=candidate.end,
            source_segment_ids=candidate.source_segment_ids,
            width=candidate.width,
            overlap=candidate.overlap,
            confidence=candidate.confidence,
        )
        for index, candidate in enumerate(centerlines, start=1)
    )


def _replace_centerline_id(
    candidate: CenterlineCandidate,
    candidate_id: str,
) -> CenterlineCandidate:
    return CenterlineCandidate(
        id=candidate_id,
        kind=candidate.kind,
        start=candidate.start,
        end=candidate.end,
        source_segment_ids=candidate.source_segment_ids,
        width=candidate.width,
        overlap=candidate.overlap,
        confidence=candidate.confidence,
    )


def _candidate_offset_on_normal(candidate: CenterlineCandidate, normal: Point2D) -> float:
    start_offset = _dot(candidate.start, normal)
    end_offset = _dot(candidate.end, normal)
    return (start_offset + end_offset) / 2.0


def _point_interval_on_direction(
    start: Point2D,
    end: Point2D,
    direction: Point2D,
) -> tuple[float, float]:
    start_t = _dot(start, direction)
    end_t = _dot(end, direction)
    return (min(start_t, end_t), max(start_t, end_t))


def _point_from_projection(direction: Point2D, normal: Point2D, t_value: float, offset: float) -> Point2D:
    return (
        direction[0] * t_value + normal[0] * offset,
        direction[1] * t_value + normal[1] * offset,
    )


def _distance_point_to_infinite_line(point: Point2D, line_start: Point2D, line_end: Point2D) -> float:
    line = _subtract(line_end, line_start)
    length = math.hypot(line[0], line[1])
    if length <= 1e-12:
        return math.hypot(point[0] - line_start[0], point[1] - line_start[1])
    return abs(_cross(_subtract(point, line_start), line)) / length


def _distance_point_to_segment(point: Point2D, start: Point2D, end: Point2D) -> float:
    segment = _subtract(end, start)
    length_squared = _dot(segment, segment)
    if length_squared <= 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])

    t_value = _dot(_subtract(point, start), segment) / length_squared
    clamped_t = min(max(t_value, 0.0), 1.0)
    closest = (
        start[0] + (end[0] - start[0]) * clamped_t,
        start[1] + (end[1] - start[1]) * clamped_t,
    )
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _is_duplicate_centerline(
    existing: CenterlineCandidate,
    candidate: CenterlineCandidate,
    tolerance: float,
) -> bool:
    if tolerance <= 0:
        return False

    existing_vector = _subtract(existing.end, existing.start)
    candidate_vector = _subtract(candidate.end, candidate.start)
    existing_length = math.hypot(existing_vector[0], existing_vector[1])
    candidate_length = math.hypot(candidate_vector[0], candidate_vector[1])
    if existing_length <= tolerance or candidate_length <= tolerance:
        return False

    existing_direction = (existing_vector[0] / existing_length, existing_vector[1] / existing_length)
    candidate_direction = (candidate_vector[0] / candidate_length, candidate_vector[1] / candidate_length)
    if abs(_cross(existing_direction, candidate_direction)) > 1e-6:
        return False
    if _distance_point_to_infinite_line(candidate.start, existing.start, existing.end) > tolerance:
        return False
    if _distance_point_to_infinite_line(candidate.end, existing.start, existing.end) > tolerance:
        return False

    existing_interval = _point_interval_on_direction(existing.start, existing.end, existing_direction)
    candidate_interval = _point_interval_on_direction(candidate.start, candidate.end, existing_direction)
    overlap = min(existing_interval[1], candidate_interval[1]) - max(existing_interval[0], candidate_interval[0])
    return overlap >= min(existing_length, candidate_length) - tolerance


def _find(parents: list[int], index: int) -> int:
    while parents[index] != index:
        parents[index] = parents[parents[index]]
        index = parents[index]
    return index


def _union(parents: list[int], left: int, right: int) -> None:
    left_root = _find(parents, left)
    right_root = _find(parents, right)
    if left_root != right_root:
        parents[right_root] = left_root


def _subtract(left: Point2D, right: Point2D) -> Point2D:
    return (left[0] - right[0], left[1] - right[1])


def _dot(left: Point2D, right: Point2D) -> float:
    return left[0] * right[0] + left[1] * right[1]


def _cross(left: Point2D, right: Point2D) -> float:
    return left[0] * right[1] - left[1] * right[0]
