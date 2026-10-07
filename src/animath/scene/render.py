import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any

import manim
from manim import (
    Animation,
    AnimationGroup,
    FadeIn,
    FadeOut,
    Group,
    MathTex,
    Mobject,
    ReplacementTransform,
    TransformMatchingTex,
    linear,
)
from manim.animation.animation import prepare_animation
from manim.renderer.cairo_renderer import CairoRenderer
from manim.scene.scene_file_writer import SceneFileWriter
from pydantic import ValidationError

from animath.core.errors import AnimateError
from animath.core.schemas import DataSet, Narration, Params, Scene, SceneRender
from animath.core.store import Store
from animath.scene.layout import Box, Placement, cell, frame, violations
from animath.scene.primitives import PRIMITIVES, Args, Context, Cue, Primitive
from animath.scene.primitives.base import (
    ENTER_S,
    MIN_S,
    VERB_S,
    VERBS,
    Action,
    color,
    instant,
    verb,
)

FRAME_HEIGHT = 8.0
DRAFT_HEIGHT, DRAFT_FPS = 240, 15
EXIT_S, MORPH_S, GAP_S = 0.6, 1.2, 0.35
TOKEN = re.compile(r"[^\W_]+")

Step = tuple[int, int, list[tuple[int, int, Cue]]]


def norm(word: str) -> str:
    return "".join(TOKEN.findall(word.casefold()))


@dataclass(frozen=True)
class Timeline:
    """Bookmark onsets, duration and word onsets (normalized text, start) of a scene."""

    marks: dict[str, float]
    duration: float
    words: tuple[tuple[str, float], ...] = ()

    def slot(self, mark: str) -> tuple[float, float]:
        t = self.marks[mark]
        return t, min((u for u in self.marks.values() if u > t), default=self.duration)

    def time(self, a: Action) -> float:
        """Onset of `a.word` within the slot of `a.at`, else the slot point `a.frac`."""
        t0, t1 = self.slot(str(a.at))
        w = norm(a.word or "")
        hit = [s for x, s in self.words if w and t0 <= s < t1 and x == w]
        return hit[0] if hit else t0 + a.frac * (t1 - t0)


def timeline(scene: Scene, narration: Narration | None, wpm: int = 135) -> Timeline:
    """From narration; else line slots in proportion to speech at `wpm`, gaps and pauses."""
    if narration is None:
        lines = scene.narration
        speech = [len(ln.text.split()) * 60 / wpm for ln in lines]
        slot = [
            s + ln.pause_s + GAP_S * (i < len(lines) - 1)
            for i, (s, ln) in enumerate(zip(speech, lines, strict=True))
        ]
        k = scene.duration_s / max(sum(slot), 1e-9)
        onset = [k * sum(slot[:i]) for i in range(len(lines))]
        marks = {ln.bookmark: t for ln, t in zip(lines, onset, strict=True) if ln.bookmark}
        words = tuple(
            (norm(w), t + k * s * j / len(ws))
            for ln, t, s in zip(lines, onset, speech, strict=True)
            for ws in [ln.text.split()]
            for j, w in enumerate(ws)
        )
        return Timeline(marks, scene.duration_s, words)
    if narration.scene_id != scene.id:
        raise AnimateError(f"narration of {narration.scene_id} given for scene {scene.id}")
    missing = sorted(
        {ln.bookmark for ln in scene.narration if ln.bookmark} - set(narration.bookmarks)
    )
    if missing:
        raise AnimateError(f"scene {scene.id}: narration lacks bookmarks {missing}")
    words = tuple((norm(w.text), w.start) for w in narration.words)
    return Timeline(dict(narration.bookmarks), narration.duration_s, words)


@dataclass(frozen=True)
class Item:
    placement: Placement
    mobject: Mobject
    cues: list[Cue]


