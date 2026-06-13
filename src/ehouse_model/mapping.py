"""Plane-local to global coordinate mapping."""

from __future__ import annotations

from ehouse_model.domain import Node2D, Node3D, PlaneSpec


def map_2d_to_3d(node: Node2D, plane: PlaneSpec) -> Node3D:
    """Map a face-local 2D node onto the global XYZ coordinate system."""
    origin = plane.origin
    local_x = plane.local_x_vector
    local_y = plane.local_y_vector

    return Node3D(
        id=node.id,
        x=origin[0] + node.x * local_x[0] + node.y * local_y[0],
        y=origin[1] + node.x * local_x[1] + node.y * local_y[1],
        z=origin[2] + node.x * local_x[2] + node.y * local_y[2],
    )
