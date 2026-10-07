import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from itertools import groupby
from pathlib import Path
from typing import Any

import manim
from manim import FadeOut, Mobject
from pydantic import ValidationError

from animath.core.errors import AnimateError
from animath.core.schemas import DataSet, Narration, Params, Scene, SceneRender
from animath.core.store import Store
from animath.scene.layout import Box, Placement, cell, frame, violations
from animath.scene.primitives import PRIMITIVES, Context, Cue

FRAME_HEIGHT = 8.0
DRAFT_HEIGHT, DRAFT_FPS = 240, 15
EXIT_S = 0.5

Step = tuple[float, float, list[Cue]]


@dataclass(frozen=True)
class Item:
    placement: Placement
    mobject: Mobject
    cues: list[Cue]


def timeline(scene: Scene, narration: Narration | None) -> tuple[dict[str, float], float]:
    """Bookmark times and duration: from narration, else line i at i·T/n."""
    if narration is None:
        dt = scene.duration_s / len(scene.narration)
        times = {ln.bookmark: i * dt for i, ln in enumerate(scene.narration) if ln.bookmark}
        return times, scene.duration_s
    if narration.scene_id != scene.id:
        raise AnimateError(f"narration of {narration.scene_id} given for scene {scene.id}")
    missing = sorted(
        {ln.bookmark for ln in scene.narration if ln.bookmark} - set(narration.bookmarks)
    )
    if missing:
        raise AnimateError(f"scene {scene.id}: narration lacks bookmarks {missing}")
    return dict(narration.bookmarks), narration.duration_s


def compose(
    scene: Scene, ctx: Context, times: Mapping[str, float], duration: float, f: Box
) -> list[Item]:
    """Build every visual, fit it into its grid cell, and attach its cues."""
    items = []
    for i, v in enumerate(scene.visuals):
        name = f"{scene.id}.{i}:{v.primitive}"
        p = PRIMITIVES.get(v.primitive)
        if p is None:
            raise AnimateError(f"{name}: unknown primitive")
        try:
            a = p.args.model_validate(v.args)
        except ValidationError as e:
            raise AnimateError(f"{name}: invalid args: {e}") from e
        if a.until is not None and a.until not in times:
            raise AnimateError(f"{name}: unknown bookmark {a.until!r}")
        t0, t1 = times[v.at] if v.at else 0.0, times[a.until] if a.until else duration
        if not t0 < t1:
            raise AnimateError(f"{name}: empty interval [{t0}, {t1}]")
        c = cell(a.region, f)
        try:
            m = p.build(a, ctx, c)
        except AnimateError:
            raise
        except Exception as e:
            raise AnimateError(f"{name}: build failed: {e}") from e
        s = min(1.0, c.width / max(m.width, 1e-9), c.height / max(m.height, 1e-9))
        m.scale(s).move_to((c.center[0], c.center[1], 0.0))
        box = Box(m.get_left()[0], m.get_bottom()[1], m.get_right()[0], m.get_top()[1])
        cues = p.cues(m, a, t0, t1)
        if a.until:
            cues.append(Cue(max(t0, t1 - EXIT_S), EXIT_S, partial(FadeOut, p.last(m))))
        items.append(Item(Placement(name, box, t0, t1, s), m, cues))
    return items


def schedule(cues: list[Cue], duration: float, fps: int) -> list[Step]:
    """Group cues by frame; each group plays for min(max run time, gap to next group)."""
    n_end = round(duration * fps)
    frames = sorted(
        (round(c.t * fps), k, c) for k, c in enumerate(cues) if round(c.t * fps) < n_end
    )
    groups = [(n, [c for _, _, c in g]) for n, g in groupby(frames, key=lambda e: e[0])]
    ends = [n for n, _ in groups[1:]] + [n_end] * bool(groups)
    return [
        (n / fps, max(1, min(round(max(c.run_time for c in g) * fps), e - n)) / fps, g)
        for (n, g), e in zip(groups, ends, strict=True)
    ]


class Clip(manim.Scene):
    def __init__(self, steps: list[Step], duration: float, fps: int, **kw: Any) -> None:
        super().__init__(**kw)
        self.steps, self.t_end, self.fps = steps, duration, fps

    def _wait_until(self, t: float) -> None:
        n = round((t - self.time) * self.fps)
        if n > 0:
            self.wait(n / self.fps)

    def construct(self) -> None:
        for t, rt, cues in self.steps:
            self._wait_until(t)
            self.play(*(c.play() for c in cues), run_time=rt)
        self._wait_until(self.t_end)


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
    times, duration = timeline(scene, narration)
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
            items = compose(
                scene, Context(scene, store, datasets or {}, h / f.height), times, duration, f
            )
            bad = violations([it.placement for it in items], f)
            if bad:
                raise AnimateError(f"scene {scene.id}: layout: {'; '.join(bad)}")
            clip = Clip(
                schedule([c for it in items for c in it.cues], duration, fps), duration, fps
            )
            try:
                clip.render()
            except Exception as e:
                raise AnimateError(f"scene {scene.id}: render failed: {e}") from e
            blob = store.put_blob(Path(clip.renderer.file_writer.movie_file_path).read_bytes())
    return SceneRender(
        scene_id=scene.id,
        clip=blob,
        duration_s=duration,
        bookmarks=times,
        checks={"layout": True, "render": True},
    )
