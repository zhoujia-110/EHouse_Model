import pytest

from ehouse_model import Node2D, PlaneSpec, map_2d_to_3d


def test_map_2d_to_3d_uses_declared_plane_axes():
    plane = PlaneSpec(
        name="right",
        origin=(100.0, 10.0, 5.0),
        local_x_axis="-Z",
        local_y_axis="Y",
    )
    node = Node2D(id="N1", x=7.0, y=3.0)

    mapped = map_2d_to_3d(node, plane)

    assert mapped.id == "N1"
    assert mapped.x == pytest.approx(100.0)
    assert mapped.y == pytest.approx(13.0)
    assert mapped.z == pytest.approx(-2.0)


def test_plane_rejects_reused_global_axis():
    with pytest.raises(ValueError, match="different global axes"):
        PlaneSpec(name="bad", local_x_axis="X", local_y_axis="-X")
