from ehouse_model.domain import Member3D, Node3D
from ehouse_model.global_model_types import GlobalModel
from ehouse_model.global_stitching import StitchOptions, stitch_global_model


def test_stitch_global_model_merges_close_nodes_and_remaps_members():
    model = GlobalModel(
        project_name="Demo",
        nodes=(
            Node3D(id="base.N1", x=0, y=0, z=0),
            Node3D(id="wall.N1", x=0.4, y=0, z=0),
            Node3D(id="wall.N2", x=10, y=0, z=0),
        ),
        members=(
            Member3D(id="wall.M1", start_node_id="wall.N1", end_node_id="wall.N2"),
        ),
    )

    stitched = stitch_global_model(model, StitchOptions(merge_tolerance=1.0, review_tolerance=5.0))

    assert [node.id for node in stitched.nodes] == ["base.N1", "wall.N2"]
    assert stitched.members[0].start_node_id == "base.N1"
    assert stitched.members[0].end_node_id == "wall.N2"
    assert stitched.node_sources["base.N1"]["merged_node_ids"] == "base.N1,wall.N1"
    assert stitched.warnings[0].code == "stitched_nodes"


def test_stitch_global_model_warns_for_near_miss_nodes():
    model = GlobalModel(
        project_name="Demo",
        nodes=(
            Node3D(id="base.N1", x=0, y=0, z=0),
            Node3D(id="wall.N1", x=3, y=0, z=0),
        ),
        members=(),
    )

    stitched = stitch_global_model(model, StitchOptions(merge_tolerance=1.0, review_tolerance=5.0))

    assert len(stitched.nodes) == 2
    assert stitched.warnings[0].code == "node_near_miss"
