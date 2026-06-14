"""Standalone DXF preprocessing for drawings that need cleanup before extraction."""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import ezdxf

from ehouse_model.dxf_reader import DxfSegment2D, Point2D


@dataclass(frozen=True, slots=True)
class PreprocessOptions:
    """Options for conservative drawing cleanup.

    The defaults are tuned for the T1161 style drawings: keep the main outline
    layer, discard centerline/dashed/detail layers, and only merge clearly
    collinear outline fragments.
    """

    keep_layers: tuple[str, ...] = ("0",)
    remove_layer_keywords: tuple[str, ...] = ("中心线", "虚线", "细线")
    angle_tolerance_degrees: float = 2.0
    merge_tolerance: float = 1.0
    gap_tolerance: float = 5.0
    min_segment_length: float = 1e-6
    cross_cleanup_enabled: bool = True
    closure_max_length: float = 300.0
    closure_length_to_width_ratio: float = 1.5
    outline_min_length_to_width_ratio: float = 3.0
    cross_tolerance: float = 5.0
    overlap_trim_enabled: bool = True
    overlap_trim_tolerance: float = 5.0
    overlap_trim_min_band_length: float = 300.0
    overlap_trim_min_remainder: float = 20.0
    overlap_trim_tie_breaker: str = "keep_horizontal"

    def __post_init__(self) -> None:
        if self.angle_tolerance_degrees <= 0:
            raise ValueError("angle_tolerance_degrees must be positive")
        if self.merge_tolerance < 0:
            raise ValueError("merge_tolerance cannot be negative")
        if self.gap_tolerance < 0:
            raise ValueError("gap_tolerance cannot be negative")
        if self.min_segment_length <= 0:
            raise ValueError("min_segment_length must be positive")
        if self.closure_max_length <= 0:
            raise ValueError("closure_max_length must be positive")
        if self.closure_length_to_width_ratio <= 0:
            raise ValueError("closure_length_to_width_ratio must be positive")
        if self.outline_min_length_to_width_ratio <= 0:
            raise ValueError("outline_min_length_to_width_ratio must be positive")
        if self.cross_tolerance < 0:
            raise ValueError("cross_tolerance cannot be negative")
        if self.overlap_trim_tolerance < 0:
            raise ValueError("overlap_trim_tolerance cannot be negative")
        if self.overlap_trim_min_band_length <= 0:
            raise ValueError("overlap_trim_min_band_length must be positive")
        if self.overlap_trim_min_remainder < 0:
            raise ValueError("overlap_trim_min_remainder cannot be negative")
        if self.overlap_trim_tie_breaker not in {"keep_horizontal", "keep_vertical"}:
            raise ValueError("overlap_trim_tie_breaker must be keep_horizontal or keep_vertical")


@dataclass(frozen=True, slots=True)
class PreprocessReportRecord:
    """One source-entity decision written to the preprocess report."""

    source_id: str
    entity_type: str
    layer: str
    status: str
    reason: str
    output_id: str = ""
    start: Point2D | None = None
    end: Point2D | None = None


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    input_path: Path
    clean_dxf_path: Path
    overlay_dxf_path: Path
    report_csv_path: Path
    original_entity_count: int
    original_segment_count: int
    non_line_entity_count: int
    kept_segment_count: int
    removed_segment_count: int
    output_segment_count: int
    merged_group_count: int
    cross_removed_segment_count: int
    overlap_trimmed_segment_count: int
    clean_segments: tuple[DxfSegment2D, ...]
    removed_segments: tuple[DxfSegment2D, ...]
    cross_removed_segments: tuple[DxfSegment2D, ...]
    overlap_trimmed_segments: tuple[DxfSegment2D, ...]
    report_records: tuple[PreprocessReportRecord, ...]


@dataclass(frozen=True, slots=True)
class LayerStat:
    layer: str
    entity_count: int
    segment_count: int
    entity_types: tuple[str, ...]
    colors: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PreprocessPreview:
    name: str
    output_segments: tuple[DxfSegment2D, ...]
    removed_segments: tuple[DxfSegment2D, ...] = ()
    trimmed_segments: tuple[DxfSegment2D, ...] = ()
    report_records: tuple[PreprocessReportRecord, ...] = ()
    summary: str = ""


