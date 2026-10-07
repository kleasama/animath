from dataclasses import replace
from typing import Any

import av
import numpy as np
import pytest
from manim import DashedVMobject, Text

from animath.core.errors import AnimateError
from animath.core.schemas import Params, Visual
from animath.core.store import Store
from animath.numerics.h2 import RssLu
from animath.scene import render
from animath.scene.primitives import PRIMITIVES
from animath.scene.primitives.hierarchy import (
    ELIM,
    FILL,
    PALETTE,
    SIDE,
    SPLIT,
    Board,
    Flash,
    HierarchyArgs,
    Spec,
    State,
    Step,
    Walk,
    advance,
    below,
    draw,
    mobject,
    nodes,
    shown,
    up,
)
from tests.scene.conftest import MAIN, context, scene

AMBER = np.array([255, 191, 0])


@pytest.fixture(scope="module")
def arrays() -> dict[str, Any]:
    return RssLu(n=256, leaf=16, tol=1e-3).run()[0]


@pytest.fixture(scope="module")
def w(arrays: dict[str, Any]) -> Walk:
    return Walk(arrays)


def walk(w: Walk, *steps: dict[str, Any], **start: Any) -> tuple[State, Flash]:
    a = HierarchyArgs.model_validate({**start, "steps": steps})
    st, fl = w.start(a), Flash()
    for s in a.steps:
        st, fl = advance(w, st, s)
    return st, fl


def step(do: str, **part: Any) -> Step:
    return Step.model_validate({"do": do, "part": part})


def area(sp: Spec) -> float:
    return (sp.x1 - sp.x0) * (sp.y1 - sp.y0)


def test_walk_sizes(w: Walk, arrays: dict[str, Any]) -> None:
    assert (w.depth, w.top) == (4, 2)
    act = arrays["active"].tolist()
    assert [sum(w.n0(t) for t in nodes(lvl)) for lvl, _ in act] == [n for _, n in act]
    for t, _, c, n, k, *_ in arrays["stage"].tolist():
        assert (w.n0(t), w.k(t), w.colour(t)) == (n, k, c)
    assert [below(0, 4), below(3, 4), below(18, 4)] == [(15, 30), (15, 18), (18, 18)]


def test_walk_without_far_field(store: Store) -> None:
    a = RssLu(n=64, leaf=16, eta=0.1).run()[0]
    v = Walk(a)
    assert (v.depth, v.top, v.row) == (2, 2, {})
    assert [v.n0(t) for t in nodes(2)] == [16] * 4
    with pytest.raises(AnimateError, match="level 2 has no stages"):
        v.pick(2)
    st, _ = walk(v, {"do": "colour"}, {"do": "top"})
    out = draw(v, st, ("plate", "operator"))[0]
    assert {sp.fill for k, sp in out.items() if k[0] == "box"} == {PALETTE[0]}
    assert (out["pcap",].text, out["ocap",].text) == (
        "level 2: 4 clusters, dense top",
        "dense top, N = 64",
    )
    assert not [k for k in out if k[0] in ("near", "fill")]


def test_pick_and_ring(w: Walk) -> None:
    t, s = w.pick(4)
    nine = [u for u in nodes(4) if len(w.near[u]) == 9]
    assert t == min(nine, key=w.row.__getitem__)
    assert s == min((u for u in w.near[t] if w.row[u] > w.row[t]), key=w.row.__getitem__)
    for u in nodes(4):
        ring = w.ring(u)
        assert not set(ring) & set(w.near[u])
        assert all(any(x in w.near[v] for v in w.near[u]) for x in ring)
        assert len(ring) == {4: 5, 6: 6, 9: 7}[len(w.near[u])]


def test_start(w: Walk) -> None:
    assert w.start(HierarchyArgs()) == State(4)
    st = w.start(HierarchyArgs(level=3, done=2, coloured=True))
    assert st.phase == {7: FILL, 12: FILL}
    assert st.coloured == frozenset(nodes(3))
    for bad, match in (
        ({"level": 1}, r"level 1 outside \[2, 4\]"),
        ({"level": 5}, "outside"),
        ({"done": 17}, "level 4 has 16 stages, done=17"),
    ):
        with pytest.raises(AnimateError, match=match):
            w.start(HierarchyArgs.model_validate(bad))


