import math
from itertools import combinations
from typing import Any, cast

import numpy as np
import pytest
from manim import ImageMobject, MathTex
from matplotlib import colormaps
from pydantic import ValidationError

from animath.core.errors import AnimateError
from animath.core.store import Store
from animath.scene.primitives import PRIMITIVES, ArrayRef, Context, catalog
from animath.scene.primitives.field import colorize
from animath.scene.primitives.plot import places, ticks
from tests.scene.conftest import MAIN, REQ, context, ref

VIRIDIS = (np.array(colormaps["viridis"]([0.0, 1.0])[:, :3]) * 255).round()


def build(name: str, ctx: Context, **args: Any) -> Any:
    p = PRIMITIVES[name]
    return p.build(p.args.model_validate(args), ctx, MAIN)


def test_catalog() -> None:
    cat = catalog()
    assert set(cat) == {
        "text",
        "equation",
        "derive",
        "matrix",
        "plot",
        "field",
        "surface",
        "trace",
        "hierarchy",
    }
    assert all(
        {"region", "until"} <= set(cast(dict[str, Any], s["properties"])) for s in cat.values()
    )


def test_array_resolution(store: Store) -> None:
    ctx = context(store, a=[1.0, 2.0])
    assert ctx.array(ArrayRef(data=0, array="a")).tolist() == [1.0, 2.0]
    with pytest.raises(AnimateError, match="no such request"):
        ctx.array(ArrayRef(data=1, array="a"))
    with pytest.raises(AnimateError, match="missing"):
        ctx.array(ArrayRef(data=0, array="b"))
    with pytest.raises(AnimateError, match="missing"):
        Context(ctx.scene, store, {}, 1.0).array(ArrayRef(data=0, array="a"))


def test_complex_parts(store: Store) -> None:
    ctx = context(store, z=np.array([3 + 4j, -1j]))
    parts = {
        k: ctx.real(ArrayRef(data=0, array="z", part=k)).tolist() for k in ("abs", "real", "imag")
    }
    assert parts == {"abs": [5.0, 1.0], "real": [3.0, 0.0], "imag": [4.0, -1.0]}
    with pytest.raises(AnimateError, match=r"complex array .*set part"):
        ctx.real(ArrayRef(data=0, array="z"))
    with pytest.raises(AnimateError, match="set part"):
        build("plot", ctx, series=[{"x": [0, 1], "y": ref("z")}])


@pytest.mark.parametrize("payload", [b"not npy", "npz"])
def test_array_unreadable(store: Store, payload: bytes | str) -> None:
    import io

    ctx = context(store, a=[0.0])
    if payload == "npz":
        b = io.BytesIO()
        np.savez(b, x=np.zeros(2))
        payload = b.getvalue()
    assert isinstance(payload, bytes)
    ds = ctx.datasets[REQ.digest].model_copy(update={"arrays": {"a": store.put_blob(payload)}})
    bad = Context(ctx.scene, store, {REQ.digest: ds}, 1.0)
    with pytest.raises(AnimateError, match=r"unreadable|\.npy"):
        bad.array(ArrayRef(data=0, array="a"))


def test_text_and_equation(store: Store) -> None:
    ctx = context(store)
    assert build("equation", ctx, latex=r"\mathbf{Z}\mathbf{I}=\mathbf{V}").get_tex_string() == (
        r"\mathbf{Z}\mathbf{I}=\mathbf{V}"
    )
    assert build("text", ctx, text="Method of moments").get_tex_string() == "Method of moments"


def test_derive_cues(store: Store) -> None:
    p = PRIMITIVES["derive"]
    a = p.args.model_validate({"steps": ["{{a}}+{{b}}", "{{b}}+{{a}}", "c"]})
    m = p.build(a, context(store), MAIN)
    assert len(m) == 3
    assert all(isinstance(s, MathTex) for s in m)
    assert [c.t for c in p.cues(m, a, 1.0, 4.0)] == [1.0, 2.0, 3.0]
    assert p.last(m) is m[-1]
    with pytest.raises(ValidationError):
        p.args.model_validate({"steps": ["a"]})