@dataclass(slots=True)
class DxfPreprocessModel:
    input_path: Path
    original_segments: tuple[DxfSegment2D, ...]
    current_segments: tuple[DxfSegment2D, ...]
    layer_stats: tuple[LayerStat, ...]
    non_line_records: tuple[PreprocessReportRecord, ...]
    original_entity_count: int
    applied_records: list[PreprocessReportRecord]
    history: list[tuple[tuple[DxfSegment2D, ...], tuple[PreprocessReportRecord, ...]]]

    @classmethod
    def load(cls, input_path: str | Path) -> DxfPreprocessModel:
        source_path = Path(input_path)
        doc = ezdxf.readfile(source_path)
        raw_segments, non_line_records, original_entity_count = _read_source_geometry(doc)
        layer_stats = _collect_layer_stats(doc, raw_segments)
        segments = tuple(raw_segments)
        return cls(
            input_path=source_path,
            original_segments=segments,
            current_segments=segments,
            layer_stats=layer_stats,
            non_line_records=tuple(non_line_records),
            original_entity_count=original_entity_count,
            applied_records=[],
            history=[],
        )

    @property
    def current_segment_count(self) -> int:
        return len(self.current_segments)

    @property
    def removed_segment_count(self) -> int:
        return len(self.original_segments) - len(self.current_segments)

    @property
    def non_line_entity_count(self) -> int:
        return len(self.non_line_records)

    @property
    def non_line_type_summary(self) -> str:
        counts = Counter(record.entity_type for record in self.non_line_records)
        return ", ".join(
            f"{entity_type}:{count}"
            for entity_type, count in sorted(counts.items())
        )

    def preview_layer_extract(self, keep_layers: Iterable[str]) -> PreprocessPreview:
        keep = set(keep_layers)
        output = tuple(segment for segment in self.current_segments if segment.layer in keep)
        removed = tuple(segment for segment in self.current_segments if segment.layer not in keep)
        records = tuple(
            PreprocessReportRecord(
                source_id=segment.id,
                entity_type=segment.entity_type,
                layer=segment.layer,
                status="removed",
                reason="removed_layer_not_selected",
                start=segment.start,
                end=segment.end,
            )
            for segment in removed
        )
        return PreprocessPreview(
            name="图层提取",
            output_segments=output,
            removed_segments=removed,
            report_records=records,
            summary=f"图层提取预览：保留 {len(output)} 条线，候选删除 {len(removed)} 条线。",
        )

    def preview_keep_axis_aligned(self, *, angle_tolerance_degrees: float = 2.0) -> PreprocessPreview:
        options = PreprocessOptions(
            keep_layers=(),
            remove_layer_keywords=(),
            angle_tolerance_degrees=angle_tolerance_degrees,
            cross_cleanup_enabled=False,
            overlap_trim_enabled=False,
        )
        kept: list[DxfSegment2D] = []
        removed: list[DxfSegment2D] = []
        records: list[PreprocessReportRecord] = []
        for segment in self.current_segments:
            axis_segment, removal_reason = _classify_segment(segment, options)
            if axis_segment is None:
                removed.append(segment)
                records.append(
                    PreprocessReportRecord(
                        source_id=segment.id,
                        entity_type=segment.entity_type,
                        layer=segment.layer,
                        status="removed",
                        reason=removal_reason,
                        start=segment.start,
                        end=segment.end,
                    )
                )
            else:
                kept.append(segment)
        return PreprocessPreview(
            name="仅保留水平/竖直线",
            output_segments=tuple(kept),
            removed_segments=tuple(removed),
            report_records=tuple(records),
            summary=f"轴线过滤预览：保留 {len(kept)} 条线，候选删除 {len(removed)} 条斜线/短线。",
        )

    def preview_merge_collinear(
        self,
        *,
        merge_tolerance: float = 1.0,
        gap_tolerance: float = 5.0,
        angle_tolerance_degrees: float = 2.0,
    ) -> PreprocessPreview:
        options = PreprocessOptions(
            keep_layers=(),
            remove_layer_keywords=(),
            angle_tolerance_degrees=angle_tolerance_degrees,
            merge_tolerance=merge_tolerance,
            gap_tolerance=gap_tolerance,
            cross_cleanup_enabled=False,
            overlap_trim_enabled=False,
        )
        axis_segments: list[_AxisSegment] = []
        passthrough: list[DxfSegment2D] = []
        for segment in self.current_segments:
            axis_segment = _clean_segment_to_axis_segment(segment, options)
            if axis_segment is None:
                passthrough.append(segment)
            else:
                axis_segments.append(axis_segment)

        merged_segments, merge_records, _ = _merge_axis_segments(axis_segments, options)
        merged_source_ids = {
            record.source_id
            for record in merge_records
            if record.status == "merged"
        }
        removed = tuple(segment for segment in self.current_segments if segment.id in merged_source_ids)
        action_records = tuple(record for record in merge_records if record.status == "merged")
        output = tuple([*merged_segments, *passthrough])
        return PreprocessPreview(
            name="合并重叠/断裂线",
            output_segments=output,
            removed_segments=removed,
            report_records=action_records,
            summary=(
                f"合并预览：当前 {len(self.current_segments)} 条线，"
                f"合并后 {len(output)} 条线，涉及 {len(removed)} 条源线。"
            ),
        )

    def preview_cross_cleanup(self, options: PreprocessOptions | None = None) -> PreprocessPreview:
        opts = options or PreprocessOptions(overlap_trim_enabled=False)
        result = _cleanup_cross_closure_segments(self.current_segments, opts)
        records = tuple(record for record in result.records if record.status == "removed")
        return PreprocessPreview(
            name="删除交叉封口短线",
            output_segments=result.clean_segments,
            removed_segments=result.removed_segments,
            report_records=records,
            summary=f"交叉封口预览：候选删除 {len(result.removed_segments)} 条短线。",
        )

    def preview_overlap_trim(self, options: PreprocessOptions | None = None) -> PreprocessPreview:
        opts = options or PreprocessOptions(cross_cleanup_enabled=False)
        result = _trim_overlapping_member_bands(self.current_segments, opts)
        return PreprocessPreview(
            name="相交构件让位裁剪",
            output_segments=result.clean_segments,
            trimmed_segments=result.trimmed_segments,
            report_records=result.records,
            summary=f"让位裁剪预览：候选裁剪 {len(result.trimmed_segments)} 段。",
        )

    def apply_preview(self, preview: PreprocessPreview) -> None:
        self.history.append((self.current_segments, tuple(self.applied_records)))
        self.current_segments = preview.output_segments
        self.applied_records.extend(preview.report_records)

    def undo(self) -> bool:
        if not self.history:
            return False
        self.current_segments, records = self.history.pop()
        self.applied_records = list(records)
        return True

    def reset(self) -> None:
        self.current_segments = self.original_segments
        self.applied_records.clear()
        self.history.clear()

    def save_clean_dxf(self, path: str | Path) -> None:
        _write_clean_dxf(Path(path), self.current_segments)

    def save_overlay_dxf(self, path: str | Path, preview: PreprocessPreview | None = None) -> None:
        write_preprocess_workspace_overlay(
            path,
            original_segments=self.original_segments,
            current_segments=self.current_segments,
            preview=preview,
        )

    def save_report_csv(self, path: str | Path) -> None:
        _write_report_csv(Path(path), [*self.non_line_records, *self.applied_records])


@dataclass(frozen=True, slots=True)
class _AxisSegment:
    source: DxfSegment2D
    axis: str
    coord: float
    interval: tuple[float, float]
    layer: str

    @property
    def length(self) -> float:
        return self.interval[1] - self.interval[0]


@dataclass(frozen=True, slots=True)
class _CrossCleanupResult:
    clean_segments: tuple[DxfSegment2D, ...]
    removed_segments: tuple[DxfSegment2D, ...]
    records: tuple[PreprocessReportRecord, ...]


@dataclass(frozen=True, slots=True)
class _MemberBand:
    id: str
    axis: str
    first: _AxisSegment
    second: _AxisSegment
    coord_range: tuple[float, float]
    interval: tuple[float, float]
    width: float

    @property
    def length(self) -> float:
        return self.interval[1] - self.interval[0]


