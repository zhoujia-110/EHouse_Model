import pytest

from ehouse_model.centerline_cleanup import (
    CenterlineCleanupOptions,
    merge_collinear_centerlines,
    realign_centerline_cluster_near_points,
    supplement_short_member_centerlines,
)
from ehouse_model.dxf_reader import DxfSegment2D
from ehouse_model.face_model import CenterlineCandidate


def test_merge_collinear_centerlines_merges_overlapping_candidates():
    left = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(1000, 0),
        source_segment_ids=("A", "B"),
        width=200,
        overlap=1000,
    )
    right = CenterlineCandidate(
        id="C2",
        start=(700, 0.5),
        end=(1500, 0.5),
        source_segment_ids=("C", "D"),
        width=204,
        overlap=800,
    )

    result = merge_collinear_centerlines([left, right])

    assert result.merged_group_count == 1
    assert result.removed_candidate_count == 1
    assert result.warnings[0].code == "centerline_collinear_candidates_merged"
    assert len(result.centerlines) == 1
    merged = result.centerlines[0]
    assert merged.id == "C1"
    assert merged.kind == "merged_collinear_centerline"
    assert merged.start == pytest.approx((0, 0))
    assert merged.end == pytest.approx((1500, 0))
    assert merged.width == pytest.approx((200 * 1000 + 204 * 800) / 1800)


def test_merge_collinear_centerlines_keeps_large_gap_separate():
    left = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(1000, 0),
        source_segment_ids=("A", "B"),
        width=200,
        overlap=1000,
    )
    right = CenterlineCandidate(
        id="C2",
        start=(1020, 0),
        end=(1500, 0),
        source_segment_ids=("C", "D"),
        width=200,
        overlap=480,
    )

    result = merge_collinear_centerlines(
        [left, right],
        CenterlineCleanupOptions(overlap_gap_tolerance=5),
    )

    assert result.merged_group_count == 0
    assert result.centerlines == (left, right)


def test_merge_collinear_centerlines_keeps_different_widths_separate():
    left = CenterlineCandidate(
        id="C1",
        start=(0, 0),
        end=(1000, 0),
        source_segment_ids=("A", "B"),
        width=100,
        overlap=1000,
    )
    right = CenterlineCandidate(
        id="C2",
        start=(700, 0),
        end=(1500, 0),
        source_segment_ids=("C", "D"),
        width=200,
        overlap=800,
    )

    result = merge_collinear_centerlines([left, right])

    assert result.merged_group_count == 0
    assert result.centerlines == (left, right)


def test_short_member_patch_adds_short_wide_ratio_centerline_near_point():
    segments = [
        DxfSegment2D(id="L", start=(0, 0), end=(0, 105), layer="0", entity_type="LINE"),
        DxfSegment2D(id="R", start=(50, 0), end=(50, 105), layer="0", entity_type="LINE"),
    ]

    result = supplement_short_member_centerlines(
        segments,
        [],
        [(25, 50)],
        CenterlineCleanupOptions(short_member_radius=120),
    )

    assert result.added_count == 1
    assert result.warnings[-1].code == "short_member_patch_centerlines_added"
    candidate = result.centerlines[0]
    assert candidate.kind == "short_member_patch"
    assert candidate.source_segment_ids == ("L", "R")
    assert candidate.start == pytest.approx((25, 0))
    assert candidate.end == pytest.approx((25, 105))


def test_short_member_patch_adds_horizontal_connector_between_centerline_gaps():
    existing = [
        CenterlineCandidate(
            id="C1",
            start=(0, 0),
            end=(100, 0),
            source_segment_ids=("A", "B"),
            width=50,
            overlap=100,
        ),
        CenterlineCandidate(
            id="C2",
            start=(175, 0),
            end=(400, 0),
            source_segment_ids=("C", "D"),
            width=50,
            overlap=225,
        ),
    ]

    result = supplement_short_member_centerlines(
        [],
        existing,
        [(130, 0)],
        CenterlineCleanupOptions(short_member_radius=120, short_member_max_length=100),
    )

    assert result.added_count == 1
    connector = result.centerlines[-1]
    assert connector.kind == "short_member_connector_patch"
    assert connector.source_segment_ids == ("C1", "C2")
    assert connector.start == pytest.approx((100, 0))
    assert connector.end == pytest.approx((175, 0))


def test_cluster_realign_replaces_greedy_misaligned_nearby_pairs():
    segments = [
        DxfSegment2D(id="wide_r", start=(14618.5, 1481.7), end=(14618.5, 4841.7), layer="0", entity_type="LINE"),
        DxfSegment2D(id="wide_l", start=(14418.5, 1481.7), end=(14418.5, 4841.7), layer="0", entity_type="LINE"),
        DxfSegment2D(id="thin_l", start=(14318.5, 2927.0), end=(14318.5, 1481.7), layer="0", entity_type="LINE"),
        DxfSegment2D(id="thin_r", start=(14368.5, 2927.0), end=(14368.5, 1481.7), layer="0", entity_type="LINE"),
    ]
    wrong_existing = [
        CenterlineCandidate(
            id="C1",
            start=(14393.5, 1481.7),
            end=(14393.5, 2927.0),
            source_segment_ids=("wide_l", "thin_r"),
            width=50,
            overlap=1445.3,
        ),
        CenterlineCandidate(
            id="C2",
            start=(14468.5, 1481.7),
            end=(14468.5, 2927.0),
            source_segment_ids=("wide_r", "thin_l"),
            width=300,
            overlap=1445.3,
        ),
    ]

    result = realign_centerline_cluster_near_points(
        segments,
        wrong_existing,
        [(14420, 2200)],
        CenterlineCleanupOptions(cluster_realign_radius=500),
    )

    assert result.replaced_group_count == 1
    assert result.removed_count == 2
    assert result.added_count == 2
    source_sets = {frozenset(candidate.source_segment_ids) for candidate in result.centerlines}
    assert source_sets == {
        frozenset(("thin_l", "thin_r")),
        frozenset(("wide_r", "wide_l")),
    }
    centers = sorted(round((candidate.start[0] + candidate.end[0]) / 2, 1) for candidate in result.centerlines)
    assert centers == [14343.5, 14518.5]
