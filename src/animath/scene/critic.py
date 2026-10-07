import json
from io import BytesIO
from itertools import pairwise
from typing import Any

import av
import numpy as np
from numpy.typing import NDArray
from PIL import Image
from pydantic import Field

from animath.core.errors import AnimateError
from animath.core.schemas import Model, Scene, SceneRender, Usage
from animath.core.store import Store
from animath.llm import LLM
from animath.scene.layout import GRID, Region, cell, frame
from animath.scene.primitives import Cue
from animath.scene.render import DRAFT_FPS, FRAME_HEIGHT

KEYFRAMES = 8
BLANK = 16
STATIC_S = 8.0
LEVEL, PIXELS = 32, 24
SYSTEM = """You review keyframes of one scene of an educational mathematics video against its plan.
Report only defects a viewer would notice: overlapping, clipped or illegible objects, empty
visuals, content contradicting the goal, the narration or the mathematics. Name the visual by
index when one is at fault. Return no issues if the scene is acceptable."""


class Issue(Model):
    visual: int | None = None
    problem: str = Field(min_length=1)


class Verdict(Model):
    issues: tuple[Issue, ...] = ()


def spans(scene: Scene, times: dict[str, float], duration: float) -> list[tuple[float, float]]:
    out = []
    for v in scene.visuals:
        u = v.args.get("until")
        out.append((times[v.at] if v.at else 0.0, times[u] if isinstance(u, str) else duration))
    return out


def keyframes(
    scene: Scene, draft: SceneRender, cues: list[Cue], fps: int, k: int = KEYFRAMES
) -> list[tuple[int, list[int]]]:
    """Last still frame (no cue playing) between consecutive cue starts, with the visuals
    alive; at most k."""
    sp = spans(scene, draft.bookmarks, draft.duration_s)
    end = round(draft.duration_s * fps)
    still = np.ones(end, dtype=bool)
    for c in cues:
        still[round(c.t * fps) : round((c.t + c.run_time) * fps)] = False
    cuts = sorted({0, end, *(min(end, round(c.t * fps)) for c in cues)})
    out = []
    for a, b in pairwise(cuts):
        idle = np.flatnonzero(still[a:b])
        if not idle.size:
            continue
        n = a + int(idle[-1])
        live = [i for i, (t0, t1) in enumerate(sp) if round(t0 * fps) <= n < round(t1 * fps)]
        if live:
            out.append((n, live))
    if len(out) > k:
        out = [out[round(j * (len(out) - 1) / (k - 1))] for j in range(k)]
    return out


def static(cues: list[Cue], duration: float) -> list[tuple[float, float]]:
    """Stretches longer than STATIC_S in which no cue plays."""
    out, t = [], 0.0
    for a, b in [*sorted((c.t, c.t + c.run_time) for c in cues), (duration, duration)]:
        if a - t > STATIC_S:
            out.append((t, a))
        t = max(t, b)
    return out


def silent(path: str, cues: list[Cue], fps: int) -> list[Cue]:
    """Labelled cues changing fewer than PIXELS pixels by more than LEVEL against the frame
    before them; frames are streamed."""
    want = [c for c in cues if c.what]
    span = [(max(0, round(c.t * fps) - 1), round((c.t + c.run_time) * fps)) for c in want]
    ref: dict[int, NDArray[np.int16]] = {}
    seen = [0] * len(want)
    with av.open(path) as f:
        for n, fr in enumerate(f.decode(video=0)):
            live = [k for k, (a, b) in enumerate(span) if a <= n <= b]
            if not live:
                continue
            img = np.asarray(fr.to_ndarray(format="rgb24"), dtype=np.int16)
            for k in live:
                if n == span[k][0]:
                    ref[k] = img
                else:
                    seen[k] = max(seen[k], int((np.abs(img - ref[k]).max(axis=2) > LEVEL).sum()))
                if n == span[k][1]:
                    ref.pop(k, None)
    return [c for c, x in zip(want, seen, strict=True) if x < PIXELS]


def frames(path: str, picks: list[int]) -> list[NDArray[np.uint8]]:
    want, got = set(picks), dict[int, NDArray[np.uint8]]()
    with av.open(path) as f:
        for n, fr in enumerate(f.decode(video=0)):
            if n in want:
                got[n] = np.asarray(fr.to_ndarray(format="rgb24"), dtype=np.uint8)
    if want - got.keys():
        raise AnimateError(f"{path}: frames {sorted(want - got.keys())} missing")
    return [got[n] for n in picks]


def blank(img: NDArray[np.uint8], region: Region) -> bool:
    """No pixel brighter than BLANK in the region's grid cell."""
    h, w = img.shape[:2]
    f = frame(FRAME_HEIGHT * w / h, FRAME_HEIGHT)
    c = cell(region, f)
    x0, x1 = int((c.x0 - f.x0) / f.width * w), int(np.ceil((c.x1 - f.x0) / f.width * w))
    y0, y1 = int((f.y1 - c.y1) / f.height * h), int(np.ceil((f.y1 - c.y0) / f.height * h))
    return bool(img[y0:y1, x0:x1].max(initial=0) <= BLANK)


def png(img: NDArray[np.uint8]) -> bytes:
    b = BytesIO()
    Image.fromarray(img).save(b, format="PNG")
    return b.getvalue()


def _region(args: dict[str, Any]) -> Region:
    r = args.get("region", "main")
    return r if r in GRID else "main"


def critique(
    scene: Scene, draft: SceneRender, cues: list[Cue], store: Store, llm: LLM
) -> tuple[list[str], Usage]:
    """Motion checks (static stretches, cues without visible change), content check of entered
    visuals in their cells, then a VLM pass on keyframes."""
    clip = str(store.blob_path(draft.clip))
    out = [
        f"scene {scene.id}: nothing changes from {a:.1f} s to {b:.1f} s while the narration "
        "goes on; add actions"
        for a, b in static(cues, draft.duration_s)
    ] + [f"{c.what}: no visible change" for c in silent(clip, cues, DRAFT_FPS)]
    if out:
        return out, Usage()
    kf = keyframes(scene, draft, cues, DRAFT_FPS)
    imgs = frames(clip, [n for n, _ in kf])

    def name(i: int | None) -> str:
        if i is None or not 0 <= i < len(scene.visuals):
            return f"scene {scene.id}"
        return f"{scene.id}.{i}:{scene.visuals[i].primitive}"

    regions = [_region(v.args) for v in scene.visuals]
    out = [
        f"{name(i)}: nothing visible in region {regions[i]} at t={n / DRAFT_FPS:.2f} s"
        for (n, live), img in zip(kf, imgs, strict=True)
        for i in live
        if blank(img, regions[i])
    ]
    if out:
        return out, Usage()
    task = {
        "goal": scene.goal,
        "narration": [ln.text for ln in scene.narration],
        "math": list(scene.math),
        "visuals": [
            {
                "index": i,
                "primitive": v.primitive,
                **{k: a for k, a in v.args.items() if k != "code"},
            }
            for i, v in enumerate(scene.visuals)
        ],
        "keyframes": [
            {"image": j, "t": round(n / DRAFT_FPS, 3), "visuals": live}
            for j, (n, live) in enumerate(kf)
        ],
    }
    verdict, usage = llm.parse(
        Verdict, SYSTEM, json.dumps(task, indent=1, sort_keys=True), images=[png(i) for i in imgs]
    )
    return [f"{name(x.visual)}: {x.problem}" for x in verdict.issues], usage
