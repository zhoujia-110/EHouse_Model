"""Roof-face processing using the same recognition path as the base face."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from ehouse_model.base_processing import (
    BaseProcessingOptions,
    extract_base_face,
)
from ehouse_model.domain import Member3D, Node3D
from ehouse_model.dxf_reader import Point2D
from ehouse_model.exporters import export_staad_geometry
from ehouse_model.face_extractor import FaceExtractionOptions
from ehouse_model.face_model import FaceModel
from ehouse_model.global_model_types import GlobalModel


@dataclass(frozen=True, slots=True)
class RoofBoundaryOffsets:
    """Boundary deltas for roof-only coordinate correction."""

    left_dx: float = 0.0
    right_dx: float = 0.0
    top_dz: float = 0.0
    bottom_dz: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "left_dx", float(self.left_dx))
        object.__setattr__(self, "right_dx", float(self.right_dx))
        object.__setattr__(self, "top_dz", float(self.top_dz))
        object.__setattr__(self, "bottom_dz", float(self.bottom_dz))


@dataclass(frozen=True, slots=True)
class RoofExtractionResult:
    """Roof extraction result in the user-selected global Y plane."""

    face_model: FaceModel
    global_model: GlobalModel
    y_plane: float
    origin: Point2D
    snap_count: int
    outline_segments: tuple[tuple[Point2D, Point2D], ...] = ()
    origin_source: Point2D = (0.0, 0.0)
    terminal_stub_removed_count: int = 0
    local_patch_added_count: int = 0
    short_member_added_count: int = 0
    cluster_realign_added_count: int = 0
    cluster_realign_removed_count: int = 0
    cluster_realign_replaced_group_count: int = 0
    centerline_cleanup_merged_group_count: int = 0
    centerline_cleanup_removed_candidate_count: int = 0


def extract_roof_face(
    dxf_path: str | Path,
    *,
    y_plane: float,
    face_model_path: str | Path | None = None,
    overlay_path: str | Path | None = None,
    warnings_csv_path: str | Path | None = None,
    extraction_options: FaceExtractionOptions | None = None,
    roof_options: BaseProcessingOptions | None = None,
    local_patch_points: tuple[Point2D, ...] | list[Point2D] | None = None,
    short_member_points: tuple[Point2D, ...] | list[Point2D] | None = None,
    cluster_realign_points: tuple[Point2D, ...] | list[Point2D] | None = None,
) -> RoofExtractionResult:
    """Extract a roof drawing exactly like the base, then place it at Y."""
    y_value = float(y_plane)
    base_result = extract_base_face(
        dxf_path,
        face_model_path=face_model_path,
        overlay_path=overlay_path,
        warnings_csv_path=warnings_csv_path,
        extraction_options=extraction_options,
        base_options=roof_options,
        local_patch_points=local_patch_points,
        short_member_points=short_member_points,
        cluster_realign_points=cluster_realign_points,
    )
    return RoofExtractionResult(
        face_model=base_result.face_model,
        global_model=face_model_to_roof_global_model(base_result.face_model, y_plane=y_value),
        y_plane=y_value,
        origin=base_result.origin,
        snap_count=base_result.snap_count,
        outline_segments=base_result.outline_segments,
        origin_source=base_result.origin_source,
        terminal_stub_removed_count=base_result.terminal_stub_removed_count,
        local_patch_added_count=base_result.local_patch_added_count,
        short_member_added_count=base_result.short_member_added_count,
        cluster_realign_added_count=base_result.cluster_realign_added_count,
        cluster_realign_removed_count=base_result.cluster_realign_removed_count,
        cluster_realign_replaced_group_count=base_result.cluster_realign_replaced_group_count,
        centerline_cleanup_merged_group_count=base_result.centerline_cleanup_merged_group_count,
        centerline_cleanup_removed_candidate_count=base_result.centerline_cleanup_removed_candidate_count,
    )


def face_model_to_roof_global_model(
    face_model: FaceModel,
    *,
    y_plane: float,
    boundary_offsets: RoofBoundaryOffsets | None = None,
    project_name: str = "E-House 屋盖",
) -> GlobalModel:
    """Convert a normalized roof face model to a constant-Y global geometry."""
    y_value = float(y_plane)
    nodes = _apply_roof_boundary_offsets(
        tuple(
            Node3D(id=node.id, x=node.x, y=y_value, z=node.y)
            for node in face_model.nodes
        ),
        boundary_offsets or RoofBoundaryOffsets(),
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


def _apply_roof_boundary_offsets(
    nodes: tuple[Node3D, ...],
    offsets: RoofBoundaryOffsets,
    *,
    tolerance: float = 1e-9,
) -> tuple[Node3D, ...]:
    """Move only roof boundary nodes, then rebase all roof nodes to Xmin/Zmin."""
    if not nodes:
        return nodes

    xmin = min(node.x for node in nodes)
    xmax = max(node.x for node in nodes)
    zmin = min(node.z for node in nodes)
    zmax = max(node.z for node in nodes)
    origin_x = xmin + offsets.left_dx
    origin_z = zmin + offsets.top_dz

    corrected_nodes: list[Node3D] = []
    for node in nodes:
        x = node.x
        z = node.z
        if abs(node.x - xmin) <= tolerance:
            x += offsets.left_dx
        if abs(node.x - xmax) <= tolerance:
            x += offsets.right_dx
        if abs(node.z - zmin) <= tolerance:
            z += offsets.top_dz
        if abs(node.z - zmax) <= tolerance:
            z += offsets.bottom_dz
        corrected_nodes.append(Node3D(id=node.id, x=x - origin_x, y=node.y, z=z - origin_z))
    return tuple(corrected_nodes)


def export_roof_staad(
    face_model: FaceModel,
    path: str | Path,
    *,
    y_plane: float,
    boundary_offsets: RoofBoundaryOffsets | None = None,
) -> None:
    """Export a normalized roof face model as geometry-only STD at Y."""
    export_staad_geometry(
        face_model_to_roof_global_model(
            face_model,
            y_plane=y_plane,
            boundary_offsets=boundary_offsets,
        ),
        path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract roof geometry using the base-face algorithm.")
    parser.add_argument("dxf_path", help="Input preprocessed roof DXF path.")
    parser.add_argument("--y-plane", type=float, required=True, help="Global Y coordinate for the roof plane.")
    parser.add_argument("--output-dir", default="output/roof", help="Output directory.")
    parser.add_argument("--max-pair-width", type=float, help="Maximum paired outline width in DXF units.")
    parser.add_argument("--snap-tolerance", type=float, help="Snap/extend tolerance in DXF units.")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    extraction_options = FaceExtractionOptions(max_pair_width=args.max_pair_width)
    roof_options = (
        BaseProcessingOptions(snap_extend_tolerance=args.snap_tolerance)
        if args.snap_tolerance is not None
        else None
    )
    result = extract_roof_face(
        args.dxf_path,
        y_plane=args.y_plane,
        face_model_path=output_dir / "roof_face_model.json",
        overlay_path=output_dir / "roof_centerline_overlay.dxf",
        warnings_csv_path=output_dir / "roof_warnings.csv",
        extraction_options=extraction_options,
        roof_options=roof_options,
    )
    export_roof_staad(result.face_model, output_dir / "roof_geometry.std", y_plane=args.y_plane)
    print(
        "Roof extraction finished.\n"
        f"Y plane: {result.y_plane:g}\n"
        f"Nodes: {len(result.face_model.nodes)}\n"
        f"Members: {len(result.face_model.members)}\n"
        f"Warnings: {len(result.face_model.warnings)}\n"
        f"Output: {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
