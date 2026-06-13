"""Single-face centerline extraction from preprocessed DXF outlines."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ehouse_model.dxf_reader import DxfSegment2D, Point2D, read_dxf_segments, write_overlay_dxf
from ehouse_model.exporters import export_warnings_csv
from ehouse_model.face_model import (
    CenterlineCandidate,
    FaceModel,
    WarningRecord,
    write_face_model_json,
)
from ehouse_model.face_topology import build_face_topology

DIRECTION_ZERO_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class FaceExtractionOptions:
    angle_tolerance_degrees: float = 2.0
    min_segment_length: float = 1e-6
    min_pair_width: float = 5.0
    max_pair_width: float | None = None
    max_pair_width_to_length_ratio: float = 0.35
    min_overlap_ratio: float = 0.75
    duplicate_centerline_tolerance: float = 1.0
    node_merge_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if self.angle_tolerance_degrees <= 0:
            raise ValueError("angle_tolerance_degrees must be positive")
        if self.min_segment_length <= 0:
            raise ValueError("min_segment_length must be positive")
        if self.min_pair_width <= 0:
            raise ValueError("min_pair_width must be positive")
        if self.max_pair_width is not None and self.max_pair_width <= 0:
            raise ValueError("max_pair_width must be positive when provided")
        if self.max_pair_width_to_length_ratio <= 0:
            raise ValueError("max_pair_width_to_length_ratio must be positive")
        if not 0 < self.min_overlap_ratio <= 1:
            raise ValueError("min_overlap_ratio must be between 0 and 1")
        if self.duplicate_centerline_tolerance < 0:
            raise ValueError("duplicate_centerline_tolerance cannot be negative")
        if self.node_merge_tolerance <= 0:
            raise ValueError("node_merge_tolerance must be positive")


@dataclass(frozen=True, slots=True)
class _ProjectedSegment:
    index: int
    segment: DxfSegment2D
    direction: Point2D
    normal: Point2D
    length: float
    interval: tuple[float, float]
    offset: float


@dataclass(frozen=True, slots=True)
class _PairCandidate:
    left: _ProjectedSegment
    right: _ProjectedSegment
    start_t: float
    end_t: float
    width: float
    overlap: float
    score: float


def extract_face(
    dxf_path: str | Path,
    face_model_path: str | Path = "face_model.json",
    overlay_path: str | Path = "centerline_overlay.dxf",
    warnings_csv_path: str | Path | None = "warnings.csv",
    options: FaceExtractionOptions | None = None,
) -> FaceModel:
    """Extract centerline candidates from one preprocessed face DXF."""
    opts = options or FaceExtractionOptions()
    source_path = Path(dxf_path)
    segments = read_dxf_segments(source_path)
    candidates, extraction_warnings = extract_centerline_candidates(segments, opts)
    topology = build_face_topology(candidates, opts.node_merge_tolerance)
    warnings = _renumber_warnings([*extraction_warnings, *topology.warnings])

    model = FaceModel(
        source_dxf=str(source_path),
        nodes=topology.nodes,
        members=topology.members,
        centerline_candidates=tuple(candidates),
        member_sources=topology.member_sources,
        warnings=warnings,
    )

    write_face_model_json(model, face_model_path)
    if warnings_csv_path is not None:
        export_warnings_csv(model.warnings, warnings_csv_path)
    write_overlay_dxf(
        overlay_path,
        outline_segments=segments,
        centerline_segments=[(candidate.start, candidate.end) for candidate in candidates],
    )
    return model


def extract_centerline_candidates(
    segments: Iterable[DxfSegment2D],
    options: FaceExtractionOptions | None = None,
) -> tuple[list[CenterlineCandidate], list[WarningRecord]]:
    """Pair parallel outline edges and return centerline candidates."""
    opts = options or FaceExtractionOptions()
    projected = [
        projection
        for index, segment in enumerate(segments)
        if (projection := _project_segment(index, segment, opts)) is not None
    ]
    warnings: list[WarningRecord] = []

    if not projected:
        return [], [
            WarningRecord(
                code="no_dxf_segments",
                message="No LINE or LWPOLYLINE segments were found.",
            )
        ]

    pair_candidates = _find_pair_candidates(projected, opts)
    selected_pairs = _select_non_overlapping_pairs(pair_candidates, opts.min_segment_length)
    raw_candidates = [
        _centerline_from_pair(index, pair)
        for index, pair in enumerate(selected_pairs, start=1)
    ]
    candidates = _renumber_centerline_candidates(
        _dedupe_centerline_candidates(raw_candidates, opts.duplicate_centerline_tolerance)
    )

    if not candidates:
        warnings.append(
            WarningRecord(
                code="no_centerline_candidates",
                message="No parallel outline pairs produced centerline candidates.",
            )
        )

    return candidates, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract one face_model.json from a DXF face.")
    parser.add_argument("dxf_path", help="Input preprocessed DXF file.")
    parser.add_argument("--face-model", default="face_model.json", help="Output face_model.json path.")
    parser.add_argument("--overlay", default="centerline_overlay.dxf", help="Output overlay DXF path.")
    parser.add_argument("--warnings", default="warnings.csv", help="Output warnings.csv path.")
    parser.add_argument("--max-pair-width", type=float, default=None)
    parser.add_argument("--angle-tolerance", type=float, default=2.0)
    args = parser.parse_args(argv)

    options = FaceExtractionOptions(
        angle_tolerance_degrees=args.angle_tolerance,
        max_pair_width=args.max_pair_width,
    )
    extract_face(
        args.dxf_path,
        face_model_path=args.face_model,
        overlay_path=args.overlay,
        warnings_csv_path=args.warnings,
        options=options,
    )
    return 0


def _find_pair_candidates(
    projected: list[_ProjectedSegment],
    options: FaceExtractionOptions,
) -> list[_PairCandidate]:
    pair_candidates: list[_PairCandidate] = []
    min_dot = math.cos(math.radians(options.angle_tolerance_degrees))

    for left_index, left in enumerate(projected):
        for right in projected[left_index + 1 :]:
            if _dot(left.direction, right.direction) < min_dot:
                continue

            right_interval = _interval_on_direction(right.segment, left.direction)
            start_t = max(left.interval[0], right_interval[0])
            end_t = min(left.interval[1], right_interval[1])
            overlap = end_t - start_t
            if overlap <= options.min_segment_length:
                continue

            min_length = min(left.length, right.length)
            overlap_ratio = overlap / min_length
            if overlap_ratio < options.min_overlap_ratio:
                continue

            right_offset = _offset_on_normal(right.segment, left.normal)
            width = abs(left.offset - right_offset)
            if width < options.min_pair_width:
                continue

            max_width = options.max_pair_width
            if max_width is None:
                max_width = min_length * options.max_pair_width_to_length_ratio
            if width > max_width:
                continue

            score = (1.0 - overlap_ratio) + width / min_length
            pair_candidates.append(
                _PairCandidate(
                    left=left,
                    right=right,
                    start_t=start_t,
                    end_t=end_t,
                    width=width,
                    overlap=overlap,
                    score=score,
                )
            )

    return sorted(pair_candidates, key=lambda pair: (pair.score, pair.width, pair.left.index, pair.right.index))


def _select_non_overlapping_pairs(
    pair_candidates: list[_PairCandidate],
    tolerance: float,
) -> list[_PairCandidate]:
    selected: list[_PairCandidate] = []
    used_intervals_by_segment: dict[int, list[tuple[float, float]]] = {}

    for pair in pair_candidates:
        left_interval = _used_interval_for_segment(pair, pair.left)
        right_interval = _used_interval_for_segment(pair, pair.right)
        if _interval_overlaps_existing(
            used_intervals_by_segment.get(pair.left.index, []),
            left_interval,
            tolerance,
        ):
            continue
        if _interval_overlaps_existing(
            used_intervals_by_segment.get(pair.right.index, []),
            right_interval,
            tolerance,
        ):
            continue

        selected.append(pair)
        used_intervals_by_segment.setdefault(pair.left.index, []).append(left_interval)
        used_intervals_by_segment.setdefault(pair.right.index, []).append(right_interval)

    return sorted(selected, key=lambda pair: (pair.left.index, pair.right.index))


def _used_interval_for_segment(
    pair: _PairCandidate,
    segment: _ProjectedSegment,
) -> tuple[float, float]:
    if segment is pair.left:
        start_t = pair.start_t
        end_t = pair.end_t
    else:
        right_offset = _offset_on_normal(pair.right.segment, pair.left.normal)
        start_point = _point_from_projection(
            pair.left.direction,
            pair.left.normal,
            pair.start_t,
            right_offset,
        )
        end_point = _point_from_projection(
            pair.left.direction,
            pair.left.normal,
            pair.end_t,
            right_offset,
        )
        start_t = _dot(start_point, segment.direction)
        end_t = _dot(end_point, segment.direction)
    return (min(start_t, end_t), max(start_t, end_t))


def _interval_overlaps_existing(
    existing_intervals: list[tuple[float, float]],
    new_interval: tuple[float, float],
    tolerance: float,
) -> bool:
    new_start, new_end = new_interval
    for used_start, used_end in existing_intervals:
        if min(new_end, used_end) - max(new_start, used_start) > tolerance:
            return True
    return False


def _centerline_from_pair(index: int, pair: _PairCandidate) -> CenterlineCandidate:
    right_offset = _offset_on_normal(pair.right.segment, pair.left.normal)
    center_offset = (pair.left.offset + right_offset) / 2.0
    start = _point_from_projection(pair.left.direction, pair.left.normal, pair.start_t, center_offset)
    end = _point_from_projection(pair.left.direction, pair.left.normal, pair.end_t, center_offset)
    return CenterlineCandidate(
        id=f"C{index}",
        start=start,
        end=end,
        source_segment_ids=(pair.left.segment.id, pair.right.segment.id),
        width=pair.width,
        overlap=pair.overlap,
    )


def _dedupe_centerline_candidates(
    candidates: list[CenterlineCandidate],
    tolerance: float,
) -> list[CenterlineCandidate]:
    if tolerance <= 0:
        return candidates

    result: list[CenterlineCandidate] = []
    for candidate in candidates:
        if any(_is_duplicate_centerline(existing, candidate, tolerance) for existing in result):
            continue
        result.append(candidate)
    return result


def _is_duplicate_centerline(
    existing: CenterlineCandidate,
    candidate: CenterlineCandidate,
    tolerance: float,
) -> bool:
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


def _renumber_centerline_candidates(
    candidates: list[CenterlineCandidate],
) -> list[CenterlineCandidate]:
    return [
        CenterlineCandidate(
            id=f"C{index}",
            start=candidate.start,
            end=candidate.end,
            source_segment_ids=candidate.source_segment_ids,
            width=candidate.width,
            overlap=candidate.overlap,
            kind=candidate.kind,
            confidence=candidate.confidence,
        )
        for index, candidate in enumerate(candidates, start=1)
    ]


def _project_segment(
    index: int,
    segment: DxfSegment2D,
    options: FaceExtractionOptions,
) -> _ProjectedSegment | None:
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    length = math.hypot(dx, dy)
    if length < options.min_segment_length:
        return None

    direction = (dx / length, dy / length)
    if direction[0] < -DIRECTION_ZERO_TOLERANCE or (
        abs(direction[0]) <= DIRECTION_ZERO_TOLERANCE and direction[1] < 0
    ):
        direction = (-direction[0], -direction[1])

    normal = (-direction[1], direction[0])
    return _ProjectedSegment(
        index=index,
        segment=segment,
        direction=direction,
        normal=normal,
        length=length,
        interval=_interval_on_direction(segment, direction),
        offset=_offset_on_normal(segment, normal),
    )


def _interval_on_direction(segment: DxfSegment2D, direction: Point2D) -> tuple[float, float]:
    start_t = _dot(segment.start, direction)
    end_t = _dot(segment.end, direction)
    return (min(start_t, end_t), max(start_t, end_t))


def _offset_on_normal(segment: DxfSegment2D, normal: Point2D) -> float:
    start_offset = _dot(segment.start, normal)
    end_offset = _dot(segment.end, normal)
    return (start_offset + end_offset) / 2.0


def _point_from_projection(direction: Point2D, normal: Point2D, t_value: float, offset: float) -> Point2D:
    return (
        direction[0] * t_value + normal[0] * offset,
        direction[1] * t_value + normal[1] * offset,
    )


def _point_interval_on_direction(
    start: Point2D,
    end: Point2D,
    direction: Point2D,
) -> tuple[float, float]:
    start_t = _dot(start, direction)
    end_t = _dot(end, direction)
    return (min(start_t, end_t), max(start_t, end_t))


def _distance_point_to_infinite_line(point: Point2D, line_start: Point2D, line_end: Point2D) -> float:
    line = _subtract(line_end, line_start)
    length = math.hypot(line[0], line[1])
    if length <= 1e-12:
        return math.hypot(point[0] - line_start[0], point[1] - line_start[1])
    return abs(_cross(_subtract(point, line_start), line)) / length


def _renumber_warnings(warnings: list[WarningRecord]) -> tuple[WarningRecord, ...]:
    return tuple(
        warning.with_id(f"W{index}")
        for index, warning in enumerate(warnings, start=1)
    )


def _dot(left: Point2D, right: Point2D) -> float:
    return left[0] * right[0] + left[1] * right[1]


def _subtract(left: Point2D, right: Point2D) -> Point2D:
    return (left[0] - right[0], left[1] - right[1])


def _cross(left: Point2D, right: Point2D) -> float:
    return left[0] * right[1] - left[1] * right[0]


if __name__ == "__main__":
    raise SystemExit(main())
