"""Build confirmed part geometry from recognition results."""

from __future__ import annotations

from collections.abc import Iterable

from ehouse_model.base_processing import face_model_to_base_global_model
from ehouse_model.domain import Member3D, Node2D, Node3D, PlaneSpec
from ehouse_model.face_model import FaceModel
from ehouse_model.mapping import map_2d_to_3d
from ehouse_model.part_geometry import PartGeometry, PartGeometrySource
from ehouse_model.project_model import ProjectDimensions, ProjectFaceSpec
from ehouse_model.roof_processing import RoofBoundaryOffsets, face_model_to_roof_global_model


def build_part_from_face_model(
    face_model: FaceModel,
    *,
    part_id: str,
    part_type: str,
    plane: PlaneSpec,
    source_kind: str = "generated_from_dxf",
    source_path: str | None = None,
) -> PartGeometry:
    """Confirm a 2D face model by mapping it into global coordinates."""
    nodes = tuple(map_2d_to_3d(node, plane) for node in face_model.nodes)
    members = tuple(
        Member3D(
            id=member.id,
            start_node_id=member.start_node_id,
            end_node_id=member.end_node_id,
        )
        for member in face_model.members
    )
    return PartGeometry(
        part_id=part_id,
        part_type=part_type,
        source=PartGeometrySource(kind=source_kind, path=source_path or face_model.source_dxf),
        nodes=nodes,
        members=members,
        warnings=face_model.warnings,
    )


def build_base_part_from_face_model(
    face_model: FaceModel,
    *,
    part_id: str = "base",
    source_path: str | None = None,
) -> PartGeometry:
    """Confirm the existing normalized base face model as global Y=0 geometry."""
    model = face_model_to_base_global_model(face_model)
    return PartGeometry(
        part_id=part_id,
        part_type="base",
        source=PartGeometrySource(
            kind="generated_from_dxf",
            path=source_path or face_model.source_dxf,
            description="Confirmed from base DXF recognition.",
        ),
        nodes=model.nodes,
        members=model.members,
        warnings=model.warnings,
    )


def build_roof_part_from_face_model(
    face_model: FaceModel,
    dimensions: ProjectDimensions | None = None,
    *,
    part_id: str = "roof",
    y_plane: float | None = None,
    center_offset: float = 0.0,
    boundary_offsets: RoofBoundaryOffsets | None = None,
    source_path: str | None = None,
) -> PartGeometry:
    """Confirm a roof face model at a user-selected global Y plane."""
    if y_plane is None:
        if dimensions is None:
            raise ValueError("build_roof_part_from_face_model requires dimensions or y_plane")
        y_plane = dimensions.height - center_offset
    model = face_model_to_roof_global_model(
        face_model,
        y_plane=float(y_plane),
        boundary_offsets=boundary_offsets,
    )
    return PartGeometry(
        part_id=part_id,
        part_type="roof",
        source=PartGeometrySource(
            kind="generated_from_dxf",
            path=source_path or face_model.source_dxf,
            description=f"Confirmed from roof DXF recognition at Y={float(y_plane):g}.",
        ),
        nodes=model.nodes,
        members=model.members,
        warnings=model.warnings,
    )


def build_wall_part_from_face_model(
    face_model: FaceModel,
    dimensions: ProjectDimensions,
    *,
    part_id: str,
    wall_type: str,
    center_offset: float = 0.0,
    source_path: str | None = None,
) -> PartGeometry:
    """Confirm a wall elevation face model using the standard wall mapping."""
    face = ProjectFaceSpec(
        id=part_id,
        plane_type=wall_type,
        face_model_path="__confirmed_wall_face_model__.json",
        center_offset=center_offset,
        dxf_path=source_path or face_model.source_dxf,
    )
    return build_part_from_face_model(
        face_model,
        part_id=part_id,
        part_type="side_wall",
        plane=face.to_plane_spec(dimensions),
        source_path=source_path,
    )


def build_vertical_wall_part_from_plan_points(
    points: Iterable[tuple[float, float] | Node2D],
    *,
    part_id: str,
    wall_type: str,
    height: float,
    base_y: float = 0.0,
    source_path: str | None = None,
) -> PartGeometry:
    """Build vertical wall members from plan-view centroid points.

    Point coordinates are interpreted as global plan coordinates ``(x, z)`` in
    meters. Each point creates one vertical member from ``base_y`` to
    ``base_y + height``.
    """
    nodes: list[Node3D] = []
    members: list[Member3D] = []
    for index, raw_point in enumerate(points, start=1):
        x, z = _plan_point(raw_point)
        bottom_id = f"N{index}B"
        top_id = f"N{index}T"
        nodes.append(Node3D(id=bottom_id, x=x, y=base_y, z=z))
        nodes.append(Node3D(id=top_id, x=x, y=base_y + height, z=z))
        members.append(Member3D(id=f"M{index}", start_node_id=bottom_id, end_node_id=top_id))

    return PartGeometry(
        part_id=part_id,
        part_type="side_wall",
        source=PartGeometrySource(
            kind="generated_from_plan_centroids",
            path=source_path,
            description=f"Vertical members generated from {wall_type} plan centroids.",
        ),
        nodes=tuple(nodes),
        members=tuple(members),
    )


def _plan_point(point: tuple[float, float] | Node2D) -> tuple[float, float]:
    if isinstance(point, Node2D):
        return point.x, point.y
    x, z = point
    return float(x), float(z)
