import csv
from collections import Counter

import ezdxf
import pytest

from ehouse_model.dxf_preprocessor import DxfPreprocessModel, PreprocessOptions, preprocess_dxf
from ehouse_model.dxf_reader import read_dxf_segments
from ehouse_model.base_processing import snap_extend_centerlines
from ehouse_model.face_extractor import extract_centerline_candidates
from ehouse_model.face_topology import build_face_topology


def test_preprocess_filters_default_layers_and_non_line_entities(tmp_path):
    dxf_path = tmp_path / "t1161_style.dxf"
    doc = ezdxf.new("R2010")
    _ensure_layers(doc, ["0", "3中心线层", "4虚线层", "2细线层"])
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 10), (100, 10), dxfattribs={"layer": "3中心线层"})
    modelspace.add_line((0, 20), (100, 20), dxfattribs={"layer": "4虚线层"})
    modelspace.add_line((0, 30), (100, 30), dxfattribs={"layer": "2细线层"})
    modelspace.add_circle((5, 5), 1, dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    assert len(cleaned_segments) == 1
    assert cleaned_segments[0].layer == "0"
    assert cleaned_segments[0].start == pytest.approx((0.0, 0.0))
    assert cleaned_segments[0].end == pytest.approx((100.0, 0.0))
    assert result.non_line_entity_count == 1
    assert result.removed_segment_count == 3
    assert result.output_segment_count == 1

    reasons = Counter(record.reason for record in result.report_records)
    assert reasons["removed_layer_keyword"] == 3
    assert reasons["removed_non_line_entity"] == 1

    with result.report_csv_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert any(row["reason"] == "removed_layer_keyword" for row in rows)
    assert any(row["reason"] == "removed_non_line_entity" for row in rows)


def test_preprocess_model_reports_layer_stats(tmp_path):
    dxf_path = tmp_path / "layer_stats.dxf"
    doc = ezdxf.new("R2010")
    _ensure_layers(doc, ["0", "CENTER"])
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 10), (100, 10), dxfattribs={"layer": "CENTER"})
    modelspace.add_circle((0, 0), 5, dxfattribs={"layer": "CENTER"})
    doc.saveas(dxf_path)

    model = DxfPreprocessModel.load(dxf_path)

    stats = {stat.layer: stat for stat in model.layer_stats}
    assert stats["0"].entity_count == 1
    assert stats["0"].segment_count == 1
    assert stats["CENTER"].entity_count == 2
    assert stats["CENTER"].segment_count == 1
    assert "CIRCLE:1" in stats["CENTER"].entity_types
    assert "LINE:1" in stats["CENTER"].entity_types


def test_preprocess_model_defaults_to_recognition_segments_only(tmp_path):
    dxf_path = tmp_path / "recognition_workspace.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_lwpolyline([(0, 10), (100, 10), (100, 60)], dxfattribs={"layer": "0"})
    modelspace.add_circle((20, 20), 5, dxfattribs={"layer": "0"})
    modelspace.add_arc((40, 40), 10, 0, 90, dxfattribs={"layer": "0"})
    modelspace.add_text("note", dxfattribs={"layer": "TEXT"})
    doc.saveas(dxf_path)

    model = DxfPreprocessModel.load(dxf_path)

    assert model.original_entity_count == 5
    assert model.current_segment_count == 3
    assert model.non_line_entity_count == 3
    assert model.non_line_type_summary == "ARC:1, CIRCLE:1, TEXT:1"

    clean_path = tmp_path / "default_clean.dxf"
    report_path = tmp_path / "default_report.csv"
    model.save_clean_dxf(clean_path)
    model.save_report_csv(report_path)

    clean_doc = ezdxf.readfile(clean_path)
    assert Counter(entity.dxftype() for entity in clean_doc.modelspace()) == {"LINE": 3}

    with report_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    reasons = Counter(row["reason"] for row in rows)
    assert reasons["removed_non_line_entity"] == 3


