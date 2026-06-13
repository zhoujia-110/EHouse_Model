"""CSV exporters for global model intermediate files."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.face_model import WarningRecord

NODE_CSV_FIELDS = ("id", "x", "y", "z")
MEMBER_CSV_FIELDS = ("id", "start_node_id", "end_node_id")
WARNING_CSV_FIELDS = ("id", "level", "code", "message", "entity_id")


def export_nodes_csv(nodes: Iterable[Node3D], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=NODE_CSV_FIELDS)
        writer.writeheader()
        for node in nodes:
            writer.writerow(
                {
                    "id": node.id,
                    "x": _format_float(node.x),
                    "y": _format_float(node.y),
                    "z": _format_float(node.z),
                }
            )


def export_members_csv(members: Iterable[Member3D], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=MEMBER_CSV_FIELDS)
        writer.writeheader()
        for member in members:
            writer.writerow(
                {
                    "id": member.id,
                    "start_node_id": member.start_node_id,
                    "end_node_id": member.end_node_id,
                }
            )


def export_warnings_csv(warnings: Iterable[WarningRecord], path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=WARNING_CSV_FIELDS)
        writer.writeheader()
        for warning in warnings:
            writer.writerow(
                {
                    "id": warning.id,
                    "level": warning.level,
                    "code": warning.code,
                    "message": warning.message,
                    "entity_id": warning.entity_id or "",
                }
            )


def _format_float(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    if text in ("", "-0"):
        return "0"
    return text
