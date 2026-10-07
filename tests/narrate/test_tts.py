import hashlib
import json
import os
import shutil
import sys
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
import pytest

from animath.core.errors import NarrateError
from animath.narrate import tts
from animath.narrate.tts import Espeak, Kokoro, fit, from_wav, spread, to_wav, with_outputs
from tests.narrate.conftest import Script, tone

WAV = """
import io, wave
text, buf = sys.stdin.read(), io.BytesIO()
open(sys.argv[0] + ".in", "w").write(text)
open(sys.argv[0] + ".args", "w").write(" ".join(sys.argv[1:]))
with wave.open(buf, "wb") as w:
    w.setnchannels({ch}); w.setsampwidth(2); w.setframerate({rate})
    w.writeframes(bytes(range(2 * len(text))))
sys.stdout.buffer.write(buf.getvalue())
"""


def test_wav_round_trip() -> None:
    x = tone(500, lead=10)
    assert np.array_equal(from_wav(to_wav(x, 16000), 16000), x)


def test_from_wav_rejects_format_and_garbage() -> None:
    with pytest.raises(NarrateError, match="16000 Hz"):
        from_wav(to_wav(tone(10), 8000), 16000)
    with pytest.raises(NarrateError, match="invalid WAV"):
        from_wav(b"RIFF....", 16000)


def test_spread_by_alphanumeric_weight() -> None:
    assert spread(["ab", "cdefg,"], 100) == [(0, 33), (33, 100)]
    assert spread([], 10) == []


def test_espeak_speaks_pronunciations(script: Script) -> None:
    cmd = script(WAV.format(ch=1, rate=22050))
    e = Espeak("en-gb", 150, cmd=cmd)
    assert e.id.startswith("espeak-ng:en-gb:150:")
    pcm, spans = e.synth("LU and (Schur).")
    assert Path(cmd + ".in").read_text() == "L U and ([[S'Ur]])."
    assert Path(cmd + ".args").read_text() == "-v en-gb -s 150 --stdout"
    assert pcm.size == len("L U and ([[S'Ur]]).")
    assert spans == spread(["LU", "and", "(Schur)."], pcm.size)
    assert e.natural("LU and (Schur).") == 60 * 3 / 150
    e.synth("LU.", 1.2)
    assert Path(cmd + ".args").read_text() == "-v en-gb -s 180 --stdout"
    with pytest.raises(NarrateError, match="mono"):
        Espeak(cmd=script(WAV.format(ch=2, rate=22050))).synth("abc")


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng")
def test_espeak_real_scales_with_text() -> None:
    e = Espeak()
    (short, _), (long, spans) = e.synth("Krylov."), e.synth("Krylov methods minimise residuals.")
    assert short.dtype == np.int16
    assert 0.2 * e.rate < short.size < long.size
    assert np.abs(long).max() > 1000
    assert spans[-1][1] == long.size


def f(tag: int, *parts: bytes) -> bytes:
    return tts._field(tag, b"".join(parts))


def s(tag: int, text: str) -> bytes:
    return f(tag, text.encode())


def v(tag: int, n: int) -> bytes:
    return tts._uvarint(tag << 3) + tts._uvarint(n)


FLOAT3 = f(2, f(1, v(1, 1), f(2, f(1, v(1, 3)))))
W = np.array([0.5, 1.5, 2.5], dtype="<f4")


def graph(*nodes: tuple[str, str, str], out: str) -> bytes:
    """Model of `nodes` (inputs, output, op) over input x and initializer w, with output `out`."""
    return (
        v(1, 8)
        + f(8, v(2, 13))
        + f(
            7,
            *(f(1, *(s(1, i) for i in ins.split()), s(2, o), s(4, op)) for ins, o, op in nodes),
            s(2, "g"),
            f(5, v(1, 3), v(2, 1), s(8, "w"), f(9, W.tobytes())),
            f(11, s(1, "x"), FLOAT3),
            f(12, s(1, out), FLOAT3),
        )
        + s(2, "after")
    )


MODEL = graph(("x", "t", "Neg"), ("t w", "y", "Add"), out="y")


def run(model: bytes) -> Any:
    return ort.InferenceSession(model, providers=["CPUExecutionProvider"])