def test_marks(w: Walk) -> None:
    t, s = w.pick(4)
    st, fl = walk(
        w,
        {"do": "select"},
        {"do": "footprint"},
        {"do": "ring", "part": {"cluster": "s"}},
        {"do": "select", "part": {"cluster": 15}},
    )
    assert (st.marks, st.current, fl) == (
        frozenset({(t, "footprint"), (s, "ring"), (15, "select")}),
        15,
        (),
    )
    st, _ = advance(w, st, Step(do="footprint"))
    assert (15, "footprint") in st.marks
    st, _ = advance(w, st, step("clear", cluster=15))
    assert st.marks == {(t, "footprint"), (s, "ring")}
    assert advance(w, st, Step(do="clear"))[0].marks == frozenset()
    assert advance(w, st, step("colour", cluster=16))[0].coloured == {16}
    assert advance(w, st, Step(do="colour"))[0].coloured == set(nodes(4))
    with pytest.raises(AnimateError, match="cluster 7 is not on level 4"):
        advance(w, st, step("select", cluster=7))


def test_stage_phases(w: Walk) -> None:
    t = w.pick(4)[0]
    st, fl = walk(w, {"do": "eliminate"}, {"do": "rotate"})
    assert (st.phase, st.current, fl) == ({t: ELIM}, t, (("rotate", t),))
    with pytest.raises(AnimateError, match="rotate: cluster 3 has no stage"):
        advance(w, State(2), step("rotate", cluster=3))


def test_wave(w: Walk) -> None:
    t = w.pick(4)[0]
    st, fl = walk(w, {"do": "split"}, {"do": "wave"})
    assert fl == (("class", 0),)
    assert {u for u, ph in st.phase.items() if ph == FILL} == {15, 20, 25, 30}
    assert st.phase[t] == SPLIT
    st, fl = advance(w, st, step("wave", colour=4))
    assert fl == (("class", 4),)
    assert {u for u, ph in st.phase.items() if ph == FILL} == {15, 20, 25, 30, 19, 29}
    for c in (1, 2, 3, 5, 6, 7, 8):
        st, fl = advance(w, st, Step(do="wave"))
        assert fl == (("class", c),)
    assert st.phase == dict.fromkeys(nodes(4), FILL)
    with pytest.raises(AnimateError, match="no pending stage of colour 0 on level 4"):
        advance(w, st, Step(do="wave"))


def test_drop_coarsen_top(w: Walk) -> None:
    t = w.pick(4)[0]
    st, _ = walk(w, {"do": "fill"})
    made = set(w.made[w.row[t]])
    assert made == {(a, b) for a in w.near[t] for b in w.near[t] if b not in w.near[a]}
    assert shown(w, st) == made
    blk = min(made)
    st, _ = advance(w, st, step("drop", block=blk))
    assert shown(w, st) == made - {blk}
    for bad in (None, blk):
        with pytest.raises(AnimateError, match="not a fill block on view"):
            advance(w, st, step("drop", block=bad))
    st3, _ = advance(w, st, Step(do="coarsen"))
    assert st3 == State(3)
    assert shown(w, st3) == w.carried[3]
    with pytest.raises(AnimateError, match="level 3 is not the undone top 2"):
        advance(w, st3, Step(do="top"))
    st2, _ = advance(w, st3, Step(do="coarsen"))
    with pytest.raises(AnimateError, match="level 2 is the top"):
        advance(w, st2, Step(do="coarsen"))
    st2, _ = advance(w, replace(st2, marks=frozenset({(3, "select")})), Step(do="top"))
    assert st2.top
    assert not st2.marks
    with pytest.raises(AnimateError, match="not the undone top"):
        advance(w, st2, Step(do="top"))


def test_operator_tiles_the_matrix(w: Walk) -> None:
    for lvl in (4, 3, 2):
        out = draw(w, State(lvl), ("operator",))[0]
        sg = SIDE / sum(w.n0(t) for t in nodes(lvl))
        blocks = sum(area(sp) for k, sp in out.items() if k[0] in ("near", "far"))
        level = sum(w.n0(t) * w.n0(s) for t in nodes(lvl) for s in w.far[t]) * sg**2
        assert blocks + level == pytest.approx(SIDE**2)
        assert area(out["bg",]) == pytest.approx(SIDE**2)


