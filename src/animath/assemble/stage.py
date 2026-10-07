import math
import tempfile
import time
from collections.abc import Sequence
from fractions import Fraction
from itertools import pairwise
from pathlib import Path

from animath.assemble import ffmpeg, vtt
from animath.core.errors import AssembleError
from animath.core.schemas import Manifest, Narration, SceneRender, Storyboard
from animath.core.store import Store

VERSION = "0.1"
TOL_S = 0.1


def timeline(durations: Sequence[float], fps: Fraction) -> tuple[list[int], list[int]]:
    """Frames n_i and audio samples S_i per segment, Eq. (11.1)."""
    frames = [math.ceil(fps * Fraction(d) - Fraction(1, 10**6)) for d in durations]
    ends = [0, *(round(ffmpeg.RATE * sum(frames[: i + 1]) / fps) for i in range(len(frames)))]
    return frames, [b - a for a, b in pairwise(ends)]


def _by_scene[A: SceneRender | Narration](
    store: Store, cls: type[A], digests: Sequence[str]
) -> dict[str, tuple[str, A]]:
    out: dict[str, tuple[str, A]] = {}
    for d in digests:
        a = store.get(cls, d)
        if a.scene_id in out:
            raise AssembleError(f"two {cls.kind} artifacts for scene {a.scene_id}")
        out[a.scene_id] = (d, a)
    return out


def _check(path: Path, claimed: float, actual: float, what: str) -> None:
    if abs(actual - claimed) > TOL_S:
        raise AssembleError(f"{what} {path.name}: {actual:.3f} s, artifact claims {claimed:.3f} s")


def assemble(
    store: Store,
    board: str,
    renders: Sequence[str],
    narrations: Sequence[str],
    threads: int = 1,
) -> str:
    """Phi_7: renders and narrations of a storyboard -> Manifest digest (cached by input key)."""
    t0 = time.perf_counter()
    ids = [s.id for s in store.get(Storyboard, board).scenes]
    rs = _by_scene(store, SceneRender, renders)
    ns = _by_scene(store, Narration, narrations)
    for kind, got in (("renders", rs), ("narrations", ns)):
        if set(got) != set(ids):
            raise AssembleError(f"{kind} cover {sorted(got)}, storyboard has {sorted(ids)}")
    key = Store.key(
        "assemble", VERSION, str(threads), board, *(rs[i][0] for i in ids), *(ns[i][0] for i in ids)
    )
    if (hit := store.ref(Manifest.kind, key)) is not None:
        return hit

    clips = [store.blob_path(rs[i][1].clip) for i in ids]
    audios = [store.blob_path(ns[i][1].audio) for i in ids]
    vs = [ffmpeg.probe(p, "v") for p in clips]
    shape = {(v.width, v.height, v.fps) for v in vs}
    if len(shape) > 1:
        raise AssembleError(f"clips differ in width, height or rate: {sorted(shape)}")
    fps = vs[0].fps
    for i, p, q, v in zip(ids, clips, audios, vs, strict=True):
        _check(p, rs[i][1].duration_s, v.duration_s, f"clip of {i}")
        _check(q, ns[i][1].duration_s, ffmpeg.probe(q, "a").duration_s, f"audio of {i}")
    frames, samples = timeline([max(rs[i][1].duration_s, ns[i][1].duration_s) for i in ids], fps)
    starts = [float(sum(frames[:k]) / fps) for k in range(len(ids))]
    total = float(sum(frames) / fps)

    subs = vtt.webvtt(
        c for i, t in zip(ids, starts, strict=True) for c in vtt.cues(ns[i][1].words, t)
    )
    measured = ffmpeg.loudness(audios, samples)
    with tempfile.TemporaryDirectory(prefix="animath-assemble-") as tmp:
        out = Path(tmp) / "video.mp4"
        ffmpeg.encode(clips, audios, frames, samples, fps, measured, threads, out)
        v, a = ffmpeg.probe(out, "v"), ffmpeg.probe(out, "a")
        if (v.codec, a.codec, a.rate) != ("h264", "aac", ffmpeg.RATE) or abs(
            v.duration_s - total
        ) > TOL_S:
            raise AssembleError(f"output {v}, {a} does not match timeline of {total:.3f} s")
        video = store.put_blob(out.read_bytes())

    manifest = Manifest(
        video=video,
        subtitles=store.put_blob(subs.encode()),
        artifacts={
            "storyboard": board,
            **{f"render/{i}": rs[i][0] for i in ids},
            **{f"narration/{i}": ns[i][0] for i in ids},
        },
        versions={"assemble": VERSION, "ffmpeg": ffmpeg.version()},
        timings_s={"assemble": time.perf_counter() - t0},
        metrics={
            "duration_s": total,
            "loudness_in_lufs": measured["input_i"],
            "true_peak_in_dbtp": measured["input_tp"],
        },
    )
    return store.put(manifest, key)
