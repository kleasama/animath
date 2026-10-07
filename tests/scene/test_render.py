from functools import partial
from typing import Any

import av
import pytest
from manim import Circle, FadeIn

from animath.core.errors import AnimateError
from animath.core.schemas import Narration, Params, Visual
from animath.core.store import Store
from animath.scene import compose, render, schedule, timeline
from animath.scene.primitives import Cue
from animath.scene.render import EXIT_S, Clip
from tests.scene.conftest import F, context, scene

H = "0" * 64
EQ = Visual(primitive="equation", args={"latex": "x", "until": "b"})


def narration(**kw: Any) -> Narration:
    return Narration(**{"scene_id": "s", "audio": H, "duration_s": 5.0, **kw})


def test_timeline() -> None:
    s = scene(marks=("a", "b"))
    assert timeline(s, None) == ({"a": 0.0, "b": 2.0}, 4.0)
    times = {"a": 0.5, "b": 3.0, "c": 4.0}
    assert timeline(s, narration(bookmarks=times)) == (times, 5.0)
    with pytest.raises(AnimateError, match="narration of t"):
        timeline(s, narration(scene_id="t", bookmarks=times))
    with pytest.raises(AnimateError, match=r"lacks bookmarks \['b'\]"):
        timeline(s, narration(bookmarks={"a": 0.5}))


def test_schedule() -> None:
    def cue(t: float, rt: float) -> Cue:
        return Cue(t, rt, partial(FadeIn, Circle()))

    a, b, c, d, e = cue(0.0, 1.0), cue(0.01, 0.2), cue(0.5, 2.0), cue(0.55, 0.0), cue(2.0, 1.0)
    steps = schedule([c, a, b, d, e], 2.0, 10)
    assert [(t, rt) for t, rt, _ in steps] == [(0.0, 0.5), (0.5, 0.1), (0.6, 0.1)]
    assert [g for _, _, g in steps] == [[a, b], [c], [d]]
    assert schedule([], 2.0, 10) == []


def test_compose_places_and_cues(store: Store) -> None:
    s = scene(EQ, Visual(primitive="text", args={"text": "T", "region": "title"}, at="b"))
    (eq, txt) = compose(s, context(store), {"a": 0.0, "b": 2.0}, 4.0, F)
    assert (eq.placement.t0, eq.placement.t1, txt.placement.t0, txt.placement.t1) == (0, 2, 2, 4)
    assert [c.t for c in eq.cues] == [0.0, 2.0 - EXIT_S]
    assert [c.t for c in txt.cues] == [2.0]
    assert eq.placement.scale == 1.0
    assert eq.placement.box.center == pytest.approx((0.0, -0.09))


def test_compose_shrinks_to_cell(store: Store) -> None:
    s = scene(Visual(primitive="equation", args={"latex": "+".join("x" * 80), "region": "left"}))
    (it,) = compose(s, context(store), {"a": 0.0, "b": 2.0}, 4.0, F)
    assert it.placement.scale < 1.0
    assert it.placement.box.width == pytest.approx(0.45 * F.width)


@pytest.mark.parametrize(
    ("visual", "match"),
    [
        (Visual(primitive="nope"), "unknown primitive"),
        (Visual(primitive="equation", args={"latex": ""}), "invalid args"),
        (Visual(primitive="equation", args={"latex": "x", "until": "z"}), "unknown bookmark"),
        (Visual(primitive="equation", args={"latex": "x", "until": "a"}, at="b"), "empty interval"),
        (Visual(primitive="equation", args={"latex": r"\frac{"}), "build failed"),
        (Visual(primitive="field", args={"values": {"data": 0, "array": "u"}}), "missing"),
    ],
)
def test_compose_rejects(store: Store, visual: Visual, match: str) -> None:
    with pytest.raises(AnimateError, match=match):
        compose(scene(visual), context(store), {"a": 0.0, "b": 2.0}, 4.0, F)


def frames(store: Store, d: str) -> int:
    with av.open(str(store.blob_path(d))) as f:
        return sum(1 for _ in f.decode(video=0))


def test_render_clip(store: Store) -> None:
    s = scene(EQ, Visual(primitive="equation", args={"latex": "y"}, at="b"), duration=2.0)
    nar = narration(duration_s=2.4, bookmarks={"a": 0.0, "b": 1.2})
    out = render(s, Params(width=320, height=240, fps=15), store, nar)
    assert (out.scene_id, out.duration_s, out.bookmarks) == ("s", 2.4, {"a": 0.0, "b": 1.2})
    assert out.checks == {"layout": True, "render": True}
    assert frames(store, out.clip) == 36
    with av.open(str(store.blob_path(out.clip))) as f:
        v = f.streams.video[0]
        assert (v.codec_context.name, v.width, v.height) == ("h264", 320, 240)
    draft = render(s, Params(), store, draft=True)
    with av.open(str(store.blob_path(draft.clip))) as f:
        assert (f.streams.video[0].width, f.streams.video[0].height) == (426, 240)
    assert frames(store, draft.clip) == 30
    assert render(s, Params(), store, draft=True).clip == draft.clip


def test_render_rejects_layout(store: Store) -> None:
    s = scene(EQ, Visual(primitive="equation", args={"latex": "y"}), duration=2.0)
    with pytest.raises(AnimateError, match=r"layout: s\.0:equation overlaps s\.1:equation"):
        render(s, Params(), store, draft=True)


def test_render_wraps_failure(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Clip) -> None:
        raise RuntimeError("cairo")

    monkeypatch.setattr(Clip, "construct", boom)
    with pytest.raises(AnimateError, match="render failed: cairo"):
        render(scene(duration=1.0), Params(), store, draft=True)