def test_matrix_entries(store: Store) -> None:
    ctx = context(store, small=np.array([[1.0, 2.5e-4], [-3.0, 4.0]]))
    m = build("matrix", ctx, entries=[["a", "b"], ["c", "d"]])
    assert [e.get_tex_string() for e in m.get_entries()] == ["a", "b", "c", "d"]
    m = build("matrix", ctx, entries=ref("small"))
    assert [e.get_tex_string() for e in m.get_entries()] == ["1", "0.00025", "-3", "4"]
    cases: list[list[list[str]]] = [[], [[]], [["a"], ["b", "c"]]]
    for bad in cases:
        with pytest.raises(ValidationError, match="rectangular"):
            PRIMITIVES["matrix"].args.model_validate({"entries": bad})


def test_matrix_entries_disjoint(store: Store) -> None:
    jacobi = [
        ["0", r"\frac{1}{\sqrt{3}}", "0"],
        [r"\frac{1}{\sqrt{3}}", "0", r"\frac{2}{\sqrt{15}}"],
        ["0", r"\frac{2}{\sqrt{15}}", "0"],
    ]
    boxes = [
        (e.get_left()[0], e.get_bottom()[1], e.get_right()[0], e.get_top()[1])
        for e in build("matrix", context(store), entries=jacobi).get_entries()
    ]
    assert not [
        (a, b)
        for a, b in combinations(boxes, 2)
        if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    ]


def test_matrix_heatmap(store: Store) -> None:
    n = 20
    z = np.full((n, n), 1e-6)
    np.fill_diagonal(z, 1.0)
    ctx = context(store, z=z, zero=np.zeros((n, n)), v=np.ones(n))
    img = build("matrix", ctx, entries=ref("z")).get_pixel_array()
    assert img.shape[:2] == (n, n)
    assert (img[0, 0, :3] == VIRIDIS[1]).all()
    assert (img[0, 1, :3] == VIRIDIS[0]).all()
    assert (
        build("matrix", ctx, entries=ref("zero")).get_pixel_array()[..., :3] == VIRIDIS[0]
    ).all()
    with pytest.raises(AnimateError, match="2-D"):
        build("matrix", ctx, entries=ref("v"))


def test_colorize() -> None:
    rgb = colorize(np.array([[0.0, 0.5, 1.0]]))
    assert (rgb[0, 0] == VIRIDIS[0]).all()
    assert (rgb[0, 2] == VIRIDIS[1]).all()
    assert (colorize(np.ones((2, 2))) == VIRIDIS[0]).all()
    for bad in (np.array([np.nan]), np.zeros(0)):
        with pytest.raises(AnimateError, match="non-finite"):
            colorize(bad)


def test_field_orientation(store: Store) -> None:
    u = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    ctx = context(store, u=u, v=np.ones(3))
    m = build("field", ctx, values=ref("u"))
    assert isinstance(m, ImageMobject)
    img = m.get_pixel_array()
    assert (img[0, :, :3] == VIRIDIS[1]).all()
    assert (img[-1, :, :3] == VIRIDIS[0]).all()
    assert m.height == pytest.approx(MAIN.height)
    assert m.width < MAIN.width
    with pytest.raises(AnimateError, match="2-D"):
        build("field", ctx, values=ref("v"))


TET = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
FACES = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])


def test_surface(store: Store) -> None:
    ctx = context(store, p=TET, f=FACES, s=np.arange(4.0))
    m = build("surface", ctx, points=ref("p"), faces=ref("f"), scalars=ref("s"))
    img = m.get_pixel_array()
    assert img.shape[:2] == (round(MAIN.height * 30), round(MAIN.width * 30))
    lit = img[..., :3].max(axis=2) > 0
    assert 0.01 < lit.mean() < 0.9