def test_with_outputs_appends_or_prunes() -> None:
    x = np.array([1.0, -2.0, 3.5], dtype=np.float32)
    assert [o.name for o in run(MODEL).get_outputs()] == ["y"]
    spliced = with_outputs(MODEL, ["t"])
    assert spliced.endswith(s(2, "after"))
    sess = run(spliced)
    assert [o.name for o in sess.get_outputs()] == ["y", "t"]
    y, t = sess.run(None, {"x": x})
    assert np.array_equal(y, W - x)
    assert np.array_equal(t, -x)
    pruned = with_outputs(MODEL, ["t"], prune=True)
    assert b"Add" not in pruned
    assert W.tobytes() not in pruned
    assert pruned.endswith(s(2, "after"))
    (t,) = run(pruned).run(None, {"x": x})
    assert np.array_equal(t, -x)
    whole = with_outputs(MODEL, ["y"], prune=True)
    assert all(part in whole for part in (b"Neg", b"Add", W.tobytes()))
    (y,) = run(whole).run(None, {"x": x})
    assert np.array_equal(y, W - x)


@pytest.mark.parametrize(
    ("model", "names", "match"),
    [
        (b"\x08", ["t"], "truncated"),
        (v(1, 8) + s(2, "pq")[:-1], ["t"], "truncated"),
        (v(1, 8) + s(2, "p"), ["t"], "no graph"),
        (b"\x0d\x00\x00\x00\x00", ["t"], "wire type 5"),
        (MODEL, ["t", "z"], r"computes \['z'\]"),
    ],
)
def test_with_outputs_rejects_malformed_and_unknown(
    model: bytes, names: list[str], match: str
) -> None:
    with pytest.raises(NarrateError, match=match):
        with_outputs(model, names)


def test_fit_cancels_the_rounding_of_clustered_durations() -> None:
    rng = np.random.default_rng(7)
    d = np.concatenate(
        [rng.normal(2.0, 0.01, 80), rng.uniform(1.0, 3.0, 80), rng.uniform(3.0, 12.0, 40)]
    ).astype(np.float32)

    def frames(s: float) -> float:
        return float(np.maximum(1, np.round(d / np.float32(s))).sum())

    speeds = np.arange(0.7, 1.0, 0.005)
    naive = max(abs(frames(s) * s / d.sum() - 1) for s in speeds)
    fitted = max(abs(frames(fit(d, s)) * s / d.sum() - 1) for s in speeds)
    assert naive > 0.04
    assert fitted < 0.01
    assert fit(np.full(3, 2.0, np.float32), 1.0) == 1.0


VOCAB = {";": 1, ",": 3, ".": 4, "(": 12, ")": 13, "—": 9, " ": 16}
VOCAB |= {c: 40 + i for i, c in enumerate("abcdfghijklmn")}


KMODEL = graph(
    ("x", Kokoro.predicted, "Neg"),
    (Kokoro.predicted, Kokoro.durations, "Neg"),
    (f"{Kokoro.durations} w", "y", "Add"),
    out="y",
)


def unrounded(n: int) -> np.ndarray:
    """Fake frames of the n padded tokens at speed 1, before rounding."""
    return (1.2 + 0.7 * (np.arange(n) % 3)).astype(np.float32)


class FakeSession:
    """The pruned model returns `unrounded`; the full one rounds it at the speed input like Kokoro
    and returns constant audio 0.5."""

    def __init__(self, model: bytes, opts: Any, providers: list[str]) -> None:
        self.model, self.opts, self.providers = model, opts, providers
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, out: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        d = unrounded(feed["tokens"].shape[1])
        if Kokoro.durations.encode() not in self.model:
            return [d[None]]
        dur = np.maximum(1, np.round(d / feed["speed"][0]))
        return [np.full(Kokoro.hop * int(dur.sum()), 0.5, np.float32), dur[None]]


def frames(feed: dict[str, np.ndarray]) -> np.ndarray:
    d = unrounded(feed["tokens"].shape[1])
    cum = np.concatenate([[0], np.cumsum(np.maximum(1, np.round(d / feed["speed"][0])))])
    return cum.astype(int) * Kokoro.hop


@pytest.fixture
def kokoro_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = SimpleNamespace(InferenceSession=FakeSession, SessionOptions=SimpleNamespace)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    root = tmp_path / "kokoro"
    root.mkdir()
    (root / Kokoro.model).write_bytes(KMODEL)
    (root / "config.json").write_text(json.dumps({"vocab": VOCAB}))
    styles = np.arange(16 * 256, dtype="<f4").reshape(16, 1, 256)
    with (root / Kokoro.voices).open("wb") as fh:
        np.savez(fh, af_x=styles, bf_y=-styles)
    return root


@pytest.fixture
def echo(script: Script) -> str:
    return script("print(sys.stdin.read())")


