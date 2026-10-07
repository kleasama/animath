import pytest

from animath.scene.layout import Box, Placement, Region, cell, frame, violations

F = frame(16.0, 9.0)


def test_box_relations() -> None:
    a = Box(0, 0, 2, 1)
    assert (a.width, a.height, a.center) == (2, 1, (1, 0.5))
    assert a.overlaps(Box(1, 0.5, 3, 2))
    assert not a.overlaps(Box(2, 0, 3, 1))
    assert not a.overlaps(Box(0, 1, 2, 2))
    assert a.within(Box(0, 0, 2, 1))
    assert not a.within(Box(0.1, 0, 2, 1))


@pytest.mark.parametrize(
    ("region", "box"),
    [("main", (-7.36, -3.24, 7.36, 3.06)), ("title", (-7.36, 3.24, 7.36, 4.23))],
)
def test_cell_maps_grid_to_frame(region: Region, box: tuple[float, ...]) -> None:
    c = cell(region, F)
    assert (c.x0, c.y0, c.x1, c.y1) == pytest.approx(box)


def test_grid_semantics() -> None:
    regions: tuple[Region, ...] = ("title", "main", "left", "right", "footer")
    cells = {r: cell(r, F) for r in regions}
    assert all(c.within(F) for c in cells.values())
    assert not cells["left"].overlaps(cells["right"])
    assert cells["left"].overlaps(cells["main"])
    assert cells["right"].overlaps(cells["main"])
    assert not any(cells["title"].overlaps(cells[r]) for r in ("main", "left", "right", "footer"))


def test_violations() -> None:
    a = Placement("a", Box(0, 0, 2, 2), 0, 2)
    b = Placement("b", Box(1, 1, 3, 3), 2, 4)
    c = Placement("c", Box(1, 1, 3, 3), 1, 3)
    assert violations([a, b], F) == []
    assert violations([a, c], F) == ["a overlaps c"]
    far = Placement("d", Box(7, 0, 9, 1), 0, 1, scale=0.3)
    assert violations([far], F) == ["d: off-frame", "d: scale 0.30 < 0.4"]
