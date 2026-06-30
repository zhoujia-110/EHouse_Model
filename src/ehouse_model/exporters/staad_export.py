"""STAAD.Pro geometry-only exporter."""

from __future__ import annotations

from pathlib import Path

from ehouse_model.global_model_types import GlobalModel


def export_staad_geometry(model: GlobalModel, path: str | Path) -> None:
    """Export nodes and member incidences as a minimal STAAD SPACE file."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    node_numbers = _staad_number_map([node.id for node in model.nodes])
    member_numbers = _staad_number_map([member.id for member in model.members])
    lines = ["STAAD SPACE", "UNIT METER KN", "JOINT COORDINATES"]

    for node in model.nodes:
        node_number = node_numbers[node.id]
        lines.append(
            f"{node_number} {_format_float(node.x)} {_format_float(node.y)} {_format_float(node.z)};"
        )

    lines.append("MEMBER INCIDENCES")
    for member in model.members:
        member_number = member_numbers[member.id]
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


def _staad_number_map(ids: list[str]) -> dict[str, int]:
    numeric_ids = [_positive_int_or_none(value) for value in ids]
    if all(value is not None for value in numeric_ids) and len(set(numeric_ids)) == len(numeric_ids):
        return {raw_id: int(number) for raw_id, number in zip(ids, numeric_ids)}
    return {raw_id: index for index, raw_id in enumerate(ids, start=1)}


def _positive_int_or_none(value: str) -> int | None:
    text = str(value).strip()
    if not text.isdigit():
        return None
    number = int(text)
    if number <= 0:
        return None
    return number
