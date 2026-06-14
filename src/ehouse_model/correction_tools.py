"""Interactive correction tools for base face centerline models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ehouse_model.base_processing import (
    BaseExtractionResult,
    BaseProcessingOptions,
    DXF_MM_TO_M,
    face_model_to_base_global_model,
    normalize_base_coordinates,
    prune_base_terminal_stubs,
    snap_extend_centerlines,
    supplement_centerlines_near_points,
)
from ehouse_model.centerline_cleanup import (
    cleanup_centerline_candidates,
    realign_centerline_cluster_near_points,
    supplement_short_member_centerlines,
)
from ehouse_model.dxf_reader import Point2D, read_dxf_segments, write_overlay_dxf
from ehouse_model.exporters import export_warnings_csv
from ehouse_model.face_extractor import FaceExtractionOptions, extract_centerline_candidates
from ehouse_model.face_model import FaceModel, WarningRecord, write_face_model_json
from ehouse_model.face_topology import build_face_topology

CORRECTION_LOCAL_PATCH = "local_patch"
CORRECTION_SHORT_MEMBER = "short_member"
CORRECTION_CLUSTER_REALIGN = "cluster_realign"


@dataclass(frozen=True, slots=True)
class CorrectionStep:
    kind: str
    point: Point2D
    extraction_options: FaceExtractionOptions
    base_options: BaseProcessingOptions


def extract_base_with_correction_steps(
    dxf_path: str | Path,
    *,
    face_model_path: str | Path | None = None,
    overlay_path: str | Path | None = None,
    warnings_csv_path: str | Path | None = None,
    extraction_options: FaceExtractionOptions | None = None,
    base_options: BaseProcessingOptions | None = None,
    correction_steps: Iterable[CorrectionStep] = (),
) -> BaseExtractionResult:
    """Extract a base face and replay user-confirmed local correction steps."""
    extract_opts = extraction_options or FaceExtractionOptions()
    base_opts = base_options or BaseProcessingOptions()
    source_path = Path(dxf_path)
    segments = read_dxf_segments(source_path)
    candidates, extraction_warnings = extract_centerline_candidates(segments, extract_opts)

    local_patch_added_count = 0
    short_member_added_count = 0
    cluster_realign_added_count = 0
    cluster_realign_removed_count = 0
    cluster_realign_replaced_group_count = 0
    warning_inputs: list[WarningRecord] = [*extraction_warnings]

    for step in correction_steps:
        if step.kind == CORRECTION_LOCAL_PATCH:
            candidates, added_count, warnings = supplement_centerlines_near_points(
                segments,
                candidates,
                [step.point],
                extraction_options=step.extraction_options,
                radius=step.base_options.local_patch_radius,
                width_tolerance=step.base_options.local_patch_width_tolerance,
                width_tolerance_ratio=step.base_options.local_patch_width_tolerance_ratio,
                max_candidates_per_point=step.base_options.local_patch_max_candidates_per_point,
            )
            local_patch_added_count += added_count
            warning_inputs.extend(warnings)
            continue

        if step.kind == CORRECTION_SHORT_MEMBER:
            result = supplement_short_member_centerlines(
                segments,
                candidates,
                [step.point],
                step.base_options.centerline_cleanup_options,
            )
            candidates = list(result.centerlines)
            short_member_added_count += result.added_count
            warning_inputs.extend(result.warnings)
            continue

        if step.kind == CORRECTION_CLUSTER_REALIGN:
            result = realign_centerline_cluster_near_points(
                segments,
                candidates,
                [step.point],
                step.base_options.centerline_cleanup_options,
            )
            candidates = list(result.centerlines)
            cluster_realign_added_count += result.added_count
            cluster_realign_removed_count += result.removed_count
            cluster_realign_replaced_group_count += result.replaced_group_count
            warning_inputs.extend(result.warnings)
            continue

        raise ValueError(f"unknown correction tool: {step.kind}")

    cleanup_result = cleanup_centerline_candidates(
        candidates,
        base_opts.centerline_cleanup_options,
    )
    candidates = list(cleanup_result.centerlines)
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

    warning_inputs.extend(cleanup_result.warnings)
    warning_inputs.extend(snap_warnings)
    warning_inputs.extend(topology.warnings)
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
    raw_model = _replace_face_model_warnings(raw_model, _renumber_warnings(warning_inputs))
    normalized = normalize_base_coordinates(raw_model)
    model = normalized.face_model
    global_model = face_model_to_base_global_model(model)
    outline_segments = tuple(
        (
            _normalize_point(segment.start, normalized.origin_source),
            _normalize_point(segment.end, normalized.origin_source),
        )
        for segment in segments
    )

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
        outline_segments=outline_segments,
        origin_source=normalized.origin_source,
        terminal_stub_removed_count=terminal_stub_removed_count,
        local_patch_added_count=local_patch_added_count,
        short_member_added_count=short_member_added_count,
        cluster_realign_added_count=cluster_realign_added_count,
        cluster_realign_removed_count=cluster_realign_removed_count,
        cluster_realign_replaced_group_count=cluster_realign_replaced_group_count,
        centerline_cleanup_merged_group_count=cleanup_result.merged_group_count,
        centerline_cleanup_removed_candidate_count=cleanup_result.removed_candidate_count,
    )


def _member_segments(face_model: FaceModel) -> list[tuple[Point2D, Point2D]]:
    nodes_by_id = {node.id: node for node in face_model.nodes}
    segments: list[tuple[Point2D, Point2D]] = []
    for member in face_model.members:
        start = nodes_by_id.get(member.start_node_id)
        end = nodes_by_id.get(member.end_node_id)
        if start is not None and end is not None:
            segments.append(((start.x, start.y), (end.x, end.y)))
    return segments


def _replace_face_model_warnings(face_model: FaceModel, warnings: tuple[WarningRecord, ...]) -> FaceModel:
    return FaceModel(
        source_dxf=face_model.source_dxf,
        nodes=face_model.nodes,
        members=face_model.members,
        centerline_candidates=face_model.centerline_candidates,
        member_sources=face_model.member_sources,
        warnings=warnings,
    )


def _renumber_warnings(warnings: list[WarningRecord]) -> tuple[WarningRecord, ...]:
    return tuple(
        warning.with_id(f"W{index}")
        for index, warning in enumerate(warnings, start=1)
    )


def _normalize_point(point: Point2D, origin: Point2D) -> Point2D:
    return (
        _round4((point[0] - origin[0]) * DXF_MM_TO_M),
        _round4((origin[1] - point[1]) * DXF_MM_TO_M),
    )


def _round4(value: float) -> float:
    result = round(value, 4)
    return 0.0 if result == -0.0 else result
