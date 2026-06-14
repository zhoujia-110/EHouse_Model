import json
import csv

import ezdxf
import pytest

from ehouse_model.face_extractor import (
    FaceExtractionOptions,
    extract_centerline_candidates,
    extract_face,
)
from ehouse_model.dxf_reader import DxfSegment2D


def test_extract_face_from_line_rectangle_outputs_json_and_overlay(tmp_path):
    dxf_path = tmp_path / "beam_outline.dxf"
    _write_line_rectangle(dxf_path)

    face_model_path = tmp_path / "face_model.json"
    overlay_path = tmp_path / "overlay.dxf"
    warnings_path = tmp_path / "warnings.csv"
    model = extract_face(
        dxf_path,
        face_model_path=face_model_path,
        overlay_path=overlay_path,
        warnings_csv_path=warnings_path,
    )

    assert len(model.nodes) == 2
    assert len(model.members) == 1
    assert len(model.centerline_candidates) == 1
    assert model.centerline_candidates[0].width == pytest.approx(10.0)
    assert model.centerline_candidates[0].start == pytest.approx((0.0, 5.0))
    assert model.centerline_candidates[0].end == pytest.approx((100.0, 5.0))

    data = json.loads(face_model_path.read_text(encoding="utf-8"))
    assert data["nodes"] == [
        {"id": "N1", "x": 0.0, "y": 5.0},
        {"id": "N2", "x": 100.0, "y": 5.0},
    ]
    assert data["schema_version"] == 2
    assert data["members"] == [
        {
            "id": "M1",
            "start_node_id": "N1",
            "end_node_id": "N2",
            "source_candidate_id": "C1",
        }
    ]
    assert len(data["centerline_candidates"][0]["source_segment_ids"]) == 2
    assert data["centerline_candidates"][0]["kind"] == "outline_member"
    assert overlay_path.exists()
    assert warnings_path.exists()


def test_extract_face_reads_closed_lwpolyline(tmp_path):
    dxf_path = tmp_path / "polyline_beam_outline.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_lwpolyline([(0, 0), (100, 0), (100, 10), (0, 10)], close=True)
    doc.saveas(dxf_path)

    model = extract_face(
        dxf_path,
        face_model_path=tmp_path / "face_model.json",
        overlay_path=tmp_path / "overlay.dxf",
        warnings_csv_path=tmp_path / "warnings.csv",
    )

    assert len(model.members) == 1
    assert model.centerline_candidates[0].start == pytest.approx((0.0, 5.0))
    assert model.centerline_candidates[0].end == pytest.approx((100.0, 5.0))


def test_extract_face_uses_max_pair_width_override(tmp_path):
    dxf_path = tmp_path / "wide_beam_outline.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (10, 0))
    modelspace.add_line((0, 5), (10, 5))
    doc.saveas(dxf_path)

    default_model = extract_face(
        dxf_path,
        face_model_path=tmp_path / "default_face_model.json",
        overlay_path=tmp_path / "default_overlay.dxf",
        warnings_csv_path=tmp_path / "default_warnings.csv",
    )
    assert default_model.members == ()
    assert default_model.warnings[0].code == "no_centerline_candidates"

    relaxed_model = extract_face(
        dxf_path,
        face_model_path=tmp_path / "relaxed_face_model.json",
        overlay_path=tmp_path / "relaxed_overlay.dxf",
        warnings_csv_path=tmp_path / "relaxed_warnings.csv",
        options=FaceExtractionOptions(max_pair_width=6.0, max_pair_width_to_length_ratio=0.6),
    )
    assert len(relaxed_model.members) == 1
    assert relaxed_model.centerline_candidates[0].start == pytest.approx((0.0, 2.5))
    assert relaxed_model.centerline_candidates[0].end == pytest.approx((10.0, 2.5))

    capped_model = extract_face(
        dxf_path,
        face_model_path=tmp_path / "capped_face_model.json",
        overlay_path=tmp_path / "capped_overlay.dxf",
        warnings_csv_path=tmp_path / "capped_warnings.csv",
        options=FaceExtractionOptions(max_pair_width=4.0, max_pair_width_to_length_ratio=1.0),
    )
    assert capped_model.members == ()
    assert capped_model.warnings[0].code == "no_centerline_candidates"


