"""Import minimal STAAD.Pro geometry into the project part format."""

from __future__ import annotations

from pathlib import Path
import re

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.exporters.staad_export import export_staad_geometry
from ehouse_model.face_model import WarningRecord
from ehouse_model.global_model_types import GlobalModel
from ehouse_model.part_geometry import PartGeometry, PartGeometrySource

_SECTION_NONE = "none"
_SECTION_NODES = "nodes"
_SECTION_MEMBERS = "members"


def import_staad_part_geometry(
    path: str | Path,
    *,
    part_id: str,
    part_type: str,
) -> PartGeometry:
    """Parse JOINT COORDINATES and MEMBER INCIDENCES from a STD file."""
    input_path = Path(path)
    text = input_path.read_text(encoding="utf-8", errors="ignore")
    section = _SECTION_NONE
    length_unit = "METER"
    unit_scale = 1.0
    nodes: list[Node3D] = []
    members: list[Member3D] = []
    warnings: list[WarningRecord] = []

    for raw_line in _logical_lines(text):
        line = raw_line.strip()
        if not line:
            continue

        upper = line.upper()
        if upper.startswith("*"):
            continue
        if upper.startswith("UNIT "):
            tokens = upper.split()
            if len(tokens) >= 2:
                length_unit = tokens[1]
                unit_scale = _length_unit_scale(length_unit)
            continue
        if upper.startswith("JOINT COORDINATES"):
            section = _SECTION_NODES
            continue
        if upper.startswith("MEMBER INCIDENCES"):
            section = _SECTION_MEMBERS
            continue
        if upper.startswith("FINISH"):
            break
        if _starts_non_geometry_section(upper):
            section = _SECTION_NONE
            continue

        if section == _SECTION_NODES:
            node = _parse_node_line(line, unit_scale)
            if node is not None:
                nodes.append(node)
            continue
        if section == _SECTION_MEMBERS:
            member = _parse_member_line(line)
            if member is not None:
                members.append(member)

    if not nodes:
        warnings.append(
            WarningRecord(
                level="warning",
                code="std_no_nodes",
                message="No JOINT COORDINATES were found in the imported STD file.",
            )
        )
    if not members:
        warnings.append(
            WarningRecord(
                level="warning",
                code="std_no_members",
                message="No MEMBER INCIDENCES were found in the imported STD file.",
            )
        )

    return PartGeometry(
        part_id=part_id,
        part_type=part_type,
        source=PartGeometrySource(
            kind="imported_modified_std",
            path=str(input_path),
            description=f"Imported from STD with length unit {length_unit}.",
        ),
        nodes=tuple(nodes),
        members=tuple(members),
        warnings=tuple(warnings),
    )


def export_part_staad_geometry(part: PartGeometry, path: str | Path) -> None:
    """Export one confirmed part as a geometry-only STD file."""
    export_staad_geometry(
        GlobalModel(
            project_name=part.part_id,
            nodes=part.nodes,
            members=part.members,
            warnings=part.warnings,
        ),
        path,
    )


def _logical_lines(text: str) -> list[str]:
    normalized = text.replace(";", ";\n")
    return [line.rstrip(";") for line in normalized.splitlines()]


def _length_unit_scale(unit: str) -> float:
    if unit in {"METER", "METERS", "METRE", "METRES"}:
        return 1.0
    if unit in {"MMS", "MM"}:
        return 0.001
    if unit in {"CMS", "CM"}:
        return 0.01
    raise ValueError(f"unsupported STAAD length unit {unit!r}")


def _starts_non_geometry_section(upper_line: str) -> bool:
    prefixes = (
        "MEMBER PROPERTY",
        "CONSTANTS",
        "DEFINE ",
        "SUPPORTS",
        "LOAD ",
        "PERFORM ",
        "PARAMETER",
        "CHECK ",
    )
    return upper_line.startswith(prefixes)


def _parse_node_line(line: str, unit_scale: float) -> Node3D | None:
    tokens = _numeric_tokens(line)
    if len(tokens) < 4:
        return None
    node_id = _clean_id(tokens[0])
    return Node3D(
        id=node_id,
        x=float(tokens[1]) * unit_scale,
        y=float(tokens[2]) * unit_scale,
        z=float(tokens[3]) * unit_scale,
    )


def _parse_member_line(line: str) -> Member3D | None:
    tokens = _numeric_tokens(line)
    if len(tokens) < 3:
        return None
    return Member3D(
        id=_clean_id(tokens[0]),
        start_node_id=_clean_id(tokens[1]),
        end_node_id=_clean_id(tokens[2]),
    )


def _numeric_tokens(line: str) -> list[str]:
    return re.findall(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?", line)


def _clean_id(token: str) -> str:
    value = float(token)
    if value.is_integer():
        return str(int(value))
    return token
