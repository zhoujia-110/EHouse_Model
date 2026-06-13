"""Global node stitching for multi-face models."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ehouse_model.domain import Member3D, Node3D
from ehouse_model.face_model import WarningRecord
from ehouse_model.global_model_types import GlobalModel


@dataclass(frozen=True, slots=True)
class StitchOptions:
    merge_tolerance: float = 1.0
    review_tolerance: float = 5.0

    def __post_init__(self) -> None:
        if self.merge_tolerance < 0:
            raise ValueError("merge_tolerance cannot be negative")
        if self.review_tolerance < self.merge_tolerance:
            raise ValueError("review_tolerance must be greater than or equal to merge_tolerance")


@dataclass(slots=True)
class _NodeCluster:
    primary: Node3D
    source_node_ids: list[str]


def stitch_global_model(
    model: GlobalModel,
    options: StitchOptions | None = None,
) -> GlobalModel:
    """Merge close global nodes and remap member incidences."""
    opts = options or StitchOptions()
    clusters: list[_NodeCluster] = []
    node_replacements: dict[str, str] = {}
    warnings: list[WarningRecord] = list(model.warnings)

    for node in model.nodes:
        match = _find_cluster(clusters, node, opts.merge_tolerance)
        if match is None:
            clusters.append(_NodeCluster(primary=node, source_node_ids=[node.id]))
            node_replacements[node.id] = node.id
            continue

        match.source_node_ids.append(node.id)
        node_replacements[node.id] = match.primary.id
        warnings.append(
            WarningRecord(
                level="info",
                code="stitched_nodes",
                message="Nodes were merged within the stitching tolerance.",
                entity_id=",".join(match.source_node_ids),
            )
        )

    warnings.extend(_find_near_miss_warnings(clusters, opts))

    stitched_members: list[Member3D] = []
    member_sources: dict[str, dict[str, str]] = {}
    seen_incidences: set[tuple[str, str]] = set()

    for member in model.members:
        start_node_id = node_replacements[member.start_node_id]
        end_node_id = node_replacements[member.end_node_id]
        if start_node_id == end_node_id:
            warnings.append(
                WarningRecord(
                    level="warning",
                    code="zero_length_member_removed",
                    message="A member became zero-length after node stitching and was removed.",
                    entity_id=member.id,
                )
            )
            continue

        incidence_key = tuple(sorted((start_node_id, end_node_id)))
        if incidence_key in seen_incidences:
            warnings.append(
                WarningRecord(
                    level="info",
                    code="duplicate_member_removed",
                    message="A duplicate member incidence was removed after node stitching.",
                    entity_id=member.id,
                )
            )
            continue
        seen_incidences.add(incidence_key)

        stitched_member = Member3D(
            id=member.id,
            start_node_id=start_node_id,
            end_node_id=end_node_id,
        )
        stitched_members.append(stitched_member)
        member_sources[stitched_member.id] = dict(model.member_sources.get(member.id, {}))

    node_sources = {
        cluster.primary.id: _merged_node_source(model, cluster)
        for cluster in clusters
    }

    return GlobalModel(
        project_name=model.project_name,
        nodes=tuple(cluster.primary for cluster in clusters),
        members=tuple(stitched_members),
        node_sources=node_sources,
        member_sources=member_sources,
        warnings=_renumber_warnings(warnings),
    )


def _find_cluster(
    clusters: list[_NodeCluster],
    node: Node3D,
    tolerance: float,
) -> _NodeCluster | None:
    for cluster in clusters:
        if _distance_3d(cluster.primary, node) <= tolerance:
            return cluster
    return None


def _find_near_miss_warnings(
    clusters: list[_NodeCluster],
    options: StitchOptions,
) -> list[WarningRecord]:
    warnings: list[WarningRecord] = []
    for left_index, left in enumerate(clusters):
        for right in clusters[left_index + 1 :]:
            distance = _distance_3d(left.primary, right.primary)
            if options.merge_tolerance < distance <= options.review_tolerance:
                warnings.append(
                    WarningRecord(
                        level="warning",
                        code="node_near_miss",
                        message="Nodes are near each other but outside the automatic stitching tolerance.",
                        entity_id=f"{left.primary.id},{right.primary.id}",
                    )
                )
    return warnings


def _merged_node_source(model: GlobalModel, cluster: _NodeCluster) -> dict[str, str]:
    source = dict(model.node_sources.get(cluster.primary.id, {}))
    source["merged_node_ids"] = ",".join(cluster.source_node_ids)
    return source


def _renumber_warnings(warnings: list[WarningRecord]) -> tuple[WarningRecord, ...]:
    return tuple(
        warning.with_id(f"W{index}")
        for index, warning in enumerate(warnings, start=1)
    )


def _distance_3d(left: Node3D, right: Node3D) -> float:
    return math.sqrt(
        (left.x - right.x) ** 2
        + (left.y - right.y) ** 2
        + (left.z - right.z) ** 2
    )
