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
from animath.scene.primitives.tex import Derive, DeriveArgs
from animath.scene.render import DRAFT_FPS, EXIT_S, FRAME_HEIGHT

KEYFRAMES = 6
ENTRY_S = 1.0
BLANK = 16
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
    scene: Scene, times: dict[str, float], duration: float, fps: int, k: int = KEYFRAMES
) -> list[tuple[int, list[int]]]:
    """Last still frame (no entry, derivation step or exit playing) between consecutive changes
    of the visual set or derivation steps, with the visuals alive; at most k."""
    sp = spans(scene, times, duration)
    steps = [
        t
        for v, (t0, t1) in zip(scene.visuals, sp, strict=True)
        if v.primitive == Derive.name
        for t in Derive.times(len(DeriveArgs.model_validate(v.args).steps), t0, t1)[1:]
    ]
    moving = [(t, t + ENTRY_S) for t in [*steps, *(t0 for t0, _ in sp)]] + [
        (max(t0, t1 - EXIT_S), t1)
        for v, (t0, t1) in zip(scene.visuals, sp, strict=True)
        if isinstance(v.args.get("until"), str)
    ]
    still = np.ones(round(duration * fps), dtype=bool)
    for u, w in moving:
        still[round(u * fps) : round(w * fps)] = False
    cuts = sorted({0, len(still), *(round(t * fps) for t in [*steps, *(t for s in sp for t in s)])})
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


def critique(scene: Scene, draft: SceneRender, store: Store, llm: LLM) -> tuple[list[str], Usage]:
    """Content check of entered visuals in their cells, then a VLM pass on keyframes."""
    kf = keyframes(scene, draft.bookmarks, draft.duration_s, DRAFT_FPS)
    imgs = frames(str(store.blob_path(draft.clip)), [n for n, _ in kf])

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