def actions(
    p: Primitive[Any], a: Args, m: Mobject, tl: Timeline, t0: float, t1: float, name: str
) -> list[Cue]:
    """Initial-state actions applied now; timed ones as cues between the entry and the exit."""
    sels = {s for x in a.actions for s in x.parts or [""]}
    parts = {s: p.part(m, a, s) if s else m for s in sorted(sels)}
    orig = {s: q.copy() for s, q in parts.items()}
    for x in a.actions:
        if x.do == "show" and not x.parts:
            raise AnimateError("show needs parts")
        if x.do not in VERBS and not p.knows(m, x.do):
            raise AnimateError(f"unknown verb {x.do!r}; known: {[*VERBS, *p.verbs]}")
        if x.at is None and x.do in p.timed:
            raise AnimateError(f"{x.do} needs a bookmark")
        for s in x.parts if x.do == "show" else ():
            parts[s].set_opacity(0.0)

    def make(x: Action) -> Animation:
        if x.do not in VERBS:
            return prepare_animation(p.act(m, a, x.do, x.parts))
        c = color(x.color)
        anims = [verb(x.do, parts[s], orig[s], c) for s in x.parts or [""]]
        return anims[0] if len(anims) == 1 else AnimationGroup(*anims)

    out = []
    for x in a.actions:
        what = f"{name}: {x.do} {' '.join(x.parts)}".rstrip()
        if x.at is None:
            instant(make(x))
            continue
        rt = max(MIN_S, VERB_S / x.rate)
        t = max(t0, min(tl.time(x), t1 - EXIT_S - rt))
        if t >= t1:
            raise AnimateError(f"{what}: no time left after the entry, before {t1:.2f} s")
        out.append(Cue(t, rt, partial(make, x), m, f"{what} at {t:.2f} s"))
    return out


def leave(p: Primitive[Any], m: Mobject) -> Animation:
    return FadeOut(p.last(m))


def morph(src: Mobject, dst: Mobject) -> Animation:
    if isinstance(src, MathTex) and isinstance(dst, MathTex):
        return TransformMatchingTex(src, dst)
    return ReplacementTransform(src, dst)


def entry(
    p: Primitive[Any], a: Args, m: Mobject, cue: Cue, items: list[Item], scene: Scene, i: int
) -> Cue:
    if a.replaces is not None:
        k = a.replaces
        if (
            k >= i
            or not scene.visuals[i].at
            or scene.visuals[k].args.get("until") != scene.visuals[i].at
        ):
            raise AnimateError(f"replaces {k}: needs an earlier visual whose until is this at")
        q, mk = PRIMITIVES[scene.visuals[k].primitive], items[k].mobject
        return Cue(cue.t, MORPH_S, lambda: morph(q.last(mk), p.first(m)), Group(mk, m))
    if a.enter == "none":
        return Cue(cue.t, 0.0, partial(FadeIn, p.first(m)), m)
    if a.enter == "fade":
        return Cue(cue.t, ENTER_S, partial(FadeIn, p.first(m)), m)
    return replace(cue, mobject=m)


def compose(scene: Scene, ctx: Context, tl: Timeline, f: Box) -> list[Item]:
    """Build every visual, fit it into its grid cell, and attach entry, action and exit cues."""
    items: list[Item] = []
    args: list[Args] = []
    for i, v in enumerate(scene.visuals):
        name = f"{scene.id}.{i}:{v.primitive}"
        p = PRIMITIVES.get(v.primitive)
        if p is None:
            raise AnimateError(f"{name}: unknown primitive")
        try:
            a = p.args.model_validate(v.args)
        except ValidationError as e:
            raise AnimateError(f"{name}: invalid args: {e}") from e
        bad = sorted({b for b in [a.until, *(x.at for x in a.actions)] if b} - set(tl.marks))
        if bad:
            raise AnimateError(f"{name}: unknown bookmark {bad[0]!r}")
        t0, t1 = tl.marks[v.at] if v.at else 0.0, tl.marks[a.until] if a.until else tl.duration
        if not t0 < t1:
            raise AnimateError(f"{name}: empty interval [{t0}, {t1}]")
        c = cell(a.region, f)
        try:
            m = p.build(a, ctx, c)
            s = min(1.0, c.width / max(m.width, 1e-9), c.height / max(m.height, 1e-9))
            m.scale(s).move_to((c.center[0], c.center[1], 0.0))
            own = p.cues(m, a, t0, t1)
            first = entry(p, a, m, own[0], items, scene, i)
            later = actions(p, a, m, tl, first.t + first.run_time, t1, name)
        except AnimateError as e:
            raise AnimateError(f"{name}: {e}") from e
        except Exception as e:
            raise AnimateError(f"{name}: build failed: {e}") from e
        cues = [first, *(replace(x, mobject=m) for x in own[1:]), *later]
        box = Box(m.get_left()[0], m.get_bottom()[1], m.get_right()[0], m.get_top()[1])
        items.append(Item(Placement(name, box, t0, t1, s), m, cues))
        args.append(a)
    gone = {a.replaces for a in args if a.replaces is not None}
    for i, (it, a) in enumerate(zip(items, args, strict=True)):
        if i not in gone and (a.until or not a.persist):
            t = max(it.placement.t0, it.placement.t1 - EXIT_S)
            q = PRIMITIVES[scene.visuals[i].primitive]
            it.cues.append(Cue(t, EXIT_S, partial(leave, q, it.mobject), it.mobject))
    return items


