import tempfile
from functools import partial
from typing import Any

import av
import manim
import numpy as np
import pytest
from manim import (
    BLUE,
    RED,
    Animation,
    AnimationGroup,
    Circle,
    Create,
    FadeIn,
    FadeOut,
    Group,
    Rectangle,
    ReplacementTransform,
    Square,
    VGroup,
)
from manim.mobject.text.tex_mobject import MathTexPart

from animath.core.errors import AnimateError
from animath.core.schemas import Line as Spoken
from animath.core.schemas import Narration, Params, Scene, Visual, Word
from animath.core.store import Store
from animath.scene import compose, render, schedule, timeline
from animath.scene.primitives import Cue
from animath.scene.primitives.base import ENTER_S, Action
from animath.scene.render import EXIT_S, MORPH_S, Clip, Timeline, norm, shoot
from tests.scene.conftest import F, context

H = "0" * 64
TL = Timeline({"a": 0.0, "b": 2.35}, 4.0, (("x", 0.0), ("y", 1.0), ("z", 2.35)))


def scn(*visuals: Visual, duration: float = 4.0) -> Scene:
    """At 60 wpm: `x y` from 0 s, then `z` from 2.35 s with a 0.65 s pause."""
    lines = (Spoken(text="x y", bookmark="a"), Spoken(text="z", bookmark="b", pause_s=0.65))
    return Scene(id="s", goal="g", narration=lines, visuals=visuals, duration_s=duration)


def eq(latex: str = "x + y", at: str | None = None, **args: Any) -> Visual:
    return Visual(primitive="equation", args={"latex": latex, **args}, at=at)


def narration(**kw: Any) -> Narration:
    return Narration(**{"scene_id": "s", "audio": H, "duration_s": 5.0, **kw})


def test_norm() -> None:
    assert norm("Cluster,") == "cluster"
    assert norm("RS-S") == "rss"


def test_timeline_estimated() -> None:
    assert timeline(scn(), None, 60) == TL
    tl = timeline(scn(duration=8.0), None, 60)
    assert tl.marks == {"a": 0.0, "b": 4.7}
    assert tl.words[1] == ("y", 2.0)


def test_timeline_from_narration() -> None:
    words = (Word(text="Z!", start=3.5, end=3.9),)
    tl = timeline(scn(), narration(bookmarks={"a": 0.5, "b": 3.0}, words=words))
    assert tl == Timeline({"a": 0.5, "b": 3.0}, 5.0, (("z", 3.5),))
    with pytest.raises(AnimateError, match="narration of t"):
        timeline(scn(), narration(scene_id="t", bookmarks={"a": 0.0, "b": 1.0}))
    with pytest.raises(AnimateError, match=r"lacks bookmarks \['b'\]"):
        timeline(scn(), narration(bookmarks={"a": 0.5}))


@pytest.mark.parametrize(
    ("action", "t"),
    [
        (Action(at="a", word="y", do="dim"), 1.0),
        (Action(at="a", frac=0.5, do="dim"), 1.175),
        (Action(at="a", word="z", do="dim"), 0.0),
        (Action(at="b", word="Z", do="dim", frac=0.5), 2.35),
        (Action(at="b", word="w", do="dim", frac=0.5), 3.175),
    ],
)
def test_timeline_time(action: Action, t: float) -> None:
    assert TL.slot("a") == (0.0, 2.35)
    assert TL.time(action) == pytest.approx(t)


def cue(t: float, rt: float) -> Cue:
    return Cue(t, rt, partial(FadeIn, Square()))


def test_schedule() -> None:
    a, b, c, d, e = cue(0.0, 1.0), cue(0.01, 0.2), cue(0.5, 2.0), cue(0.55, 0.0), cue(2.0, 1.0)
    steps = schedule([c, a, b, d, e], 2.0, 10)
    assert steps == [(0, 20, [(0, 10, a), (0, 2, b), (5, 15, c), (6, 0, d)])]
    f, g = cue(0.0, 0.3), cue(0.3, 0.0)
    assert schedule([g, f], 1.0, 10) == [(0, 3, [(0, 3, f)]), (3, 1, [(0, 0, g)])]
    assert schedule([], 2.0, 10) == []