@dataclass(frozen=True, slots=True)
class _OverlapTrimResult:
    clean_segments: tuple[DxfSegment2D, ...]
    trimmed_segments: tuple[DxfSegment2D, ...]
    records: tuple[PreprocessReportRecord, ...]


def preprocess_dxf(
    input_path: str | Path,
    output_path: str | Path | None = None,
    options: PreprocessOptions | None = None,
    *,
    overlay_path: str | Path | None = None,
    report_csv_path: str | Path | None = None,
) -> PreprocessResult:
    """Clean one DXF into a conservative LINE-only drawing for later inspection."""
    opts = options or PreprocessOptions()
    source_path = Path(input_path)
    clean_path = Path(output_path) if output_path is not None else _default_clean_path(source_path)
    overlay_output_path = (
        Path(overlay_path)
        if overlay_path is not None
        else source_path.with_name(f"{source_path.stem}_preprocess_overlay.dxf")
    )
    report_path = (
        Path(report_csv_path)
        if report_csv_path is not None
        else source_path.with_name(f"{source_path.stem}_preprocess_report.csv")
    )

    doc = ezdxf.readfile(source_path)
    raw_segments, non_line_records, original_entity_count = _read_source_geometry(doc)
    axis_segments: list[_AxisSegment] = []
    removed_segments: list[DxfSegment2D] = []
    report_records: list[PreprocessReportRecord] = [*non_line_records]

    for segment in raw_segments:
        axis_segment, removal_reason = _classify_segment(segment, opts)
        if axis_segment is None:
            removed_segments.append(segment)
            report_records.append(
                PreprocessReportRecord(
                    source_id=segment.id,
                    entity_type=segment.entity_type,
                    layer=segment.layer,
                    status="removed",
                    reason=removal_reason,
                    start=segment.start,
                    end=segment.end,
                )
            )
            continue
        axis_segments.append(axis_segment)

    clean_segments, merge_records, merged_group_count = _merge_axis_segments(axis_segments, opts)
    report_records.extend(merge_records)
    cross_cleanup_result = _cleanup_cross_closure_segments(clean_segments, opts)
    clean_segments = list(cross_cleanup_result.clean_segments)
    cross_removed_segments = list(cross_cleanup_result.removed_segments)
    report_records.extend(cross_cleanup_result.records)
    overlap_trim_result = _trim_overlapping_member_bands(clean_segments, opts)
    clean_segments = list(overlap_trim_result.clean_segments)
    overlap_trimmed_segments = list(overlap_trim_result.trimmed_segments)
    report_records.extend(overlap_trim_result.records)

    _write_clean_dxf(clean_path, clean_segments)
    _write_preprocess_overlay(
        overlay_output_path,
        clean_segments,
        removed_segments,
        cross_removed_segments,
        overlap_trimmed_segments,
    )
    _write_report_csv(report_path, report_records)

    return PreprocessResult(
        input_path=source_path,
        clean_dxf_path=clean_path,
        overlay_dxf_path=overlay_output_path,
        report_csv_path=report_path,
        original_entity_count=original_entity_count,
        original_segment_count=len(raw_segments),
        non_line_entity_count=len(non_line_records),
        kept_segment_count=len(axis_segments),
        removed_segment_count=len(removed_segments) + len(cross_removed_segments) + len(overlap_trimmed_segments),
        output_segment_count=len(clean_segments),
        merged_group_count=merged_group_count,
        cross_removed_segment_count=len(cross_removed_segments),
        overlap_trimmed_segment_count=len(overlap_trimmed_segments),
        clean_segments=tuple(clean_segments),
        removed_segments=tuple([*removed_segments, *cross_removed_segments, *overlap_trimmed_segments]),
        cross_removed_segments=tuple(cross_removed_segments),
        overlap_trimmed_segments=tuple(overlap_trimmed_segments),
        report_records=tuple(report_records),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preprocess a DXF into a cleaner LINE-only DXF.")
    parser.add_argument("dxf_path", help="Input DXF path.")
    parser.add_argument("--output", help="Output clean DXF path.")
    parser.add_argument("--overlay", help="Output preprocess overlay DXF path.")
    parser.add_argument("--report", help="Output preprocess report CSV path.")
    parser.add_argument(
        "--keep-layer",
        action="append",
        dest="keep_layers",
        help="Layer to keep. Repeat for multiple layers. Defaults to layer 0.",
    )
    parser.add_argument(
        "--remove-layer-keyword",
        action="append",
        dest="remove_layer_keywords",
        help="Layer-name keyword to remove. Repeat for multiple keywords.",
    )
    parser.add_argument("--angle-tolerance", type=float, default=2.0)
    parser.add_argument("--merge-tolerance", type=float, default=1.0)
    parser.add_argument("--gap-tolerance", type=float, default=5.0)
    parser.add_argument("--no-cross-cleanup", action="store_true", help="Disable cross closure cleanup.")
    parser.add_argument("--closure-max-length", type=float, default=300.0)
    parser.add_argument("--closure-length-to-width-ratio", type=float, default=1.5)
    parser.add_argument("--outline-min-length-to-width-ratio", type=float, default=3.0)
    parser.add_argument("--cross-tolerance", type=float, default=5.0)
    parser.add_argument("--no-overlap-trim", action="store_true", help="Disable one-direction overlap trimming.")
    parser.add_argument("--overlap-trim-tolerance", type=float, default=5.0)
    parser.add_argument("--overlap-trim-min-band-length", type=float, default=300.0)
    parser.add_argument("--overlap-trim-min-remainder", type=float, default=20.0)
    parser.add_argument(
        "--overlap-trim-tie-breaker",
        choices=("keep_horizontal", "keep_vertical"),
        default="keep_horizontal",
    )
    args = parser.parse_args(argv)

    options = PreprocessOptions(
        keep_layers=tuple(args.keep_layers) if args.keep_layers else ("0",),
        remove_layer_keywords=(
            tuple(args.remove_layer_keywords)
            if args.remove_layer_keywords
            else ("中心线", "虚线", "细线")
        ),
        angle_tolerance_degrees=args.angle_tolerance,
        merge_tolerance=args.merge_tolerance,
        gap_tolerance=args.gap_tolerance,
        cross_cleanup_enabled=not args.no_cross_cleanup,
        closure_max_length=args.closure_max_length,
        closure_length_to_width_ratio=args.closure_length_to_width_ratio,
        outline_min_length_to_width_ratio=args.outline_min_length_to_width_ratio,
        cross_tolerance=args.cross_tolerance,
        overlap_trim_enabled=not args.no_overlap_trim,
        overlap_trim_tolerance=args.overlap_trim_tolerance,
        overlap_trim_min_band_length=args.overlap_trim_min_band_length,
        overlap_trim_min_remainder=args.overlap_trim_min_remainder,
        overlap_trim_tie_breaker=args.overlap_trim_tie_breaker,
    )
    result = preprocess_dxf(
        args.dxf_path,
        output_path=args.output,
        overlay_path=args.overlay,
        report_csv_path=args.report,
        options=options,
    )
    print(_format_result_summary(result))
    return 0


def _default_clean_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}_clean.dxf")