def schedule(cues: list[Cue], duration: float, fps: int) -> list[Step]:
    """Algorithm 9.2: cues as frame intervals, merged into clusters where they overlap."""
    end = round(duration * fps)
    starts = sorted(
        ((round(c.t * fps), k, c) for k, c in enumerate(cues) if round(c.t * fps) < end),
        key=lambda e: e[:2],
    )
    steps: list[Step] = []
    for s, _, c in starts:
        n = min(round(c.run_time * fps), end - s)
        if steps and s < steps[-1][0] + steps[-1][1]:
            s0, length, group = steps[-1]
            steps[-1] = (s0, max(length, s - s0 + max(n, 1)), [*group, (s - s0, n, c)])
        else:
            steps.append((s, max(n, 1), [(0, n, c)]))
    return steps


class Delayed(Animation):
    """Cue starting `d` frames into a cluster of `n` frames and lasting `k`; set up at its start
    and cleaned up at its end, so overlapping cues each keep their own run time."""

    def __init__(self, cue: Cue, d: int, k: int, n: int, fps: int) -> None:
        mob = cue.mobject if cue.mobject is not None else Mobject()
        super().__init__(mob, run_time=n / fps, rate_func=linear, introducer=True)
        self.cue, self.d, self.k, self.fps = cue, d, k, fps
        self.inner: Animation | None = None
        self.done = False

    def _setup_scene(self, scene: Any) -> None:
        self.scene = scene

    def begin(self) -> None:
        pass

    def update_mobjects(self, dt: float) -> None:
        if self.inner is not None and not self.done:
            self.inner.update_mobjects(dt)

    def interpolate(self, alpha: float) -> None:
        self.at(round(alpha * self.run_time * self.fps))

    def at(self, frame: int) -> None:
        if self.done or frame < self.d:
            return
        if self.inner is None:
            self.before = {id(x) for x in self.scene.mobjects}
            try:
                self.inner = prepare_animation(self.cue.play())
            except Exception as e:
                raise AnimateError(f"{self.cue.what or 'cue'} failed: {e}") from e
            self.inner.run_time = max(self.k, 1) / self.fps
            self.inner._setup_scene(self.scene)
            self.inner.begin()
        if frame < self.d + self.k:
            self.inner.interpolate((frame - self.d) / self.k)
            return
        self.inner.finish()
        self.inner.clean_up_from_scene(self.scene)
        self.done = True
        if self.cue.what and self.cue.mobject is not None:
            self.adopt(self.cue.mobject)
        live = {id(x) for x in self.scene.get_mobject_family_members()}
        self.scene.moving_mobjects = [x for x in self.scene.moving_mobjects if id(x) in live]

    def adopt(self, m: Mobject) -> None:
        """Objects an action added to the scene join its visual, so they leave with it."""
        own = {id(x) for x in m.get_family()} | self.before
        new = [x for x in self.scene.mobjects if id(x) not in own]
        m.add(*new)
        if any(x is m for x in self.scene.mobjects):
            self.scene.mobjects = [x for x in self.scene.mobjects if all(x is not y for y in new)]

    def finish(self) -> None:
        self.at(self.d + self.k)

    def clean_up_from_scene(self, scene: Any) -> None:
        pass


