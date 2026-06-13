"""DXF IO helpers for preprocessed single-face drawings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import ezdxf

Point2D = tuple[float, float]


@dataclass(frozen=True, slots=True)
class DxfSegment2D:
    """A straight 2D segment read from LINE or LWPOLYLINE geometry."""

    id: str
    start: Point2D
    end: Point2D
    layer: str
    entity_type: str


def read_dxf_segments(path: str | Path) -> list[DxfSegment2D]:
    """Read LINE and LWPOLYLINE entities as 2D straight segments."""
    doc = ezdxf.readfile(path)
    segments: list[DxfSegment2D] = []

    for entity in doc.modelspace():
        entity_type = entity.dxftype()
        if entity_type == "LINE":
            start = (float(entity.dxf.start.x), float(entity.dxf.start.y))
            end = (float(entity.dxf.end.x), float(entity.dxf.end.y))
            _append_segment(
                segments,
                start=start,
                end=end,
                layer=str(entity.dxf.layer),
                entity_type=entity_type,
                handle=str(entity.dxf.handle),
                part_index=0,
            )
        elif entity_type == "LWPOLYLINE":
            points = [(float(x), float(y)) for x, y in entity.get_points("xy")]
            _append_polyline_segments(
                segments,
                points=points,
                closed=bool(entity.closed),
                layer=str(entity.dxf.layer),
                entity_type=entity_type,
                handle=str(entity.dxf.handle),
            )

    return segments


def write_overlay_dxf(
    path: str | Path,
    outline_segments: Iterable[DxfSegment2D],
    centerline_segments: Iterable[tuple[Point2D, Point2D]],
) -> None:
    """Write a simple overlay DXF containing source outlines and centerlines."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new("R2010")
    _ensure_layer(doc, "OUTLINE_INPUT", color=8)
    _ensure_layer(doc, "CENTERLINE_CANDIDATE", color=1)

    modelspace = doc.modelspace()
    for segment in outline_segments:
        modelspace.add_line(
            segment.start,
            segment.end,
            dxfattribs={"layer": "OUTLINE_INPUT", "color": 8},
        )

    for start, end in centerline_segments:
        modelspace.add_line(
            start,
            end,
            dxfattribs={"layer": "CENTERLINE_CANDIDATE", "color": 1},
        )

    doc.saveas(output_path)


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


def _ensure_layer(doc: ezdxf.document.Drawing, name: str, *, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)