def _collect_layer_stats(
    doc: ezdxf.document.Drawing,
    segments: Sequence[DxfSegment2D],
) -> tuple[LayerStat, ...]:
    entity_counts: Counter[str] = Counter()
    entity_types_by_layer: dict[str, Counter[str]] = {}
    colors_by_layer: dict[str, Counter[int]] = {}
    segment_counts: Counter[str] = Counter(segment.layer for segment in segments)

    for entity in doc.modelspace():
        layer = str(entity.dxf.layer)
        entity_counts[layer] += 1
        entity_types_by_layer.setdefault(layer, Counter())[entity.dxftype()] += 1
        colors_by_layer.setdefault(layer, Counter())[int(getattr(entity.dxf, "color", 256))] += 1

    layers = sorted(set(entity_counts) | set(segment_counts))
    return tuple(
        LayerStat(
            layer=layer,
            entity_count=entity_counts[layer],
            segment_count=segment_counts[layer],
            entity_types=tuple(
                f"{entity_type}:{count}"
                for entity_type, count in sorted(entity_types_by_layer.get(layer, Counter()).items())
            ),
            colors=tuple(sorted(colors_by_layer.get(layer, Counter()))),
        )
        for layer in layers
    )


def _read_source_geometry(
    doc: ezdxf.document.Drawing,
) -> tuple[list[DxfSegment2D], list[PreprocessReportRecord], int]:
    segments: list[DxfSegment2D] = []
    non_line_records: list[PreprocessReportRecord] = []
    original_entity_count = 0

    for entity in doc.modelspace():
        original_entity_count += 1
        entity_type = entity.dxftype()
        layer = str(entity.dxf.layer)
        handle = str(entity.dxf.handle)
        if entity_type == "LINE":
            _append_segment(
                segments,
                start=(float(entity.dxf.start.x), float(entity.dxf.start.y)),
                end=(float(entity.dxf.end.x), float(entity.dxf.end.y)),
                layer=layer,
                entity_type=entity_type,
                handle=handle,
                part_index=0,
            )
        elif entity_type == "LWPOLYLINE":
            points = [(float(x), float(y)) for x, y in entity.get_points("xy")]
            _append_polyline_segments(
                segments,
                points=points,
                closed=bool(entity.closed),
                layer=layer,
                entity_type=entity_type,
                handle=handle,
            )
        else:
            non_line_records.append(
                PreprocessReportRecord(
                    source_id=handle,
                    entity_type=entity_type,
                    layer=layer,
                    status="removed",
                    reason="removed_non_line_entity",
                )
            )

    return segments, non_line_records, original_entity_count


def _append_polyline_segments(
    segments: list[DxfSegment2D],
    *,
    points: Sequence[Point2D],
    closed: bool,
    layer: str,
    entity_type: str,
    handle: str,
) -> None:
    if len(points) < 2:
        return

    for index, (start, end) in enumerate(zip(points, points[1:])):
        _append_segment(
            segments,
            start=start,
            end=end,
            layer=layer,
            entity_type=entity_type,
            handle=handle,
            part_index=index,
        )

    if closed:
        _append_segment(
            segments,
            start=points[-1],
            end=points[0],
            layer=layer,
            entity_type=entity_type,
            handle=handle,
            part_index=len(points) - 1,
        )


def _append_segment(
    segments: list[DxfSegment2D],
    *,
    start: Point2D,
    end: Point2D,
    layer: str,
    entity_type: str,
    handle: str,
    part_index: int,
) -> None:
    if start == end:
        return
    segments.append(
        DxfSegment2D(
            id=f"{handle}:{part_index}",
            start=start,
            end=end,
            layer=layer,
            entity_type=entity_type,
        )
    )


def _classify_segment(
    segment: DxfSegment2D,
    options: PreprocessOptions,
) -> tuple[_AxisSegment | None, str]:
    if _length(segment.start, segment.end) < options.min_segment_length:
        return None, "removed_too_short"
    if _layer_has_remove_keyword(segment.layer, options.remove_layer_keywords):
        return None, "removed_layer_keyword"
    if options.keep_layers and segment.layer not in set(options.keep_layers):
        return None, "removed_layer_not_in_keep_list"

    axis = _axis_orientation(segment.start, segment.end, options.angle_tolerance_degrees)
    if axis is None:
        return None, "removed_not_axis_aligned"

    axis_segment = _to_axis_segment(segment, axis)
    if axis_segment.length < options.min_segment_length:
        return None, "removed_too_short"
    return axis_segment, ""


def _layer_has_remove_keyword(layer: str, keywords: Iterable[str]) -> bool:
    return any(keyword and keyword in layer for keyword in keywords)


def _axis_orientation(start: Point2D, end: Point2D, tolerance_degrees: float) -> str | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
    horizontal_delta = min(angle, 180.0 - angle)
    vertical_delta = abs(angle - 90.0)
    if horizontal_delta <= tolerance_degrees:
        return "H"
    if vertical_delta <= tolerance_degrees:
        return "V"
    return None


def _to_axis_segment(segment: DxfSegment2D, axis: str) -> _AxisSegment:
    if axis == "H":
        coord = (segment.start[1] + segment.end[1]) / 2.0
        interval = _sorted_interval(segment.start[0], segment.end[0])
    else:
        coord = (segment.start[0] + segment.end[0]) / 2.0
        interval = _sorted_interval(segment.start[1], segment.end[1])
    return _AxisSegment(
        source=segment,
        axis=axis,
        coord=coord,
        interval=interval,
        layer=segment.layer,
    )