def test_operator_stage(w: Walk) -> None:
    t = w.pick(4)[0]
    n, k = w.n0(t), w.k(t)
    sg = SIDE / 256
    st, _ = walk(w, {"do": "footprint"}, {"do": "zero"})
    out = draw(w, st, ("operator",))[0]
    assert {key[2:] for key in out if key[0] == "onear"} == {
        (s, i) for s in w.near[t] for i in (0, 1)
    }
    heights = [out["split", t, j, 0].y1 - out["split", t, j, 0].y0 for j in (0, 1)]
    assert heights == pytest.approx([k * sg, (n - k) * sg])
    z = out["zero", t, 1]
    assert (z.x1 - z.x0, z.y1 - z.y0) == pytest.approx(((n - k) * sg, SIDE))
    assert out["ocap",].text == "N = 256"
    st, _ = advance(w, st, Step(do="fill"))
    out, fl = draw(w, st, ("operator",), (("rotate", t), ("schur", t)))
    assert not [key for key in out if key[0] in ("split", "zero")]
    tt = out["near", t, t]
    assert (tt.x1 - tt.x0, tt.y1 - tt.y0) == pytest.approx((k * sg, k * sg))
    assert out["ocap",].text == f"N = {256 - n + k}"
    assert {key[1:] for key in out if key[0] == "fill"} == set(w.made[w.row[t]])
    assert {key for key in fl if key[0] == "schur"} == {
        ("schur", a, b) for a in w.near[t] for b in w.near[t]
    }
    assert {("rot", t, 0), ("rot", t, 1)} <= set(fl)


def test_plate(w: Walk) -> None:
    t = w.pick(4)[0]
    st, fl = walk(
        w, {"do": "colour"}, {"do": "select"}, {"do": "footprint"}, {"do": "ring"}, {"do": "wave"}
    )
    out, flash = draw(w, st, ("plate",), fl)
    boxes = {key[1]: sp for key, sp in out.items() if key[0] == "box"}
    assert set(boxes) == set(nodes(4))
    x0, y0 = min(b.x0 for b in boxes.values()), min(b.y0 for b in boxes.values())
    x1, y1 = max(b.x1 for b in boxes.values()), max(b.y1 for b in boxes.values())
    assert (x0, y0, x1, y1) == pytest.approx((-SIDE / 2, -SIDE / 2, SIDE / 2, SIDE / 2))
    assert {key[1] for key in flash} == {15, 20, 25, 30}
    assert {key[2] for key in out if key[0] == "pnear"} == set(w.near[t])
    assert {key[2] for key in out if key[0] == "pring"} == set(w.ring(t))
    assert out["psel", t][:4] == boxes[t][:4]
    assert boxes[t].fill == PALETTE[w.colour(t)]
    assert boxes[15].fo < boxes[t].fo
    assert out["pcap",].text == "level 4: 16 clusters, 9 colours"
    assert draw(w, State(2), ("plate",))[0]["pcap",].text == "level 2: 4 clusters, top level"


def test_plate_split_bar(w: Walk) -> None:
    t = w.pick(4)[0]
    out = draw(w, walk(w, {"do": "split"})[0], ("plate",))[0]
    k, r = out["psplit", t, 0], out["psplit", t, 1]
    assert (k.x1 - k.x0) / (r.x1 - r.x0) == pytest.approx(w.k(t) / (w.n0(t) - w.k(t)))
    assert (k.x0, k.x1, r.x1) == pytest.approx((out["box", t].x0, r.x0, out["box", t].x1))
    done = draw(w, walk(w, {"do": "eliminate"})[0], ("plate",))[0]
    assert not [key for key in done if key[0] == "psplit"]