def test_kokoro_scales_unrounded_durations_and_times_words(kokoro_dir: Path, echo: str) -> None:
    k = Kokoro(kokoro_dir, voice="af_x", wpm=150, threads=2, espeak=echo)
    model = hashlib.sha256(KMODEL).hexdigest()[:16]
    assert k.id.startswith(f"kokoro:{model}:af_x:150wpm:")
    assert k.session.model == with_outputs(KMODEL, [Kokoro.durations])
    assert k.predictor.model == with_outputs(KMODEL, [Kokoro.predicted], prune=True)
    assert k.session.opts.intra_op_num_threads == 2
    assert k.g2p.cmd[-1] == "en-us"
    pcm, spans = k.synth("ab cd, (fg).", 0.7)
    (probe,), (feed,) = k.predictor.feeds, k.session.feeds
    ids = [VOCAB[c] for c in "ab cd, (fg)."]
    assert feed["tokens"].tolist() == probe["tokens"].tolist() == [[0, *ids, 0]]
    assert np.array_equal(feed["style"], np.arange(11 * 256, 12 * 256, dtype="<f4")[None])
    d = unrounded(14)
    assert probe["speed"].tolist() == [1.0]
    assert feed["speed"].tolist() == [np.float32(fit(d, 0.7))]
    cum = frames(feed)
    assert d.sum() / 0.7 == pytest.approx(37)
    assert (np.maximum(1, np.round(d / np.float32(0.7))).sum(), cum[-1] / Kokoro.hop) == (41, 37)
    assert spans == [(cum[1], cum[3]), (cum[4], cum[6]), (cum[9], cum[11])]
    assert pcm.size == cum[-1]
    assert set(pcm.tolist()) == {8192}
    assert k.natural("ab cd, (fg).") == pytest.approx(d[1:11].sum() * Kokoro.hop / Kokoro.rate)


def test_kokoro_splits_long_text_at_clause_ends(kokoro_dir: Path, echo: str) -> None:
    k = Kokoro(kokoro_dir, voice="bf_y", espeak=echo)
    assert k.g2p.cmd[-1] == "en-gb"
    k.max_tokens = 7
    pcm, spans = k.synth("ab cd, fg hi.")
    first, second = k.session.feeds
    assert (first["tokens"].shape[1], second["tokens"].shape[1]) == (8, 8)
    n1, c2 = frames(first)[-1], frames(second)
    assert pcm.size == n1 + c2[-1]
    assert spans[2] == (n1 + c2[1], n1 + c2[3])
    assert np.array_equal(second["style"], -np.arange(5 * 256, 6 * 256)[None])
    d = unrounded(8)
    assert k.natural("ab cd, fg hi.") == pytest.approx(
        (2 * d.sum() - d[0] - d[6:].sum()) * Kokoro.hop / Kokoro.rate
    )


def test_kokoro_rejects_unspeakable_and_overlong(kokoro_dir: Path, echo: str) -> None:
    k = Kokoro(kokoro_dir, voice="af_x", espeak=echo)
    for say in (k.synth, k.natural):
        with pytest.raises(NarrateError, match="nothing to pronounce"):
            say("—")
    k.max_tokens = 3
    with pytest.raises(NarrateError, match="7 tokens exceed 3"):
        k.synth("abcdfgh")


@pytest.mark.parametrize("missing", ["config.json", Kokoro.voices, Kokoro.model, "voice", "tensor"])
def test_kokoro_invalid_directory(kokoro_dir: Path, missing: str) -> None:
    if missing == "tensor":
        (kokoro_dir / Kokoro.model).write_bytes(MODEL)
    elif missing != "voice":
        (kokoro_dir / missing).unlink()
    with pytest.raises(NarrateError, match="invalid Kokoro model directory"):
        Kokoro(kokoro_dir, voice="af_x" if missing != "voice" else "zz_none")


KOKORO = Path(os.environ.get("ANIMATH_KOKORO", "/nonexistent"))


@pytest.mark.skipif(not (KOKORO / Kokoro.model).is_file(), reason="ANIMATH_KOKORO model directory")
def test_kokoro_real_rate_and_spans() -> None:
    k = Kokoro(KOKORO, threads=4)
    text = "Krylov subspace methods minimise the residual over a growing space."
    pcm, spans = k.synth(text, k.natural(text) * k.wpm / (60 * len(text.split())))
    assert len(spans) == len(text.split())
    assert all(a < b for a, b in spans)
    assert all(b <= c for (_, b), (c, _) in pairwise(spans))
    assert spans[0][0] > 0
    assert spans[-1][1] < pcm.size
    assert 60 * len(spans) * k.rate / (spans[-1][1] - spans[0][0]) == pytest.approx(135, rel=0.01)
    assert 0.1 < np.abs(pcm).max() / 32767 < 0.9