def _merge_axis_segments(
    axis_segments: list[_AxisSegment],
    options: PreprocessOptions,
) -> tuple[list[DxfSegment2D], list[PreprocessReportRecord], int]:
    outputs: list[DxfSegment2D] = []
    records: list[PreprocessReportRecord] = []
    merged_group_count = 0

    for axis in ("H", "V"):
        clusters = _cluster_by_coordinate(
            [segment for segment in axis_segments if segment.axis == axis],
            options.merge_tolerance,
        )
        for cluster in clusters:
            for group in _merge_intervals(cluster, options.gap_tolerance):
                output_id = f"P{len(outputs) + 1}"
                output = _axis_group_to_segment(output_id, axis, group)
                outputs.append(output)

                is_merged = len(group) > 1 or any(
                    _source_changed_by_merge(item, output, options.merge_tolerance)
                    for item in group
                )
                if is_merged:
                    merged_group_count += 1

                for item in group:
                    records.append(
                        PreprocessReportRecord(
                            source_id=item.source.id,
                            entity_type=item.source.entity_type,
                            layer=item.source.layer,
                            status="merged" if is_merged else "kept",
                            reason=(
                                "merged_collinear_overlap_or_gap"
                                if is_merged
                                else "kept_axis_aligned"
                            ),
                            output_id=output_id,
                            start=item.source.start,
                            end=item.source.end,
                        )
                    )

    return outputs, records, merged_group_count


def _cluster_by_coordinate(
    segments: list[_AxisSegment],
    tolerance: float,
) -> list[list[_AxisSegment]]:
    clusters: list[list[_AxisSegment]] = []
    for segment in sorted(segments, key=lambda item: (item.coord, item.interval[0], item.interval[1])):
        if not clusters:
            clusters.append([segment])
            continue

        current = clusters[-1]
        current_coord = _weighted_coord(current)
        if abs(segment.coord - current_coord) <= tolerance:
            current.append(segment)
        else:
            clusters.append([segment])

    return clusters


def _merge_intervals(
    cluster: list[_AxisSegment],
    gap_tolerance: float,
) -> list[list[_AxisSegment]]:
    if not cluster:
        return []

    groups: list[list[_AxisSegment]] = []
    current: list[_AxisSegment] = []
    current_end = 0.0

    for segment in sorted(cluster, key=lambda item: (item.interval[0], item.interval[1])):
        if not current:
            current = [segment]
            current_end = segment.interval[1]
            continue

        if segment.interval[0] <= current_end + gap_tolerance:
            current.append(segment)
            current_end = max(current_end, segment.interval[1])
        else:
            groups.append(current)
            current = [segment]
            current_end = segment.interval[1]

    if current:
        groups.append(current)
    return groups


def _axis_group_to_segment(
    output_id: str,
    axis: str,
    group: list[_AxisSegment],
) -> DxfSegment2D:
    coord = _weighted_coord(group)
    start_value = min(item.interval[0] for item in group)
    end_value = max(item.interval[1] for item in group)
    layer = _most_common_layer(group)

    if axis == "H":
        start = (start_value, coord)
        end = (end_value, coord)
    else:
        start = (coord, start_value)
        end = (coord, end_value)

    return DxfSegment2D(
        id=output_id,
        start=start,
        end=end,
        layer=layer,
        entity_type="LINE",
    )


def _source_changed_by_merge(
    item: _AxisSegment,
    output: DxfSegment2D,
    tolerance: float,
) -> bool:
    output_axis = _axis_orientation(output.start, output.end, 0.01)
    if output_axis is None:
        return True
    output_axis_segment = _to_axis_segment(output, output_axis)
    return (
        abs(item.coord - output_axis_segment.coord) > tolerance
        or abs(item.interval[0] - output_axis_segment.interval[0]) > tolerance
        or abs(item.interval[1] - output_axis_segment.interval[1]) > tolerance
    )


def _weighted_coord(group: list[_AxisSegment]) -> float:
    total_length = sum(max(item.length, 1e-12) for item in group)
    return sum(item.coord * max(item.length, 1e-12) for item in group) / total_length


def _most_common_layer(group: list[_AxisSegment]) -> str:
    counts = Counter(item.layer for item in group)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _cleanup_cross_closure_segments(
    segments: Sequence[DxfSegment2D],
    options: PreprocessOptions,
) -> _CrossCleanupResult:
    if not options.cross_cleanup_enabled:
        return _CrossCleanupResult(
            clean_segments=tuple(segments),
            removed_segments=(),
            records=(),
        )

    axis_segments = [
        axis_segment
        for segment in segments
        if (axis_segment := _clean_segment_to_axis_segment(segment, options)) is not None
    ]
    removal_reasons = {
        segment.source.id: reason
        for segment in axis_segments
        if (reason := _cross_removal_reason(segment, axis_segments, options)) is not None
    }

    clean_segments: list[DxfSegment2D] = []
    removed_segments: list[DxfSegment2D] = []
    records: list[PreprocessReportRecord] = []
    for segment in segments:
        reason = removal_reasons.get(segment.id)
        if reason is None:
            clean_segments.append(segment)
            records.append(
                PreprocessReportRecord(
                    source_id=segment.id,
                    entity_type=segment.entity_type,
                    layer=segment.layer,
                    status="kept",
                    reason="kept_real_outline_edge",
                    output_id=segment.id,
                    start=segment.start,
                    end=segment.end,
                )
            )
            continue

        removed_segments.append(segment)
        records.append(
            PreprocessReportRecord(
                source_id=segment.id,
                entity_type=segment.entity_type,
                layer=segment.layer,
                status="removed",
                reason=reason,
                output_id=segment.id,
                start=segment.start,
                end=segment.end,
            )
        )

    return _CrossCleanupResult(
        clean_segments=tuple(clean_segments),
        removed_segments=tuple(removed_segments),
        records=tuple(records),
    )


def _clean_segment_to_axis_segment(
    segment: DxfSegment2D,
    options: PreprocessOptions,
) -> _AxisSegment | None:
    axis = _axis_orientation(segment.start, segment.end, options.angle_tolerance_degrees)
    if axis is None:
        return None
    axis_segment = _to_axis_segment(segment, axis)
    if axis_segment.length < options.min_segment_length:
        return None
    return axis_segment