def test_centerline_pairing_reuses_long_outline_on_disjoint_intervals():
    segments = [
        DxfSegment2D(id="S1", start=(0, 0), end=(200, 0), layer="0", entity_type="LINE"),
        DxfSegment2D(id="S2", start=(0, 10), end=(80, 10), layer="0", entity_type="LINE"),
        DxfSegment2D(id="S3", start=(120, 10), end=(200, 10), layer="0", entity_type="LINE"),
    ]

    candidates, warnings = extract_centerline_candidates(segments)

    assert warnings == []
    assert len(candidates) == 2
    assert candidates[0].start == pytest.approx((0, 5.0))
    assert candidates[0].end == pytest.approx((80, 5.0))
    assert candidates[1].start == pytest.approx((120, 5.0))
    assert candidates[1].end == pytest.approx((200, 5.0))


def test_centerline_pairing_normalizes_nearly_vertical_reversed_edges():
    segments = [
        DxfSegment2D(id="S1", start=(0, 0), end=(0, 100), layer="0", entity_type="LINE"),
        DxfSegment2D(
            id="S2",
            start=(10, 100),
            end=(10 + 1e-12, 0),
            layer="0",
            entity_type="LINE",
        ),
    ]

    candidates, warnings = extract_centerline_candidates(segments)

    assert warnings == []
    assert len(candidates) == 1
    assert candidates[0].start == pytest.approx((5.0, 0.0))
    assert candidates[0].end == pytest.approx((5.0, 100.0))


def test_centerline_pairing_rejects_nearly_duplicate_zero_width_edges():
    segments = [
        DxfSegment2D(id="L1", start=(0, 0), end=(0, 200), layer="0", entity_type="LINE"),
        DxfSegment2D(id="L2", start=(0.001, 0), end=(0.001, 200), layer="0", entity_type="LINE"),
        DxfSegment2D(id="R1", start=(50, 0), end=(50, 200), layer="0", entity_type="LINE"),
        DxfSegment2D(id="R2", start=(50.001, 0), end=(50.001, 200), layer="0", entity_type="LINE"),
    ]

    candidates, warnings = extract_centerline_candidates(segments)

    assert warnings == []
    assert len(candidates) == 1
    assert candidates[0].width == pytest.approx(49.999, abs=0.002)
    assert candidates[0].start[0] == pytest.approx(25.0, abs=0.001)


def test_extract_face_splits_intersecting_centerlines_into_shared_node(tmp_path):
    dxf_path = tmp_path / "crossing_beams.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0))
    modelspace.add_line((0, 10), (100, 10))
    modelspace.add_line((40, -20), (40, 30))
    modelspace.add_line((50, -20), (50, 30))
    doc.saveas(dxf_path)

    model = extract_face(
        dxf_path,
        face_model_path=tmp_path / "face_model.json",
        overlay_path=tmp_path / "overlay.dxf",
        warnings_csv_path=tmp_path / "warnings.csv",
    )

    assert len(model.centerline_candidates) == 2
    assert len(model.nodes) == 5
    assert len(model.members) == 4
    assert [(node.x, node.y) for node in model.nodes] == pytest.approx(
        [
            (0.0, 5.0),
            (45.0, 5.0),
            (100.0, 5.0),
            (45.0, -20.0),
            (45.0, 30.0),
        ]
    )


def test_extract_face_writes_structured_warnings_csv(tmp_path):
    dxf_path = tmp_path / "too_wide.dxf"
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (10, 0))
    modelspace.add_line((0, 5), (10, 5))
    doc.saveas(dxf_path)

    warnings_path = tmp_path / "warnings.csv"
    extract_face(
        dxf_path,
        face_model_path=tmp_path / "face_model.json",
        overlay_path=tmp_path / "overlay.dxf",
        warnings_csv_path=warnings_path,
    )

    with warnings_path.open("r", encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    assert rows == [
        {
            "id": "W1",
            "level": "warning",
            "code": "no_centerline_candidates",
            "message": "No parallel outline pairs produced centerline candidates.",
            "entity_id": "",
        }
    ]


def _write_line_rectangle(path):
    doc = ezdxf.new("R2010")
    modelspace = doc.modelspace()
    modelspace.add_line((0, 0), (100, 0))
    modelspace.add_line((0, 10), (100, 10))
    modelspace.add_line((0, 0), (0, 10))
    modelspace.add_line((100, 0), (100, 10))
    modelspace.add_circle((5, 5), 1)
    doc.saveas(path)