def test_preprocess_model_preview_apply_discard_and_undo(tmp_path):
    dxf_path = tmp_path / "interactive_layers.dxf"
    doc = ezdxf.new("R2010")
    _ensure_layers(doc, ["0", "NOISE"])
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 10), (100, 10), dxfattribs={"layer": "NOISE"})
    doc.saveas(dxf_path)

    model = DxfPreprocessModel.load(dxf_path)
    preview = model.preview_layer_extract(["0"])

    assert model.current_segment_count == 2
    assert len(preview.output_segments) == 1
    assert len(preview.removed_segments) == 1

    model.apply_preview(preview)
    assert model.current_segment_count == 1
    assert len(model.applied_records) == 1

    assert model.undo()
    assert model.current_segment_count == 2
    assert model.applied_records == []

    model.apply_preview(preview)
    model.reset()
    assert model.current_segment_count == 2
    assert model.applied_records == []


def test_preprocess_model_each_preview_is_independent(tmp_path):
    dxf_path = tmp_path / "interactive_operations.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (50, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((45, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 0), (100, 100), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    model = DxfPreprocessModel.load(dxf_path)
    axis_preview = model.preview_keep_axis_aligned()
    merge_preview = model.preview_merge_collinear(gap_tolerance=5.0)

    assert model.current_segment_count == 3
    assert len(axis_preview.output_segments) == 2
    assert len(axis_preview.removed_segments) == 1
    assert len(merge_preview.output_segments) == 2
    assert len(merge_preview.removed_segments) == 2


def test_preprocess_model_saves_clean_dxf_and_workspace_overlay(tmp_path):
    dxf_path = tmp_path / "save_workspace.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 10), (100, 10), dxfattribs={"layer": "NOISE"})
    doc.saveas(dxf_path)

    model = DxfPreprocessModel.load(dxf_path)
    preview = model.preview_layer_extract(["0"])
    model.apply_preview(preview)
    clean_path = tmp_path / "clean.dxf"
    overlay_path = tmp_path / "workspace_overlay.dxf"
    report_path = tmp_path / "report.csv"

    model.save_clean_dxf(clean_path)
    model.save_overlay_dxf(overlay_path, preview)
    model.save_report_csv(report_path)

    assert len(read_dxf_segments(clean_path)) == 1
    assert overlay_path.exists()
    with report_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["reason"] == "removed_layer_not_selected"


def test_preprocess_merges_collinear_overlaps_and_small_gaps(tmp_path):
    dxf_path = tmp_path / "fragmented_outline.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (50, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((45, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((104, 0), (150, 0), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path, options=PreprocessOptions(gap_tolerance=5.0))

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    assert len(cleaned_segments) == 1
    assert cleaned_segments[0].start == pytest.approx((0.0, 0.0))
    assert cleaned_segments[0].end == pytest.approx((150.0, 0.0))
    assert result.merged_group_count == 1
    assert Counter(record.status for record in result.report_records)["merged"] == 3


def test_preprocess_keeps_real_crossing_segments(tmp_path):
    dxf_path = tmp_path / "crossing_outline.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((50, -50), (50, 50), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    assert len(cleaned_segments) == 2
    assert result.removed_segment_count == 0
    assert result.cross_removed_segment_count == 0
    assert result.merged_group_count == 0


def test_preprocess_removes_cross_closure_lines_between_long_outlines(tmp_path):
    dxf_path = tmp_path / "cross_closure_lines.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (0, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((100, 0), (100, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 200), (100, 200), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 230), (100, 230), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    assert len(cleaned_segments) == 2
    assert {segment.start[0] for segment in cleaned_segments} == {0.0, 100.0}
    assert result.cross_removed_segment_count == 2

    reasons = Counter(record.reason for record in result.report_records)
    assert reasons["removed_cross_closure_line"] == 2
    assert reasons["kept_real_outline_edge"] == 2

    overlay_doc = ezdxf.readfile(result.overlay_dxf_path)
    overlay_layers = Counter(entity.dxf.layer for entity in overlay_doc.modelspace())
    assert overlay_layers["PREPROCESS_CROSS_REMOVED"] == 2