@pytest.mark.parametrize(
    ("arrays", "match"),
    [
        ({"p": TET[:, :2], "f": FACES, "s": np.arange(4.0)}, "points"),
        ({"p": TET, "f": FACES + 1, "s": np.arange(4.0)}, "index"),
        ({"p": TET, "f": FACES * 1.0, "s": np.arange(4.0)}, "index"),
        ({"p": TET, "f": FACES, "s": np.arange(5.0)}, "scalars"),
    ],
)
def test_surface_rejects(store: Store, arrays: dict[str, Any], match: str) -> None:
    ctx = context(store, **arrays)
    with pytest.raises(AnimateError, match=match):
        build("surface", ctx, points=ref("p"), faces=ref("f"), scalars=ref("s"))


@pytest.mark.parametrize(("lo", "hi"), [(0.0, 30.0), (-1.3, 0.07), (2.0, 2.0), (1e-3, 9.9e-3)])
def test_ticks(lo: float, hi: float) -> None:
    a, b, h = ticks(lo, hi)
    m = h / 10.0 ** math.floor(math.log10(h))
    assert a <= lo
    assert b >= hi
    assert (b - a) / h <= 10 + 1e-9
    assert min(abs(m - k) for k in (1, 2, 5, 10)) < 1e-9


def test_places() -> None:
    assert [places(h) for h in (5.0, 1.0, 0.2, 0.05)] == [0, 0, 1, 2]


def test_plot_maps_data(store: Store) -> None:
    x = np.arange(1.0, 11.0)
    ctx = context(store, x=x, r=10.0**-x)
    m = build(
        "plot",
        ctx,
        series=[{"x": ref("x"), "y": ref("r"), "label": "GMRES"}],
        logy=True,
        xlabel="$k$",
    )
    ax, _labels, graph, legend = m
    assert ax.y_axis.x_range[:2].tolist() == [-10, -1]
    start = graph["line_graph"].get_start()
    assert np.allclose(start, ax.c2p(1.0, 0.1), atol=1e-6)
    assert legend[0].get_tex_string() == "GMRES"
    lin = build("plot", ctx, series=[{"x": [0, 1], "y": [0, 2]}, {"x": [0, 1], "y": [1, 1]}])
    assert len(lin) == 3


@pytest.mark.parametrize(
    ("series", "logy", "match"),
    [
        ({"x": [0, 1], "y": [0, 1, 2]}, False, "equal length"),
        ({"x": [0], "y": [0]}, False, "equal length"),
        ({"x": [0, 1], "y": [0, float("nan")]}, False, "finite"),
        ({"x": [0, 1], "y": [0, 1]}, True, "positive"),
    ],
)
def test_plot_rejects(store: Store, series: dict[str, Any], logy: bool, match: str) -> None:
    with pytest.raises(AnimateError, match=match):
        build("plot", context(store), series=[series], logy=logy)


def test_trace(store: Store) -> None:
    p = PRIMITIVES["trace"]
    a = p.args.model_validate({"lines": ["for k", "  w = Av", "", "end"], "steps": [1, 3, 1]})
    m = p.build(a, context(store), MAIN)
    rows, cursor = m
    assert cursor.get_y() == pytest.approx(rows[1].get_y())
    em = (rows[1].get_left()[0] - rows[0].get_left()[0]) / 2
    assert em > 0
    assert rows[2].get_fill_opacity() == 0
    cues = p.cues(m, a, 0.0, 3.0)
    assert [c.t for c in cues] == [0.0, 1.0, 2.0]
    anim = cues[1].play()
    anim.begin()
    anim.interpolate(1.0)
    assert cursor.get_y() == pytest.approx(rows[3].get_y())
    with pytest.raises(ValidationError, match="outside"):
        p.args.model_validate({"lines": ["a"], "steps": [1]})
