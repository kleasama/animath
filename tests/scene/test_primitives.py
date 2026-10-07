import math
from itertools import combinations
from typing import Any, cast

import manim
import numpy as np
import pytest
from manim import (
    YELLOW,
    Circle,
    Circumscribe,
    ImageMobject,
    Indicate,
    ManimColor,
    MathTex,
    Square,
    VGroup,
    Write,
)
from matplotlib import colormaps
from pydantic import ValidationError

from animath.core.errors import AnimateError
from animath.core.store import Store
from animath.scene.primitives import PRIMITIVES, ArrayRef, Context, catalog
from animath.scene.primitives.base import DIM, VERBS, color, instant, path, verb
from animath.scene.primitives.field import colorize
from animath.scene.primitives.matrix import DENSE_MAX
from animath.scene.primitives.plot import places, ticks
from animath.scene.primitives.tex import IsoMathTex, tex_part, whole
from tests.scene.conftest import MAIN, REQ, context, ref

DENSE = DENSE_MAX + 1

VIRIDIS = (np.array(colormaps["viridis"]([0.0, 1.0])[:, :3]) * 255).round()


def build(name: str, ctx: Context, **args: Any) -> Any:
    p = PRIMITIVES[name]
    return p.build(p.args.model_validate(args), ctx, MAIN)


def test_catalog() -> None:
    cat = catalog()
    names = {"text", "equation", "derive", "matrix", "plot", "field", "surface", "trace", "code"}
    assert set(cat) == names
    assert all(
        {"region", "until", "actions", "view"} <= set(cast(dict[str, Any], s["properties"]))
        and "resume" not in cast(dict[str, Any], s["properties"])
        for s in cat.values()
    )

    def do(name: str) -> Any:
        return cast(dict[str, Any], cat[name])["$defs"]["Action"]["properties"]["do"]

    assert do("equation")["enum"] == list(VERBS)
    assert do("derive")["enum"] == [*VERBS, "next"]
    assert do("trace")["enum"] == [*VERBS, "goto"]
    assert "enum" not in do("code")
    assert str(cat["matrix"]["description"]).endswith("row:i, col:j, entry:i:j, brackets.")
    assert "MathTex(" in str(cast(dict[str, Any], cat["code"])["properties"]["code"])


def test_color() -> None:
    assert color(None) == YELLOW
    assert color("#FF0000") == ManimColor("#FF0000")
    assert color("BLUE_E") == manim.BLUE_E
    for bad in ("NOPE", "UP"):
        with pytest.raises(AnimateError, match=f"unknown colour '{bad}'"):
            color(bad)


def test_path() -> None:
    m = VGroup(Square(), VGroup(Circle(), Square()))
    assert path(m, "1.0") is m[1][0]
    for bad in ("2", "1.x", "0.0", ""):
        with pytest.raises(AnimateError, match="no part"):
            path(m, bad)


def leaves(m: Any) -> list[float]:
    return [float(x.get_fill_opacity()) for x in m.family_members_with_points()]


def test_generic_verbs(store: Store) -> None:
    sq = Square(fill_opacity=1.0)
    orig = sq.copy()
    a = verb("show", sq.set_opacity(0.0), orig, YELLOW)
    assert isinstance(a, Write)
    instant(a)
    assert leaves(sq) == [1.0]
    assert isinstance(verb("indicate", sq, orig, YELLOW), Indicate)
    instant(verb("dim", sq, orig, YELLOW))
    assert leaves(sq) == [DIM]
    instant(verb("hide", sq, orig, YELLOW))
    assert leaves(sq) == [0.0]
    instant(verb("mark", sq, orig, manim.RED))
    assert sq.get_color() == manim.RED
    instant(verb("unmark", sq, orig, YELLOW))
    assert (sq.get_color(), leaves(sq)) == (orig.get_color(), [1.0])
    img = build("field", context(store, u=np.eye(2)), values=ref("u"))
    assert isinstance(verb("indicate", img, img.copy(), YELLOW), Circumscribe)
    instant(verb("show", img.set_opacity(0.0), img.copy(), YELLOW))
    with pytest.raises(AnimateError, match="mark needs a vector part"):
        verb("mark", img, img.copy(), YELLOW)


def test_default_hooks(store: Store) -> None:
    p = PRIMITIVES["equation"]
    a = p.args.model_validate({"latex": "x"})
    m = p.build(a, context(store), MAIN)
    assert p.first(m) is m
    assert p.last(m) is m
    assert not p.knows(m, "next")
    with pytest.raises(AnimateError, match="verb 'next' not implemented"):
        p.act(m, a, "next", [])