def test_preprocess_removes_short_crossing_stub(tmp_path):
    dxf_path = tmp_path / "short_crossing_stub.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (0, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((50, 0), (50, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 200), (100, 200), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    assert len(cleaned_segments) == 2
    assert result.cross_removed_segment_count == 1
    assert Counter(record.reason for record in result.report_records)["removed_short_crossing_stub"] == 1


def test_cross_closure_cleanup_prevents_extra_short_centerline(tmp_path):
    dxf_path = tmp_path / "extra_short_centerline.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (0, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((100, 0), (100, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 200), (100, 200), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 230), (100, 230), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    no_cleanup = preprocess_dxf(
        dxf_path,
        output_path=tmp_path / "no_cleanup.dxf",
        options=PreprocessOptions(cross_cleanup_enabled=False),
    )
    no_cleanup_candidates, no_cleanup_warnings = extract_centerline_candidates(
        read_dxf_segments(no_cleanup.clean_dxf_path)
    )
    assert no_cleanup_warnings == []
    assert len(no_cleanup_candidates) == 2

    cleaned = preprocess_dxf(dxf_path, output_path=tmp_path / "cleanup.dxf")
    cleaned_candidates, cleaned_warnings = extract_centerline_candidates(
        read_dxf_segments(cleaned.clean_dxf_path)
    )
    assert cleaned_warnings == []
    assert len(cleaned_candidates) == 1
    assert cleaned_candidates[0].start == pytest.approx((50.0, 0.0))
    assert cleaned_candidates[0].end == pytest.approx((50.0, 1000.0))


def test_overlap_trim_cuts_short_vertical_member_against_long_horizontal_member(tmp_path):
    dxf_path = tmp_path / "long_horizontal_short_vertical.dxf"
    _write_crossing_member_bands(
        dxf_path,
        horizontal_length=1000.0,
        vertical_length=500.0,
        horizontal_start_x=0.0,
        vertical_start_y=-200.0,
    )

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    horizontal_segments = [segment for segment in cleaned_segments if segment.start[1] == segment.end[1]]
    vertical_segments = [segment for segment in cleaned_segments if segment.start[0] == segment.end[0]]
    assert len(horizontal_segments) == 2
    assert len(vertical_segments) == 4
    assert result.overlap_trimmed_segment_count == 2

    vertical_intervals = sorted(
        (min(segment.start[1], segment.end[1]), max(segment.start[1], segment.end[1]))
        for segment in vertical_segments
    )
    assert vertical_intervals == pytest.approx(
        [(-200.0, 0.0), (-200.0, 0.0), (100.0, 300.0), (100.0, 300.0)]
    )
    assert Counter(record.reason for record in result.report_records)["trimmed_overlap_secondary_member"] == 2

    overlay_doc = ezdxf.readfile(result.overlay_dxf_path)
    overlay_layers = Counter(entity.dxf.layer for entity in overlay_doc.modelspace())
    assert overlay_layers["PREPROCESS_OVERLAP_TRIMMED"] == 2