def test_compose_entries_and_exits(store: Store) -> None:
    txt = Visual(primitive="text", args={"text": "T", "region": "title"}, at="b")
    keep = Visual(primitive="text", args={"text": "K", "region": "footer", "persist": True})
    (e, t, k) = compose(scn(eq(until="b"), txt, keep), context(store), TL, F)
    assert (e.placement.t0, e.placement.t1, t.placement.t0, t.placement.t1) == (0, 2.35, 2.35, 4)
    assert [(c.t, c.run_time) for c in e.cues] == [(0.0, ENTER_S), (2.35 - EXIT_S, EXIT_S)]
    assert [c.t for c in t.cues] == [2.35, 4.0 - EXIT_S]
    assert [c.t for c in k.cues] == [0.0]
    assert e.placement.scale == 1.0
    assert e.cues[0].mobject is e.mobject


def test_compose_shrinks_to_cell(store: Store) -> None:
    s = scn(eq("+".join("x" * 80), region="left"))
    (it,) = compose(s, context(store), TL, F)
    assert it.placement.scale < 1.0
    assert it.placement.box.width == pytest.approx(0.45 * F.width)


def test_compose_entry_modes(store: Store) -> None:
    v = [eq(until="b"), eq("y", "b", replaces=0), eq("z", region="title", enter="none")]
    v.append(eq("w", region="footer", enter="fade"))
    (a, b, c, d) = compose(scn(*v), context(store), TL, F)
    assert [x.t for x in a.cues] == [0.0]
    morph = b.cues[0]
    assert (morph.t, morph.run_time) == (2.35, MORPH_S)
    assert isinstance(morph.mobject, Group)
    assert type(morph.play()).__name__ == "TransformMatchingTex"
    assert (c.cues[0].run_time, d.cues[0].run_time) == (0.0, ENTER_S)
    assert isinstance(d.cues[0].play(), FadeIn)
    grid = Visual(primitive="matrix", args={"entries": [["1"]], "replaces": 0}, at="b")
    (_, m) = compose(scn(eq(until="b"), grid), context(store), TL, F)
    assert isinstance(m.cues[0].play(), ReplacementTransform)


def test_compose_actions(store: Store) -> None:
    acts = [
        {"do": "mark", "parts": ["x"], "color": "RED"},
        {"at": "a", "word": "y", "do": "show", "parts": ["y"]},
        {"at": "b", "do": "indicate", "parts": ["x"]},
        {"at": "b", "do": "dim", "rate": 4.0},
        {"at": "b", "frac": 0.9, "do": "unmark", "parts": ["x"]},
    ]
    (it,) = compose(scn(eq(actions=acts)), context(store), TL, F)
    m = it.mobject
    x, y = (m.get_part_by_tex(s).family_members_with_points()[0] for s in "xy")
    assert x.get_color() == manim.RED
    assert y.get_fill_opacity() == 0.0
    timed = [(c.t, c.run_time, c.what) for c in it.cues if c.what]
    assert timed == [
        (1.5, 1.0, "s.0:equation: show y at 1.50 s"),
        (2.35, 1.0, "s.0:equation: indicate x at 2.35 s"),
        (2.35, 0.25, "s.0:equation: dim at 2.35 s"),
        (2.4, 1.0, "s.0:equation: unmark x at 2.40 s"),
    ]
    show = it.cues[1].play()
    show.begin()
    show.finish()
    assert y.get_fill_opacity() == 1.0
    unmark = it.cues[4].play()
    unmark.begin()
    unmark.finish()
    assert x.get_color() == manim.WHITE