def _cross_removal_reason(
    candidate: _AxisSegment,
    segments: Sequence[_AxisSegment],
    options: PreprocessOptions,
) -> str | None:
    if candidate.length > options.closure_max_length:
        return None

    start_support = _long_perpendicular_support_at(candidate, candidate.interval[0], segments, options)
    end_support = _long_perpendicular_support_at(candidate, candidate.interval[1], segments, options)
    if start_support is not None and end_support is not None:
        support_width = abs(end_support.coord - start_support.coord)
        if support_width <= options.cross_tolerance:
            return None
        if candidate.length <= support_width * options.closure_length_to_width_ratio:
            return "removed_cross_closure_line"

    support_count = int(start_support is not None) + int(end_support is not None)
    if (
        support_count == 1
        and _has_interior_long_perpendicular_crossing(candidate, segments, options)
        and not _has_parallel_outline_mate(candidate, segments, options)
    ):
        return "removed_short_crossing_stub"

    return None


def _long_perpendicular_support_at(
    candidate: _AxisSegment,
    endpoint_value: float,
    segments: Sequence[_AxisSegment],
    options: PreprocessOptions,
) -> _AxisSegment | None:
    supports = [
        segment
        for segment in segments
        if segment.axis != candidate.axis
        and segment.source.id != candidate.source.id
        and segment.length >= candidate.length * options.outline_min_length_to_width_ratio
        and abs(segment.coord - endpoint_value) <= options.cross_tolerance
        and _interval_contains(segment.interval, candidate.coord, options.cross_tolerance)
    ]
    if not supports:
        return None
    return max(supports, key=lambda item: item.length)


def _has_interior_long_perpendicular_crossing(
    candidate: _AxisSegment,
    segments: Sequence[_AxisSegment],
    options: PreprocessOptions,
) -> bool:
    return any(
        segment.axis != candidate.axis
        and segment.source.id != candidate.source.id
        and segment.length >= candidate.length * options.outline_min_length_to_width_ratio
        and candidate.interval[0] + options.cross_tolerance < segment.coord < candidate.interval[1] - options.cross_tolerance
        and _interval_contains(segment.interval, candidate.coord, options.cross_tolerance)
        for segment in segments
    )


def _has_parallel_outline_mate(
    candidate: _AxisSegment,
    segments: Sequence[_AxisSegment],
    options: PreprocessOptions,
) -> bool:
    for segment in segments:
        if segment.axis != candidate.axis or segment.source.id == candidate.source.id:
            continue

        coord_gap = abs(segment.coord - candidate.coord)
        if coord_gap <= options.cross_tolerance:
            continue
        if coord_gap > options.closure_max_length:
            continue

        overlap = min(candidate.interval[1], segment.interval[1]) - max(candidate.interval[0], segment.interval[0])
        if overlap <= 0:
            continue
        if overlap >= min(candidate.length, segment.length) * 0.75:
            return True

    return False


def _interval_contains(
    interval: tuple[float, float],
    value: float,
    tolerance: float,
) -> bool:
    return interval[0] - tolerance <= value <= interval[1] + tolerance


def _trim_overlapping_member_bands(
    segments: Sequence[DxfSegment2D],
    options: PreprocessOptions,
) -> _OverlapTrimResult:
    if not options.overlap_trim_enabled:
        return _OverlapTrimResult(clean_segments=tuple(segments), trimmed_segments=(), records=())

    axis_segments = [
        axis_segment
        for segment in segments
        if (axis_segment := _clean_segment_to_axis_segment(segment, options)) is not None
    ]
    bands = _find_member_bands(axis_segments, options)
    horizontal_bands = [band for band in bands if band.axis == "H"]
    vertical_bands = [band for band in bands if band.axis == "V"]
    cuts_by_segment_id: dict[str, list[tuple[float, float]]] = {}

    for horizontal in horizontal_bands:
        for vertical in vertical_bands:
            if not _bands_overlap(horizontal, vertical, options.overlap_trim_tolerance):
                continue
            secondary, primary = _secondary_and_primary_band(horizontal, vertical, options)
            cut_interval = primary.coord_range
            for side in (secondary.first, secondary.second):
                clipped_cut = _clip_interval(
                    cut_interval,
                    side.interval,
                    options.overlap_trim_tolerance,
                )
                if clipped_cut is None:
                    continue
                cuts_by_segment_id.setdefault(side.source.id, []).append(clipped_cut)

    if not cuts_by_segment_id:
        return _OverlapTrimResult(clean_segments=tuple(segments), trimmed_segments=(), records=())

    clean_segments: list[DxfSegment2D] = []
    trimmed_segments: list[DxfSegment2D] = []
    records: list[PreprocessReportRecord] = []
    for segment in segments:
        cuts = cuts_by_segment_id.get(segment.id)
        if not cuts:
            clean_segments.append(segment)
            continue

        axis_segment = _clean_segment_to_axis_segment(segment, options)
        if axis_segment is None:
            clean_segments.append(segment)
            continue

        merged_cuts = _merge_cut_intervals(cuts, options.overlap_trim_tolerance)
        pieces = _subtract_intervals(axis_segment.interval, merged_cuts, options.overlap_trim_tolerance)
        for cut_index, cut in enumerate(merged_cuts, start=1):
            cut_segment = _axis_interval_to_segment(
                f"{segment.id}:trim{cut_index}",
                axis_segment.axis,
                axis_segment.coord,
                cut,
                segment.layer,
            )
            trimmed_segments.append(cut_segment)
            records.append(
                PreprocessReportRecord(
                    source_id=segment.id,
                    entity_type=segment.entity_type,
                    layer=segment.layer,
                    status="removed",
                    reason="trimmed_overlap_secondary_member",
                    output_id=cut_segment.id,
                    start=cut_segment.start,
                    end=cut_segment.end,
                )
            )

        kept_piece_count = 0
        for piece_index, piece in enumerate(pieces, start=1):
            piece_length = piece[1] - piece[0]
            piece_segment = _axis_interval_to_segment(
                f"{segment.id}:part{piece_index}",
                axis_segment.axis,
                axis_segment.coord,
                piece,
                segment.layer,
            )
            if piece_length < options.overlap_trim_min_remainder:
                trimmed_segments.append(piece_segment)
                records.append(
                    PreprocessReportRecord(
                        source_id=segment.id,
                        entity_type=segment.entity_type,
                        layer=segment.layer,
                        status="removed",
                        reason="removed_tiny_trim_fragment",
                        output_id=piece_segment.id,
                        start=piece_segment.start,
                        end=piece_segment.end,
                    )
                )
                continue

            kept_piece_count += 1
            clean_segments.append(
                _axis_interval_to_segment(
                    segment.id if len(pieces) == 1 else f"{segment.id}:part{kept_piece_count}",
                    axis_segment.axis,
                    axis_segment.coord,
                    piece,
                    segment.layer,
                )
            )

    return _OverlapTrimResult(
        clean_segments=tuple(clean_segments),
        trimmed_segments=tuple(trimmed_segments),
        records=tuple(records),
    )