def test_vanishing_items_sink_into_parents(w: Walk) -> None:
    st, _ = walk(w, {"do": "fill"})
    old = draw(w, st, ("plate", "operator"))[0]
    new = draw(w, advance(w, st, Step(do="coarsen"))[0], ("plate", "operator"))[0]
    gone = old.keys() - new.keys()
    assert {key[0] for key in gone} == {"box", "near", "fill", "far"}
    for key in gone:
        p = tuple((i - 1) // 2 for i in key[1:])
        sink = up(key, new)
        if key[0] in ("near", "box"):
            assert sink == new[key[0], *p]
        elif key[0] == "fill":
            assert sink is not None
            assert sink in (new.get(("fill", *p)), new.get(("near", *p)))
        else:
            assert sink is None
    top = draw(w, State(2, top=True), ("operator",))[0]
    assert up(("near", 3, 4), top) == top["top",]
    assert up(("box", 3), top) is None


def test_mobject() -> None:
    m = mobject(Spec(0.0, 0.0, 1.0, 0.5, "#FFFFFF", 1.0, text="a caption far wider than its box"))
    assert isinstance(m, Text)
    assert m.width == pytest.approx(0.9)
    d = mobject(Spec(0.0, 0.0, 2.0, 1.0, "#FFFFFF", 0.0, sw=3.0, z=3, dashed=True))
    assert isinstance(d, DashedVMobject)
    assert (len(d), d.z_index) == (24, 3)
    assert d.get_center() == pytest.approx((1.0, 0.5, 0.0))


def play(m: Board, i: int) -> None:
    for c in m.step(i, 0.0, 1.0):
        anim = c.play()
        anim.begin()
        anim.interpolate(1.0)


def test_board(store: Store, arrays: dict[str, Any]) -> None:
    p = PRIMITIVES["hierarchy"]
    steps = [{"do": "select"}, {"do": "rotate"}, {"do": "eliminate"}, {"do": "clear"}]
    a = p.args.model_validate({"steps": steps})
    m = p.build(a, context(store, **arrays), MAIN)
    assert isinstance(m, Board)
    m.scale(0.5).shift((1.0, 1.0, 0.0))
    anchor = m.make(m.start["frame",])
    assert anchor.get_center() == pytest.approx(m.items["frame",].get_center())
    assert anchor.width == pytest.approx(m.items["frame",].width)
    cues = p.cues(m, a, 1.0, 6.0)
    assert (cues[0].t, cues[0].run_time) == (1.0, 1.0)
    assert sorted({c.t for c in cues[1:]}) == [2.0, 3.0, 4.0, 5.0]
    assert {c.run_time for c in cues[1:]} == {0.8}
    tc = Walk.load(context(store, **arrays), 0).pick(4)[0]
    play(m, 0)
    play(m, 1)
    flashes = sorted(k for k in m.items if k[0] == "flash")
    assert flashes == [("flash", 1, "rot", tc, 0), ("flash", 1, "rot", tc, 1)]
    assert all(m.items[k].get_fill_opacity() == pytest.approx(0.0) for k in flashes)
    play(m, 2)
    assert not [k for k in m.items if k[0] == "flash"]
    assert set(m.submobjects) == set(m.items.values())
    play(m, 3)
    assert set(m.dead) == {("psel", tc), ("osel", tc, 0), ("osel", tc, 1)}
    assert all(m.items[k].get_stroke_opacity() == pytest.approx(0.0) for k in m.dead)
    for k, sp in m.plan[-1][0].items():
        assert m.items[k].get_center() == pytest.approx(m.make(sp).get_center(), abs=1e-6)
    with pytest.raises(AnimateError, match=r"4 steps in 0\.30 s"):
        p.cues(m, a, 0.0, 0.3)
    bare = p.args.model_validate({})
    assert len(p.cues(p.build(bare, context(store, **arrays), MAIN), bare, 0.0, 0.3)) == 1


def test_plate_needs_2d(store: Store, arrays: dict[str, Any]) -> None:
    box = np.concatenate([arrays["box"], np.zeros((*arrays["box"].shape[:2], 1))], axis=2)
    ctx = context(store, **{**arrays, "box": box})
    p = PRIMITIVES["hierarchy"]
    with pytest.raises(AnimateError, match="plate view needs 2-D points, got 3-D"):
        p.build(p.args.model_validate({}), ctx, MAIN)
    m = p.build(p.args.model_validate({"views": ["operator"]}), ctx, MAIN)
    assert isinstance(m, Board)
    assert not [k for k in m.items if k[0] == "box"]


def test_render(store: Store, arrays: dict[str, Any]) -> None:
    ctx = context(store, **arrays)
    v = Visual(primitive="hierarchy", args={"steps": [{"do": "select"}, {"do": "fill"}]})
    r = render(scene(v, duration=3.0), Params(), store, datasets=ctx.datasets, draft=True)
    assert r.checks == {"layout": True, "render": True}
    with av.open(str(store.blob_path(r.clip))) as c:
        frames = [(f.time, f.to_ndarray(format="rgb24")) for f in c.decode(video=0)]
    assert len(frames) == 45
    amber = [t for t, img in frames if (np.abs(img - AMBER).max(axis=2) < 40).sum() > 20]
    assert amber
    assert min(amber) > 2.0