class Writer(SceneFileWriter):
    """x264 without MB-tree, whose AVX-512 code reads uninitialized memory, so clips are
    byte-identical across runs."""

    def open_partial_movie_stream(self, file_path: Any = None) -> None:
        super().open_partial_movie_stream(file_path)
        assert self._current_encode_job is not None
        self._current_encode_job.stream.codec_context.options["x264-params"] = "mbtree=0"


class Clip(manim.Scene):
    def __init__(self, steps: list[Step], duration: float, fps: int, **kw: Any) -> None:
        super().__init__(renderer=CairoRenderer(file_writer_class=Writer), **kw)
        self.steps, self.t_end, self.fps = steps, duration, fps

    def remove(self, *mobjects: Mobject) -> "Clip":
        """Also drops the parts of `mobjects` that a removal of one of their parts split off
        into the top level, so a visual leaves whole."""
        super().remove(*mobjects)
        fam = {id(x) for m in mobjects for x in m.get_family()}
        self.mobjects = [x for x in self.mobjects if id(x) not in fam]
        return self

    def replace(self, old: Mobject, new: Mobject) -> None:
        """Also when `old` was split into its parts."""
        if any(x is old for x in self.get_mobject_family_members()):
            super().replace(old, new)
        else:
            self.remove(old)
            self.add(new)

    def get_moving_mobjects(self, *animations: Animation) -> list[Mobject]:
        """All mobjects when no animated one is on screen yet, so an entering mobject is not
        drawn over a cached frame that holds translucent mobjects twice."""
        return super().get_moving_mobjects(*animations) or self.get_mobject_family_members()

    def _wait_until(self, t: float) -> None:
        n = round((t - self.time) * self.fps)
        if n > 0:
            self.wait(n / self.fps)

    def construct(self) -> None:
        for s, n, group in self.steps:
            self._wait_until(s / self.fps)
            self.play(*(Delayed(c, d, k, n, self.fps) for d, k, c in group))
        self._wait_until(self.t_end)


def shoot(
    scene: Scene,
    params: Params,
    store: Store,
    narration: Narration | None = None,
    datasets: Mapping[str, DataSet] | None = None,
    draft: bool = False,
) -> tuple[SceneRender, list[Cue]]:
    """`render`, also returning the cues it played."""
    tl = timeline(scene, narration, params.wpm)
    h = DRAFT_HEIGHT if draft else params.height
    w = 2 * round(params.width * h / params.height / 2)
    fps = DRAFT_FPS if draft else params.fps
    f = frame(FRAME_HEIGHT * w / h, FRAME_HEIGHT)
    with tempfile.TemporaryDirectory(prefix="animath-") as tmp:
        cfg = {
            "pixel_width": w,
            "pixel_height": h,
            "frame_rate": fps,
            "frame_height": f.height,
            "frame_width": f.width,
            "media_dir": tmp,
            "output_file": scene.id,
            "disable_caching": True,
            "verbosity": "ERROR",
            "progress_bar": "none",
        }
        with manim.tempconfig(cfg):
            items = compose(scene, Context(scene, store, datasets or {}, h / f.height), tl, f)
            bad = violations([it.placement for it in items], f)
            if bad:
                raise AnimateError(f"scene {scene.id}: layout: {'; '.join(bad)}")
            cues = [c for it in items for c in it.cues]
            clip = Clip(schedule(cues, tl.duration, fps), tl.duration, fps)
            try:
                clip.render()
            except Exception as e:
                raise AnimateError(f"scene {scene.id}: render failed: {e}") from e
            blob = store.put_blob(Path(clip.renderer.file_writer.movie_file_path).read_bytes())
    out = SceneRender(
        scene_id=scene.id,
        clip=blob,
        duration_s=tl.duration,
        bookmarks=tl.marks,
        checks={"layout": True, "render": True},
    )
    return out, cues


def render(
    scene: Scene,
    params: Params,
    store: Store,
    narration: Narration | None = None,
    datasets: Mapping[str, DataSet] | None = None,
    draft: bool = False,
) -> SceneRender:
    """Render `scene` to a silent H.264 clip in `store`. Not thread-safe (Manim global config);
    parallelize over processes."""
    return shoot(scene, params, store, narration, datasets, draft)[0]