def test_overlap_trim_cuts_short_horizontal_member_against_long_vertical_member(tmp_path):
    dxf_path = tmp_path / "long_vertical_short_horizontal.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (0, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((100, 0), (100, 1000), dxfattribs={"layer": "0"})
    modelspace.add_line((-200, 450), (300, 450), dxfattribs={"layer": "0"})
    modelspace.add_line((-200, 550), (300, 550), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    horizontal_segments = [segment for segment in cleaned_segments if segment.start[1] == segment.end[1]]
    vertical_segments = [segment for segment in cleaned_segments if segment.start[0] == segment.end[0]]
    assert len(vertical_segments) == 2
    assert len(horizontal_segments) == 4
    assert result.overlap_trimmed_segment_count == 2

    horizontal_intervals = sorted(
        (min(segment.start[0], segment.end[0]), max(segment.start[0], segment.end[0]))
        for segment in horizontal_segments
    )
    assert horizontal_intervals == pytest.approx(
        [(-200.0, 0.0), (-200.0, 0.0), (100.0, 300.0), (100.0, 300.0)]
    )


def test_overlap_trim_tie_breaker_keeps_horizontal_member(tmp_path):
    dxf_path = tmp_path / "close_length_members.dxf"
    _write_crossing_member_bands(
        dxf_path,
        horizontal_length=600.0,
        vertical_length=570.0,
        horizontal_start_x=0.0,
        vertical_start_y=-200.0,
    )

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    horizontal_segments = [segment for segment in cleaned_segments if segment.start[1] == segment.end[1]]
    vertical_segments = [segment for segment in cleaned_segments if segment.start[0] == segment.end[0]]
    assert len(horizontal_segments) == 2
    assert len(vertical_segments) == 4
    assert result.overlap_trimmed_segment_count == 2


def test_overlap_trim_removes_tiny_remainders(tmp_path):
    dxf_path = tmp_path / "tiny_remainders.dxf"
    _write_crossing_member_bands(
        dxf_path,
        horizontal_length=1000.0,
        vertical_length=310.0,
        horizontal_start_x=0.0,
        vertical_start_y=-10.0,
    )

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    vertical_segments = [segment for segment in cleaned_segments if segment.start[0] == segment.end[0]]
    assert len(vertical_segments) == 2
    assert sorted(
        (min(segment.start[1], segment.end[1]), max(segment.start[1], segment.end[1]))
        for segment in vertical_segments
    ) == pytest.approx([(100.0, 300.0), (100.0, 300.0)])
    reasons = Counter(record.reason for record in result.report_records)
    assert reasons["trimmed_overlap_secondary_member"] == 2
    assert reasons["removed_tiny_trim_fragment"] == 2


def test_overlap_trimmed_centerlines_can_still_snap_to_shared_node(tmp_path):
    dxf_path = tmp_path / "snap_after_overlap_trim.dxf"
    _write_crossing_member_bands(
        dxf_path,
        horizontal_length=1000.0,
        vertical_length=900.0,
        horizontal_start_x=0.0,
        vertical_start_y=-400.0,
    )

    result = preprocess_dxf(dxf_path)
    candidates, warnings = extract_centerline_candidates(read_dxf_segments(result.clean_dxf_path))
    snapped, _, snap_warnings = snap_extend_centerlines(candidates, tolerance=200.0)
    topology = build_face_topology(snapped)

    assert warnings == []
    assert snap_warnings
    assert any(node.x == pytest.approx(500.0) and node.y == pytest.approx(50.0) for node in topology.nodes)


def test_preprocess_removes_diagonal_from_kept_layer(tmp_path):
    dxf_path = tmp_path / "diagonal_noise.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((0, 0), (100, 100), dxfattribs={"layer": "0"})
    doc.saveas(dxf_path)

    result = preprocess_dxf(dxf_path)

    cleaned_segments = read_dxf_segments(result.clean_dxf_path)
    assert len(cleaned_segments) == 1
    assert cleaned_segments[0].start == pytest.approx((0.0, 0.0))
    assert cleaned_segments[0].end == pytest.approx((100.0, 0.0))
    assert Counter(record.reason for record in result.report_records)["removed_not_axis_aligned"] == 1


def _ensure_layers(doc, layer_names):
    for layer_name in layer_names:
        if layer_name not in doc.layers:
            doc.layers.add(layer_name)


def _write_crossing_member_bands(
    path,
    *,
    horizontal_length,
    vertical_length,
    horizontal_start_x,
    vertical_start_y,
):
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    horizontal_end_x = horizontal_start_x + horizontal_length
    vertical_end_y = vertical_start_y + vertical_length
    modelspace.add_line((horizontal_start_x, 0), (horizontal_end_x, 0), dxfattribs={"layer": "0"})
    modelspace.add_line((horizontal_start_x, 100), (horizontal_end_x, 100), dxfattribs={"layer": "0"})
    modelspace.add_line((450, vertical_start_y), (450, vertical_end_y), dxfattribs={"layer": "0"})
    modelspace.add_line((550, vertical_start_y), (550, vertical_end_y), dxfattribs={"layer": "0"})
    doc.saveas(path)