@pytest.mark.parametrize(
    ("visual", "match"),
    [
        (Visual(primitive="nope"), "unknown primitive"),
        (eq(""), "invalid args"),
        (eq(until="z"), "unknown bookmark 'z'"),
        (eq(actions=[{"at": "q", "do": "dim"}]), "unknown bookmark 'q'"),
        (eq(until="a", at="b"), "empty interval"),
        (eq(r"\frac{"), "build failed"),
        (Visual(primitive="field", args={"values": {"data": 0, "array": "u"}}), "missing"),
        (eq(actions=[{"at": "a", "do": "show"}]), "show needs parts"),
        (eq(actions=[{"at": "a", "do": "fly"}]), "unknown verb 'fly'; known: "),
        (eq(actions=[{"at": "a", "do": "dim", "parts": ["q"]}]), "no part 'q'"),
        (eq(replaces=0), "replaces 0: needs an earlier visual"),
    ],
)
def test_compose_rejects(store: Store, visual: Visual, match: str) -> None:
    with pytest.raises(AnimateError, match=match):
        compose(scn(visual), context(store), TL, F)


def test_compose_own_cues_run_between_entry_and_exit(store: Store) -> None:
    d = Visual(primitive="derive", args={"steps": ["a", "b", "c"]})
    (it,) = compose(scn(d), context(store), TL, F)
    s = (4.0 - EXIT_S - ENTER_S) / 3
    assert [c.t for c in it.cues] == pytest.approx([0.0, ENTER_S + s, ENTER_S + 2 * s, 4 - EXIT_S])
    assert [c.run_time for c in it.cues] == pytest.approx([ENTER_S, 0.8 * s, 0.8 * s, EXIT_S])
    tl = Timeline({"a": 0.0, "b": 1.0}, 2.0)
    with pytest.raises(
        AnimateError, match=r"derive: no time for its animations in \[1\.50, 1\.40\)"
    ):
        compose(scn(d), context(store), tl, F)


@pytest.mark.parametrize("until", [1.8, 1.0])
def test_compose_actions_end_before_the_exit(store: Store, until: float) -> None:
    v = eq(until="b", actions=[{"at": "a", "do": "show", "parts": ["x"]}])
    tl = Timeline({"a": 0.0, "b": until}, 4.0)
    with pytest.raises(AnimateError, match=r"show x: no room between the entry end 1\.50 s and"):
        compose(scn(v), context(store), tl, F)
    (it,) = compose(scn(v), context(store), Timeline({"a": 0.0, "b": 3.0}, 4.0), F)
    show = it.cues[1]
    assert (show.t, show.run_time) == pytest.approx((ENTER_S, 3.0 - EXIT_S - ENTER_S))
    assert show.t + show.run_time == pytest.approx(it.cues[2].t)


def test_compose_resumes_a_view(store: Store) -> None:
    steps = {"steps": ["a", "b", "c"], "enter": "fade"}
    nxt, late = [{"do": "next"}], [{"at": "a", "do": "next"}]
    for args, shown, n in (
        ({}, 0, 4),
        ({"actions": nxt}, 1, 2),
        ({"resume": True}, 2, 2),
        ({"resume": True, "actions": late}, 2, 3),
    ):
        (it,) = compose(scn(Visual(primitive="derive", args=steps | args)), context(store), TL, F)
        assert len(it.cues) == n
        entered: object = it.cues[0].play().mobject
        assert entered is it.mobject[shown]
    with pytest.raises(AnimateError, match="next after the last of 3 steps"):
        it.cues[1].play()


def frames_of(path: str) -> list[np.ndarray]:
    with av.open(path) as f:
        return [x.to_ndarray(format="rgb24").astype(int) for x in f.decode(video=0)]