def test_tex_parts(store: Store) -> None:
    assert whole(r"t \to s", 0, 1)
    assert not whole(r"\to", 2, 3)
    m = IsoMathTex(r"t \to t_{s}", substrings_to_isolate=["t"])
    assert len(tex_part(m, "t")) == 2
    assert tex_part(m, "0") is m[0]
    p = PRIMITIVES["equation"]
    a = p.args.model_validate(
        {"latex": "L_{21} D + L", "actions": [{"at": "a", "do": "mark", "parts": ["L_{21}"]}]}
    )
    eq = p.build(a, context(store), MAIN)
    assert len(p.part(eq, a, "L_{21}").family_members_with_points()) == 3
    acts = [{"at": "a", "do": "mark", "parts": [s]} for s in ("2", "x", "A^T")]
    a = p.args.model_validate({"latex": r"x^2 + \hat x + A^T", "actions": acts})
    eq = p.build(a, context(store), MAIN)
    assert eq.get_tex_string() == r"x^{2} + \hat{x} + A^{T}"
    assert [len(p.part(eq, a, s)) for s in ("2", "x", "A^T")] == [1, 2, 1]
    t = PRIMITIVES["text"]
    ta = t.args.model_validate(
        {"text": "a cluster $t$", "actions": [{"do": "dim", "parts": ["cluster"]}]}
    )
    assert len(t.part(t.build(ta, context(store), MAIN), ta, "cluster")) == 1


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
    cues = p.cues(m, a, 1.0, 4.0)
    assert [c.t for c in cues] == [1.0, 2.0, 3.0]
    assert [c.run_time for c in cues] == pytest.approx([1.5, 0.8, 0.8])
    assert [c.run_time for c in p.cues(m, a, 1.0, 2.5)[1:]] == pytest.approx([0.4, 0.4])
    assert p.first(m) is m[0]
    assert p.last(m) is m[0]
    with pytest.raises(ValidationError):
        p.args.model_validate({"steps": ["a"]})


def test_derive_next(store: Store) -> None:
    p = PRIMITIVES["derive"]
    nxt = {"at": "a", "do": "next"}
    a = p.args.model_validate({"steps": ["a", "{{a}}+b", "c"], "actions": [nxt, nxt]})
    m = p.build(a, context(store), MAIN)
    assert [c.t for c in p.cues(m, a, 1.0, 4.0)] == [1.0]
    assert p.knows(m, "next")
    assert p.part(m, a, "1") is m[1]
    assert type(p.act(m, a, "next", [])).__name__ == "TransformMatchingTex"
    assert p.last(m) is m[1]
    p.act(m, a, "next", [])
    assert p.last(m) is m[2]
    with pytest.raises(AnimateError, match="next after the last of 3 steps"):
        p.act(m, a, "next", [])
    too_many = p.args.model_validate({"steps": ["a", "b"], "actions": [nxt, nxt]})
    with pytest.raises(AnimateError, match="2 next actions for 2 steps"):
        p.cues(p.build(too_many, context(store), MAIN), too_many, 0.0, 1.0)


def test_matrix_parts(store: Store) -> None:
    p = PRIMITIVES["matrix"]
    a = p.args.model_validate({"entries": [["a", "b"], ["c", "d"]]})
    m = p.build(a, context(store), MAIN)

    def tex(sel: str) -> list[str]:
        return [e.get_tex_string() for e in p.part(m, a, sel)]

    assert (tex("row:2"), tex("col:1"), p.part(m, a, "entry:2:1").get_tex_string()) == (
        ["c", "d"],
        ["a", "c"],
        "c",
    )
    assert len(p.part(m, a, "brackets")) == 2
    assert p.part(m, a, "0.1") is m[0][1]
    for bad in ("row:0", "row:3", "col:x", "entry:1", "entry:3:1", "diag"):
        with pytest.raises(AnimateError, match="no part"):
            p.part(m, a, bad)
    heat = p.args.model_validate({"entries": ref("z")})
    img = p.build(heat, context(store, z=np.eye(DENSE)), MAIN)
    with pytest.raises(AnimateError, match="no part 'row:1'"):
        p.part(img, heat, "row:1")


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
    p = PRIMITIVES["plot"]
    a = p.args.model_validate(
        {"series": [{"x": ref("x"), "y": ref("r"), "label": "G"}], "logy": True, "xlabel": "$k$"}
    )
    parts = [p.part(m, a, s) for s in ("axes", "labels", "series:0", "legend")]
    assert parts == list(m)
    b = p.args.model_validate({"series": [{"x": [0, 1], "y": [0, 2]}, {"x": [0, 1], "y": [1, 1]}]})
    assert p.part(lin, b, "series:1") is lin[2]
    with pytest.raises(AnimateError, match="no part 'legend'"):
        p.part(lin, b, "legend")


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
    assert [(c.t, c.run_time) for c in cues] == [(0.0, 1.0), (1.0, 0.4), (2.0, 0.4)]
    assert [c.run_time for c in p.cues(m, a, 0.0, 0.75)[1:]] == pytest.approx([0.2, 0.2])
    anim = cues[1].play()
    anim.begin()
    anim.interpolate(1.0)
    assert cursor.get_y() == pytest.approx(rows[3].get_y())
    with pytest.raises(ValidationError, match="outside"):
        p.args.model_validate({"lines": ["a"], "steps": [1]})


def test_trace_goto(store: Store) -> None:
    p = PRIMITIVES["trace"]
    go = {"at": "a", "do": "goto", "parts": ["line:2"]}
    a = p.args.model_validate(
        {"lines": ["for k", "  w = Av", "end"], "steps": [0], "actions": [go]}
    )
    m = p.build(a, context(store), MAIN)
    rows, cursor = m
    assert [c.t for c in p.cues(m, a, 0.0, 3.0)] == [0.0]
    assert (p.part(m, a, "cursor"), p.part(m, a, "line:1")) == (cursor, rows[1])
    instant(p.act(m, a, "goto", ["line:2"]))
    assert cursor.get_y() == pytest.approx(rows[2].get_y())
    for parts in ([], ["cursor"], ["line:1", "line:2"]):
        with pytest.raises(AnimateError, match="goto needs one part line:k"):
            p.act(m, a, "goto", parts)
    with pytest.raises(AnimateError, match="no part 'line:3'"):
        p.part(m, a, "line:3")
