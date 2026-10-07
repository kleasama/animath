import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from animath.assemble import ffmpeg, timeline
from animath.assemble import stage as st
from animath.core.errors import AssembleError
from animath.core.schemas import Manifest, Narration, SceneRender
from animath.core.store import Store
from tests.assemble.conftest import Media

Two = tuple[str, list[str], list[str]]


@pytest.mark.parametrize(
    ("durations", "fps", "frames", "samples"),
    [
        ([1.0, 0.9], Fraction(15), [15, 14], [48000, 44800]),
        ([0.5, 0.5, 0.5], Fraction(60), [30, 30, 30], [24000] * 3),
        ([1 / 7, 2 / 7, 1.0], Fraction(7), [1, 2, 7], [6857, 13714, 48000]),
        ([2.0001], Fraction(30), [61], [97600]),
    ],
)
def test_timeline_exact_cumulative(
    durations: list[float], fps: Fraction, frames: list[int], samples: list[int]
) -> None:
    n, s = timeline(durations, fps)
    assert (n, s) == (frames, samples)
    assert sum(s) == round(ffmpeg.RATE * sum(n) / fps)


def _frames(path: Path) -> int:
    out = subprocess.run(
        [
            *("ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0"),
            *("-show_entries", "stream=nb_read_frames", "-of", "json", str(path)),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def test_assemble_end_to_end(store: Store, two: Two) -> None:
    board, renders, narrations = two
    d = st.assemble(store, board, renders[::-1], narrations)
    m = store.get(Manifest, d)
    video = store.blob_path(m.video)
    v, a = ffmpeg.probe(video, "v"), ffmpeg.probe(video, "a")
    assert (v.codec, v.width, v.height, v.fps) == ("h264", 64, 36, Fraction(15))
    assert (a.codec, a.rate, a.channels) == ("aac", 48000, 1)
    assert _frames(video) == 29
    assert m.metrics["duration_s"] == pytest.approx(29 / 15)
    assert abs(v.duration_s - 29 / 15) < 0.05
    assert store.get_blob(m.subtitles).decode() == (
        "WEBVTT\n\n00:00:00.100 --> 00:00:00.600\nOne.\n\n"
        "00:00:01.000 --> 00:00:01.800\nTwo x&lt;y.\n\n"
    )
    assert m.artifacts == {
        "storyboard": board,
        "render/s1": renders[0],
        "render/s2": renders[1],
        "narration/s1": narrations[0],
        "narration/s2": narrations[1],
    }
    assert m.versions["assemble"] == st.VERSION
    assert m.versions["ffmpeg"].startswith("ffmpeg version")
    out = ffmpeg.loudness([video], [round(48000 * 29 / 15)])
    assert out["input_i"] == pytest.approx(-16.0, abs=1.0)
    assert out["input_tp"] <= -1.0


def test_peaky_narration_meets_loudness_and_true_peak(store: Store, two: Two, media: Media) -> None:
    board, renders, narrations = two
    clicks = [
        _redo(store, d, Narration, audio=media("peaky", 0.8 + k / 10))
        for k, d in enumerate(narrations)
    ]
    m = store.get(Manifest, st.assemble(store, board, renders, clicks))
    assert m.metrics["true_peak_in_dbtp"] - m.metrics["loudness_in_lufs"] > 14.5
    assert m.metrics["loudness_out_lufs"] == pytest.approx(ffmpeg.LUFS, abs=1.0)
    assert m.metrics["true_peak_out_dbtp"] <= -1.5


def test_cached_and_deterministic(store: Store, two: Two, monkeypatch: pytest.MonkeyPatch) -> None:
    board, renders, narrations = two
    d = st.assemble(store, board, renders, narrations)
    shutil.rmtree(store.root / "index" / Manifest.kind)
    d2 = st.assemble(store, board, renders, narrations)
    assert store.get(Manifest, d).video == store.get(Manifest, d2).video

    def boom(*_: object) -> None:
        raise AssertionError("ffmpeg called on cache hit")

    monkeypatch.setattr(ffmpeg, "run", boom)
    assert st.assemble(store, board, renders, narrations) == d2


def _redo(store: Store, d: str, cls: type[SceneRender] | type[Narration], **kw: object) -> str:
    return store.put(cls.model_validate(store.get(cls, d).model_dump() | kw))


def test_rejects_scene_cover_and_duplicates(store: Store, two: Two) -> None:
    board, renders, narrations = two
    with pytest.raises(AssembleError, match=r"renders cover \['s1'\]"):
        st.assemble(store, board, renders[:1], narrations)
    dup = _redo(store, narrations[1], Narration, scene_id="s1", duration_s=0.85)
    with pytest.raises(AssembleError, match="two narration artifacts for scene s1"):
        st.assemble(store, board, renders, [narrations[0], dup])


@pytest.mark.parametrize(
    ("which", "kw", "match"),
    [
        ("render", {"duration_s": 1.5}, r"clip of s1 .*: 1\.0\d\d s, artifact claims 1\.500 s"),
        ("narration", {"duration_s": 0.65}, r"audio of s1 .*: 0\.800 s, artifact claims 0\.650 s"),
        ("render", {"clip": ("v", 1.0, "32x18")}, "clips differ in width, height or rate"),
        ("render", {"clip": ("v", 1.0, "64x36", 30)}, "clips differ in width, height or rate"),
        ("render", {"clip": ("a", 1.0)}, "no v stream"),
    ],
)
def test_rejects_inconsistent_media(
    store: Store, two: Two, media: Media, which: str, kw: dict[str, object], match: str
) -> None:
    board, renders, narrations = two
    kw = {k: media(*v) if isinstance(v, tuple) else v for k, v in kw.items()}
    if which == "render":
        renders = [_redo(store, renders[0], SceneRender, **kw), renders[1]]
    else:
        narrations = [_redo(store, narrations[0], Narration, **kw), narrations[1]]
    with pytest.raises(AssembleError, match=match):
        st.assemble(store, board, renders, narrations)


def test_rejects_silent_narration(store: Store, two: Two, media: Media) -> None:
    board, renders, narrations = two
    mute = [
        _redo(store, d, Narration, audio=media("silent", 0.8 + k / 10))
        for k, d in enumerate(narrations)
    ]
    with pytest.raises(AssembleError, match="narration is silent"):
        st.assemble(store, board, renders, mute)


def test_ffmpeg_failures(store: Store, two: Two, monkeypatch: pytest.MonkeyPatch) -> None:
    board, renders, narrations = two
    junk = [_redo(store, renders[0], SceneRender, clip=store.put_blob(b"junk")), renders[1]]
    with pytest.raises(AssembleError, match="ffprobe exit 1"):
        st.assemble(store, board, junk, narrations)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(AssembleError, match="ffprobe not found on PATH"):
        st.assemble(store, board, renders, narrations)


def test_rejects_output_off_timeline(
    store: Store, two: Two, monkeypatch: pytest.MonkeyPatch
) -> None:
    board, renders, narrations = two
    encode = ffmpeg.encode

    def short(*args: object) -> None:
        encode(*args)  # type: ignore[arg-type]
        out = Path(str(args[-1]))
        cut = out.with_name("cut.mp4")
        ffmpeg.run(["ffmpeg", "-v", "error", "-i", str(out), "-t", "1", "-c", "copy", str(cut)])
        cut.replace(out)

    monkeypatch.setattr(ffmpeg, "encode", short)
    with pytest.raises(AssembleError, match=r"does not match timeline of 1\.933 s"):
        st.assemble(store, board, renders, narrations)
    assert not (store.root / "index" / Manifest.kind).exists()