def _find_member_bands(
    axis_segments: Sequence[_AxisSegment],
    options: PreprocessOptions,
) -> tuple[_MemberBand, ...]:
    bands: list[_MemberBand] = []
    for axis in ("H", "V"):
        candidates: list[_MemberBand] = []
        same_axis = [segment for segment in axis_segments if segment.axis == axis]
        for left_index, left in enumerate(same_axis):
            for right in same_axis[left_index + 1 :]:
                width = abs(left.coord - right.coord)
                if width <= options.overlap_trim_tolerance:
                    continue
                if width > options.closure_max_length:
                    continue

                overlap = _interval_overlap(left.interval, right.interval)
                if overlap is None:
                    continue
                overlap_length = overlap[1] - overlap[0]
                if overlap_length < options.overlap_trim_min_band_length:
                    continue
                if overlap_length < min(left.length, right.length) * 0.5:
                    continue

                coord_range = _sorted_interval(left.coord, right.coord)
                candidates.append(
                    _MemberBand(
                        id=f"B{len(candidates) + 1}",
                        axis=axis,
                        first=left,
                        second=right,
                        coord_range=coord_range,
                        interval=overlap,
                        width=width,
                    )
                )

        bands.extend(_select_member_bands(candidates, options.overlap_trim_tolerance))

    return tuple(bands)


def _select_member_bands(
    candidates: Sequence[_MemberBand],
    tolerance: float,
) -> tuple[_MemberBand, ...]:
    selected: list[_MemberBand] = []
    used_intervals_by_segment: dict[str, list[tuple[float, float]]] = {}
    sorted_candidates = sorted(candidates, key=lambda band: (band.width, -band.length, band.first.source.id, band.second.source.id))

    for band in sorted_candidates:
        if _band_side_interval_used(band.first, band.interval, used_intervals_by_segment, tolerance):
            continue
        if _band_side_interval_used(band.second, band.interval, used_intervals_by_segment, tolerance):
            continue

        selected.append(band)
        used_intervals_by_segment.setdefault(band.first.source.id, []).append(band.interval)
        used_intervals_by_segment.setdefault(band.second.source.id, []).append(band.interval)

    return tuple(selected)


def _band_side_interval_used(
    side: _AxisSegment,
    interval: tuple[float, float],
    used_intervals_by_segment: dict[str, list[tuple[float, float]]],
    tolerance: float,
) -> bool:
    existing = used_intervals_by_segment.get(side.source.id, [])
    return any(_intervals_overlap(interval, used, tolerance) for used in existing)


def _bands_overlap(
    horizontal: _MemberBand,
    vertical: _MemberBand,
    tolerance: float,
) -> bool:
    if horizontal.axis != "H" or vertical.axis != "V":
        raise ValueError("_bands_overlap expects one horizontal band and one vertical band")
    x_overlap = _intervals_overlap(horizontal.interval, vertical.coord_range, tolerance)
    y_overlap = _intervals_overlap(vertical.interval, horizontal.coord_range, tolerance)
    return x_overlap and y_overlap


def _secondary_and_primary_band(
    horizontal: _MemberBand,
    vertical: _MemberBand,
    options: PreprocessOptions,
) -> tuple[_MemberBand, _MemberBand]:
    if _band_lengths_are_close(horizontal, vertical, options.overlap_trim_tolerance):
        if options.overlap_trim_tie_breaker == "keep_horizontal":
            return vertical, horizontal
        return horizontal, vertical
    if horizontal.length > vertical.length:
        return vertical, horizontal
    return horizontal, vertical


def _band_lengths_are_close(
    left: _MemberBand,
    right: _MemberBand,
    tolerance: float,
) -> bool:
    larger = max(left.length, right.length, 1.0)
    return abs(left.length - right.length) <= max(tolerance, larger * 0.1)


def _clip_interval(
    cut: tuple[float, float],
    boundary: tuple[float, float],
    tolerance: float,
) -> tuple[float, float] | None:
    start = max(cut[0], boundary[0])
    end = min(cut[1], boundary[1])
    if end - start <= tolerance:
        return None
    return (start, end)


def _merge_cut_intervals(
    cuts: Sequence[tuple[float, float]],
    tolerance: float,
) -> tuple[tuple[float, float], ...]:
    merged: list[tuple[float, float]] = []
    for cut in sorted(cuts):
        if not merged or cut[0] > merged[-1][1] + tolerance:
            merged.append(cut)
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], cut[1]))
    return tuple(merged)


def _subtract_intervals(
    source: tuple[float, float],
    cuts: Sequence[tuple[float, float]],
    tolerance: float,
) -> tuple[tuple[float, float], ...]:
    pieces: list[tuple[float, float]] = []
    cursor = source[0]
    for cut in cuts:
        if cut[0] > cursor + tolerance:
            pieces.append((cursor, cut[0]))
        cursor = max(cursor, cut[1])
    if cursor < source[1] - tolerance:
        pieces.append((cursor, source[1]))
    return tuple(pieces)


def _axis_interval_to_segment(
    segment_id: str,
    axis: str,
    coord: float,
    interval: tuple[float, float],
    layer: str,
) -> DxfSegment2D:
    if axis == "H":
        start = (interval[0], coord)
        end = (interval[1], coord)
    else:
        start = (coord, interval[0])
        end = (coord, interval[1])
    return DxfSegment2D(
        id=segment_id,
        start=start,
        end=end,
        layer=layer,
        entity_type="LINE",
    )