def play(cues: list[Cue], duration: float, fps: int = 10) -> list[np.ndarray]:
    """Clip of `cues` at 160 x 90 pixels over a 16 x 9 frame."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg: dict[str, Any] = {"pixel_width": 160, "pixel_height": 90, "frame_rate": fps}
        cfg |= {"frame_width": 16.0, "frame_height": 9.0, "media_dir": tmp, "disable_caching": True}
        with manim.tempconfig(cfg | {"output_file": "c", "progress_bar": "none"}):
            clip = Clip(schedule(cues, duration, fps), duration, fps)
            clip.render()
            return frames_of(str(clip.renderer.file_writer.movie_file_path))


def at(img: np.ndarray, x: float, y: float = 0.0) -> Any:
    return img[round((4.5 - y) * 10), round((x + 8.0) * 10)]


def test_overlapping_cues_keep_their_run_times() -> None:
    left, right = Square().shift(4 * manim.LEFT), Square().shift(4 * manim.RIGHT)
    red = partial(lambda: left.animate.set_fill(RED, 1.0).build())
    blue = partial(lambda: right.animate.set_fill(BLUE, 1.0).build())
    cues = [
        Cue(0.0, 0.0, partial(FadeIn, Group(left, right))),
        Cue(0.5, 1.0, red),
        Cue(1.0, 1.0, blue),
    ]
    imgs = play(cues, 2.5)
    assert len(imgs) == 25
    assert np.abs(at(imgs[15], -4) - [252, 98, 85]).max() < 12
    half = at(imgs[15], 4).sum()
    assert 0.25 < half / at(imgs[24], 4).sum() < 0.75
    assert np.abs(at(imgs[24], 4) - [88, 196, 221]).max() < 12


def test_action_objects_leave_with_their_visual() -> None:
    sq = Square().shift(4 * manim.LEFT)
    line = Rectangle(width=3.0, height=1.0, fill_opacity=1.0).shift(1.5 * manim.RIGHT)
    cues = [
        Cue(0.0, 0.0, partial(FadeIn, sq)),
        Cue(0.2, 0.3, partial(Create, line), sq, "s.0:code: draw"),
        Cue(1.0, 0.5, partial(FadeOut, sq), sq),
    ]
    imgs = play(cues, 2.0)
    assert at(imgs[8], 1.5).max() > 128
    assert line in sq.submobjects
    assert max(int(i.max()) for i in imgs[16:]) < 16


def test_objects_of_a_split_visual_stay_until_its_exit() -> None:
    a, b = Square().shift(5 * manim.LEFT), Square().shift(2 * manim.LEFT)
    m, new = VGroup(a, b), Circle(fill_opacity=1.0).shift(3 * manim.RIGHT)
    cues = [
        Cue(0.0, 0.0, partial(FadeIn, m)),
        Cue(0.2, 0.3, lambda: AnimationGroup(FadeOut(a), Create(new)), m, "s.0:code: swap"),
        Cue(1.0, 0.5, partial(FadeOut, m), m),
    ]
    imgs = play(cues, 2.0)
    assert at(imgs[8], 3).max() > 128
    assert at(imgs[8], -5, 1).max() < 16
    assert new in m.submobjects
    assert max(int(i.max()) for i in imgs[16:]) < 16


@pytest.mark.parametrize("split", [False, True])
def test_a_visual_morphs_whole(split: bool) -> None:
    a, b = (Square(fill_opacity=1.0).shift(x * manim.LEFT) for x in (5, 2))
    m, target = VGroup(a, b), Circle(fill_opacity=1.0).shift(3 * manim.RIGHT)
    drop = [Cue(0.2, 0.3, partial(FadeOut, a), m, "s.0:code: drop")] if split else []
    cues = [
        Cue(0.0, 0.0, partial(FadeIn, m)),
        *drop,
        Cue(1.0, 0.5, partial(ReplacementTransform, m, target), Group(m, target)),
    ]
    imgs = play(cues, 2.0)
    assert at(imgs[8], -2).min() > 128
    assert (at(imgs[8], -5).max() < 16) == split
    assert at(imgs[-1], 3).max() > 128
    assert max(at(imgs[-1], -5).max(), at(imgs[-1], -2).max()) < 16


def test_entries_draw_translucent_mobjects_once() -> None:
    dim = Square(fill_opacity=0.3).shift(4 * manim.LEFT)
    cues = [
        Cue(0.0, 0.0, partial(FadeIn, dim)),
        Cue(0.5, 1.0, partial(FadeIn, Square().shift(4 * manim.RIGHT))),
    ]
    imgs = play(cues, 2.0)
    assert np.abs(at(imgs[10], -4) - at(imgs[18], -4)).max() < 4


def test_primitive_verbs_play(store: Store) -> None:
    nxt = {"at": "b", "do": "next"}
    d = Visual(primitive="derive", args={"steps": ["x", "x + y"], "actions": [nxt]})
    go = {"at": "b", "do": "goto", "parts": ["line:1"]}
    t = Visual(
        primitive="trace",
        args={"lines": ["a", "b"], "steps": [0], "actions": [go], "region": "title"},
    )
    out, cues = shoot(scn(d, t, duration=6.0), Params(), store, draft=True)
    imgs = frames_of(str(store.blob_path(out.clip)))
    labels = [c.what for c in cues if c.what]
    assert labels == ["s.0:derive: next at 3.19 s", "s.1:trace: goto line:1 at 3.19 s"]
    assert np.abs(imgs[47] - imgs[66]).max() > 128
    assert max(int(i.max()) for i in imgs[-1:]) < 64


def test_a_shown_term_morphs_with_its_equation(store: Store) -> None:
    def clip(*acts: dict[str, Any]) -> tuple[list[np.ndarray], list[Cue]]:
        s = scn(eq(until="b", actions=list(acts)), eq("x + z", "b", replaces=0))
        out, cues = shoot(s, Params(), store, draft=True)
        return frames_of(str(store.blob_path(out.clip))), cues

    imgs, cues = clip({"at": "a", "do": "show", "parts": ["y"]})
    ref, _ = clip()
    m = cues[0].mobject
    assert m is not None
    assert {type(x) for x in m.submobjects} == {MathTexPart}
    assert np.abs(imgs[20] - ref[20]).max() > 128
    assert max(int(np.abs(a - b).max()) for a, b in zip(imgs[36:], ref[36:], strict=True)) <= 8


@pytest.mark.parametrize(
    ("what", "match"),
    [
        ("s.0:x: dim at 0.10 s", r"^s\.0:x: dim at 0\.10 s failed: ValueError: bad part$"),
        ("", r"^cue at 0\.10 s failed: ValueError: bad part$"),
    ],
)
def test_failed_cue_names_its_action(what: str, match: str) -> None:
    def boom() -> Animation:
        raise ValueError("bad part")

    with pytest.raises(AnimateError, match=match):
        play([Cue(0.1, 0.2, boom, Square(), what)], 0.5)


def test_render_clip(store: Store) -> None:
    s = scn(eq(until="b"), eq("y", "b"), duration=2.0)
    nar = narration(duration_s=2.4, bookmarks={"a": 0.0, "b": 1.2})
    out = render(s, Params(width=320, height=240, fps=15), store, nar)
    assert (out.scene_id, out.duration_s, out.bookmarks) == ("s", 2.4, {"a": 0.0, "b": 1.2})
    assert out.checks == {"layout": True, "render": True}
    assert len(frames_of(str(store.blob_path(out.clip)))) == 36
    with av.open(str(store.blob_path(out.clip))) as f:
        v = f.streams.video[0]
        assert (v.codec_context.name, v.width, v.height) == ("h264", 320, 240)
    assert b" mbtree=0 " in store.get_blob(out.clip)
    draft, cues = shoot(s, Params(), store, draft=True)
    with av.open(str(store.blob_path(draft.clip))) as f:
        assert (f.streams.video[0].width, f.streams.video[0].height) == (426, 240)
    assert len(frames_of(str(store.blob_path(draft.clip)))) == 30
    assert len(cues) == 4
    assert render(s, Params(), store, draft=True).clip == draft.clip


def test_render_plays_actions(store: Store) -> None:
    v = eq(actions=[{"at": "b", "do": "mark", "parts": ["y"], "color": "#FF0000"}])
    out = render(scn(v), Params(), store, draft=True)
    imgs = frames_of(str(store.blob_path(out.clip)))

    def red(img: np.ndarray) -> int:
        return int((img[..., 0] - img[..., 1:].max(axis=2) > 60).sum())

    assert red(imgs[30]) == 0
    assert red(imgs[48]) > 20


def test_render_rejects_layout(store: Store) -> None:
    s = scn(eq(until="b"), eq("y"), duration=2.0)
    with pytest.raises(AnimateError, match=r"layout: s\.0:equation overlaps s\.1:equation"):
        render(s, Params(), store, draft=True)


def test_render_wraps_failure(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: Clip) -> None:
        raise RuntimeError("cairo")

    monkeypatch.setattr(Clip, "construct", fail)
    with pytest.raises(AnimateError, match="render failed: cairo"):
        render(scn(duration=1.0), Params(), store, draft=True)
