"""project.yaml loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ehouse_model.domain import PlaneSpec, StitchRule


@dataclass(frozen=True, slots=True)
class ProjectSpec:
    path: Path
    planes: dict[str, PlaneSpec]
    stitch_rules: tuple[StitchRule, ...]

    def plane(self, name: str) -> PlaneSpec:
        return self.planes[name]


def load_project(path: str | Path = "project.yaml") -> ProjectSpec:
    """Load and validate project.yaml without reading DXF geometry."""
    project_path = Path(path)
    with project_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    if not isinstance(raw, dict):
        raise ValueError("project.yaml must contain a mapping at the top level")

    planes = _parse_planes(raw.get("planes"))
    stitch_rules = _parse_stitch_rules(raw.get("stitch_rules", []), planes)

    return ProjectSpec(
        path=project_path,
        planes=planes,
        stitch_rules=tuple(stitch_rules),
    )


def _parse_planes(raw: Any) -> dict[str, PlaneSpec]:
    if raw is None:
        raise ValueError("project.yaml must define planes")

    planes: dict[str, PlaneSpec] = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, list):
        items = []
        for index, value in enumerate(raw):
            if not isinstance(value, dict):
                raise ValueError(f"planes[{index}] must be a mapping")
            if "name" not in value:
                raise ValueError(f"planes[{index}] must define name")
            items.append((value["name"], value))
    else:
        raise ValueError("planes must be a mapping or a list")

    for name, value in items:
        if not isinstance(value, dict):
            raise ValueError(f"plane {name!r} must be a mapping")

        plane = PlaneSpec(
            name=str(name),
            dxf_path=value.get("dxf_path", value.get("dxf")),
            origin=value.get("origin", (0.0, 0.0, 0.0)),
            local_x_axis=value.get("local_x_axis", value.get("x_axis", "X")),
            local_y_axis=value.get("local_y_axis", value.get("y_axis", "Y")),
        )

        if plane.name in planes:
            raise ValueError(f"duplicate plane name {plane.name!r}")
        planes[plane.name] = plane

    if not planes:
        raise ValueError("project.yaml must define at least one plane")
    return planes


def _parse_stitch_rules(raw: Any, planes: dict[str, PlaneSpec]) -> list[StitchRule]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("stitch_rules must be a list")

    rules: list[StitchRule] = []
    for index, value in enumerate(raw):
        if not isinstance(value, dict):
            raise ValueError(f"stitch_rules[{index}] must be a mapping")

        rule = StitchRule(
            source_plane=value.get("source_plane"),
            target_plane=value.get("target_plane"),
            source_edge=value.get("source_edge"),
            target_edge=value.get("target_edge"),
            tolerance=value.get("tolerance", 0.001),
        )

        missing_planes = [
            plane_name
            for plane_name in (rule.source_plane, rule.target_plane)
            if plane_name not in planes
        ]
        if missing_planes:
            joined = ", ".join(repr(plane_name) for plane_name in missing_planes)
            raise ValueError(f"stitch_rules[{index}] references unknown plane(s): {joined}")

        rules.append(rule)
    return rules
