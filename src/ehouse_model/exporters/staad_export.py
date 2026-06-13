"""STAAD.Pro geometry-only exporter."""

from __future__ import annotations

from pathlib import Path

from ehouse_model.global_model_types import GlobalModel


def export_staad_geometry(model: GlobalModel, path: str | Path) -> None:
    """Export nodes and member incidences as a minimal STAAD SPACE file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    node_numbers = {node.id: index for index, node in enumerate(model.nodes, start=1)}
    lines = ["STAAD SPACE", "UNIT METER KN", "JOINT COORDINATES"]

    for node in model.nodes:
        node_number = node_numbers[node.id]
        lines.append(
            f"{node_number} {_format_float(node.x)} {_format_float(node.y)} {_format_float(node.z)};"
        )

    lines.append("MEMBER INCIDENCES")
    for member_number, member in enumerate(model.members, start=1):
        lines.append(
            f"{member_number} {node_numbers[member.start_node_id]} {node_numbers[member.end_node_id]};"
        )

    lines.append("FINISH")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_float(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in ("", "-0"):
        return "0"
    return text