def _interval_overlap(
    left: tuple[float, float],
    right: tuple[float, float],
) -> tuple[float, float] | None:
    start = max(left[0], right[0])
    end = min(left[1], right[1])
    if end <= start:
        return None
    return (start, end)


def _intervals_overlap(
    left: tuple[float, float],
    right: tuple[float, float],
    tolerance: float,
) -> bool:
    return min(left[1], right[1]) - max(left[0], right[0]) > tolerance


def _write_clean_dxf(path: Path, segments: Sequence[DxfSegment2D]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    for segment in segments:
        _ensure_layer(doc, segment.layer, color=7)
        modelspace.add_line(segment.start, segment.end, dxfattribs={"layer": segment.layer})
    doc.saveas(path)


def _write_preprocess_overlay(
    path: Path,
    clean_segments: Sequence[DxfSegment2D],
    removed_segments: Sequence[DxfSegment2D],
    cross_removed_segments: Sequence[DxfSegment2D],
    overlap_trimmed_segments: Sequence[DxfSegment2D],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    _ensure_layer(doc, "PREPROCESS_CLEAN", color=3)
    _ensure_layer(doc, "PREPROCESS_REMOVED", color=1)
    _ensure_layer(doc, "PREPROCESS_CROSS_REMOVED", color=6)
    _ensure_layer(doc, "PREPROCESS_OVERLAP_TRIMMED", color=2)

    modelspace = doc.modelspace()
    for segment in clean_segments:
        modelspace.add_line(
            segment.start,
            segment.end,
            dxfattribs={"layer": "PREPROCESS_CLEAN", "color": 3},
        )
    for segment in removed_segments:
        modelspace.add_line(
            segment.start,
            segment.end,
            dxfattribs={"layer": "PREPROCESS_REMOVED", "color": 1},
        )
    for segment in cross_removed_segments:
        modelspace.add_line(
            segment.start,
            segment.end,
            dxfattribs={"layer": "PREPROCESS_CROSS_REMOVED", "color": 6},
        )
    for segment in overlap_trimmed_segments:
        modelspace.add_line(
            segment.start,
            segment.end,
            dxfattribs={"layer": "PREPROCESS_OVERLAP_TRIMMED", "color": 2},
        )
    doc.saveas(path)


def write_preprocess_workspace_overlay(
    path: str | Path,
    *,
    original_segments: Sequence[DxfSegment2D],
    current_segments: Sequence[DxfSegment2D],
    preview: PreprocessPreview | None = None,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2010")
    _ensure_layer(doc, "WORKSPACE_ORIGINAL", color=8)
    _ensure_layer(doc, "WORKSPACE_CURRENT", color=3)
    _ensure_layer(doc, "WORKSPACE_PREVIEW_REMOVE", color=1)
    _ensure_layer(doc, "WORKSPACE_PREVIEW_TRIM", color=2)
    _ensure_layer(doc, "WORKSPACE_PREVIEW_OUTPUT", color=5)

    modelspace = doc.modelspace()
    _add_overlay_lines(modelspace, original_segments, "WORKSPACE_ORIGINAL", color=8)
    _add_overlay_lines(modelspace, current_segments, "WORKSPACE_CURRENT", color=3)
    if preview is not None:
        _add_overlay_lines(modelspace, preview.output_segments, "WORKSPACE_PREVIEW_OUTPUT", color=5)
        _add_overlay_lines(modelspace, preview.removed_segments, "WORKSPACE_PREVIEW_REMOVE", color=1)
        _add_overlay_lines(modelspace, preview.trimmed_segments, "WORKSPACE_PREVIEW_TRIM", color=2)

    doc.saveas(output_path)


def _add_overlay_lines(
    modelspace: ezdxf.layouts.Modelspace,
    segments: Sequence[DxfSegment2D],
    layer: str,
    *,
    color: int,
) -> None:
    for segment in segments:
        modelspace.add_line(
            segment.start,
            segment.end,
            dxfattribs={"layer": layer, "color": color},
        )


def _write_report_csv(
    path: Path,
    records: Sequence[PreprocessReportRecord],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "source_id",
                "entity_type",
                "layer",
                "status",
                "reason",
                "output_id",
                "start_x",
                "start_y",
                "end_x",
                "end_y",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "source_id": record.source_id,
                    "entity_type": record.entity_type,
                    "layer": record.layer,
                    "status": record.status,
                    "reason": record.reason,
                    "output_id": record.output_id,
                    "start_x": _format_optional_coord(record.start, 0),
                    "start_y": _format_optional_coord(record.start, 1),
                    "end_x": _format_optional_coord(record.end, 0),
                    "end_y": _format_optional_coord(record.end, 1),
                }
            )


def _ensure_layer(doc: ezdxf.document.Drawing, name: str, *, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)


def _format_optional_coord(point: Point2D | None, index: int) -> str:
    if point is None:
        return ""
    return f"{point[index]:.6f}"


def _format_result_summary(result: PreprocessResult) -> str:
    return (
        "DXF preprocessing finished.\n"
        f"Input: {result.input_path}\n"
        f"Clean DXF: {result.clean_dxf_path}\n"
        f"Overlay DXF: {result.overlay_dxf_path}\n"
        f"Report CSV: {result.report_csv_path}\n"
        f"Source entities: {result.original_entity_count}\n"
        f"Source line segments: {result.original_segment_count}\n"
        f"Kept line segments before merge: {result.kept_segment_count}\n"
        f"Removed line segments: {result.removed_segment_count}\n"
        f"Removed non-line entities: {result.non_line_entity_count}\n"
        f"Output line segments: {result.output_segment_count}\n"
        f"Merged groups: {result.merged_group_count}\n"
        f"Cross cleanup removed segments: {result.cross_removed_segment_count}\n"
        f"Overlap trimmed segments: {result.overlap_trimmed_segment_count}"
    )


def _sorted_interval(left: float, right: float) -> tuple[float, float]:
    return (min(left, right), max(left, right))


def _length(start: Point2D, end: Point2D) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


if __name__ == "__main__":
    raise SystemExit(main())
