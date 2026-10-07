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
from animath.narrate.tts import Espeak, Kokoro, from_wav, spread, to_wav, with_output
from tests.narrate.conftest import Script, tone

WAV = """
import io, wave
text, buf = sys.stdin.read(), io.BytesIO()
open(sys.argv[0] + ".in", "w").write(text)
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
    assert pcm.size == len("L U and ([[S'Ur]]).")
    assert spans == spread(["LU", "and", "(Schur)."], pcm.size)
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
MODEL = (
    v(1, 8)
    + f(8, v(2, 13))
    + f(
        7,
        f(1, s(1, "x"), s(2, "t"), s(4, "Neg")),
        f(1, s(1, "t"), s(2, "y"), s(4, "Neg")),
        s(2, "g"),
        f(11, s(1, "x"), FLOAT3),
        f(12, s(1, "y"), FLOAT3),
    )
    + s(2, "after")
)


@pytest.mark.parametrize(
    ("n", "enc"),
    [(0, b"\x00"), (127, b"\x7f"), (300, b"\xac\x02"), (2**35, b"\x80\x80\x80\x80\x80\x01")],
)
def test_varint_encoding_and_decoding(n: int, enc: bytes) -> None:
    assert tts._uvarint(n) == enc
    assert tts._read(enc + b"\xff", 0) == (n, len(enc))


def test_with_output_exposes_intermediate_tensor() -> None:
    x = np.array([1.0, -2.0, 3.5], dtype=np.float32)
    plain = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    assert [o.name for o in plain.get_outputs()] == ["y"]
    spliced = with_output(MODEL, "t")
    assert spliced.endswith(s(2, "after"))
    sess = ort.InferenceSession(spliced, providers=["CPUExecutionProvider"])
    assert [o.name for o in sess.get_outputs()] == ["y", "t"]
    y, t = sess.run(None, {"x": x})
    assert np.array_equal(y, x)
    assert np.array_equal(t, -x)


@pytest.mark.parametrize(
    ("model", "match"),
    [
        (b"\x08", "truncated"),
        (v(1, 8) + s(2, "p"), "no graph"),
        (b"\x0d\x00\x00\x00\x00", "wire type 5"),
    ],
)
def test_with_output_rejects_malformed(model: bytes, match: str) -> None:
    with pytest.raises(NarrateError, match=match):
        with_output(model, "t")


VOCAB = {";": 1, ",": 3, ".": 4, "(": 12, ")": 13, "—": 9, " ": 16}
VOCAB |= {c: 40 + i for i, c in enumerate("abcdfghijklmn")}


class FakeSession:
    """Token k of the padded sequence lasts k + 1 frames; audio is constant 0.5."""

    def __init__(self, model: bytes, opts: Any, providers: list[str]) -> None:
        self.model, self.opts, self.providers = model, opts, providers
        self.feeds: list[dict[str, np.ndarray]] = []

    def run(self, out: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        dur = np.arange(1, feed["tokens"].shape[1] + 1, dtype=np.float32)[None]
        return [np.full(Kokoro.hop * int(dur.sum()), 0.5, np.float32), dur]


@pytest.fixture
def kokoro_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = SimpleNamespace(InferenceSession=FakeSession, SessionOptions=SimpleNamespace)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    root = tmp_path / "kokoro"
    root.mkdir()
    (root / Kokoro.model).write_bytes(MODEL)
    (root / "config.json").write_text(json.dumps({"vocab": VOCAB}))
    styles = np.arange(16 * 256, dtype="<f4").reshape(16, 1, 256)
    with (root / Kokoro.voices).open("wb") as fh:
        np.savez(fh, af_x=styles, bf_y=-styles)
    return root


@pytest.fixture
def echo(script: Script) -> str:
    return script("print(sys.stdin.read())")


def test_kokoro_feeds_and_word_spans(kokoro_dir: Path, echo: str) -> None:
    k = Kokoro(kokoro_dir, voice="af_x", speed=1.25, threads=2, espeak=echo)
    model = hashlib.sha256(MODEL).hexdigest()[:16]
    assert k.id.startswith(f"kokoro:{model}:af_x:1.25:")
    sess = k.session
    assert sess.model == with_output(MODEL, Kokoro.durations)
    assert sess.opts.intra_op_num_threads == 2
    assert k.g2p.cmd[-1] == "en-us"
    pcm, spans = k.synth("ab cd, (fg).")
    (feed,) = sess.feeds
    ids = [VOCAB[c] for c in "ab cd, (fg)."]
    assert feed["tokens"].tolist() == [[0, *ids, 0]]
    assert np.array_equal(feed["style"], np.arange(11 * 256, 12 * 256, dtype="<f4")[None])
    assert feed["speed"].tolist() == [1.25]
    cum = np.concatenate([[0], np.cumsum(np.arange(1, 15))]) * Kokoro.hop
    assert spans == [(cum[1], cum[3]), (cum[4], cum[6]), (cum[9], cum[11])]
    assert pcm.size == cum[-1]
    assert set(pcm.tolist()) == {8192}


def test_kokoro_splits_long_text_at_clause_ends(kokoro_dir: Path, echo: str) -> None:
    k = Kokoro(kokoro_dir, voice="bf_y", espeak=echo)
    assert k.g2p.cmd[-1] == "en-gb"
    k.max_tokens = 7
    pcm, spans = k.synth("ab cd, fg hi.")
    first, second = (f["tokens"].shape[1] for f in k.session.feeds)
    assert (first, second) == (8, 8)
    n1 = Kokoro.hop * first * (first + 1) // 2
    assert pcm.size == n1 + Kokoro.hop * second * (second + 1) // 2
    assert spans[2] == (n1 + Kokoro.hop * 1, n1 + Kokoro.hop * 6)
    assert np.array_equal(k.session.feeds[1]["style"], -np.arange(5 * 256, 6 * 256)[None])


def test_kokoro_rejects_unspeakable_and_overlong(kokoro_dir: Path, echo: str) -> None:
    k = Kokoro(kokoro_dir, voice="af_x", espeak=echo)
    with pytest.raises(NarrateError, match="nothing to pronounce"):
        k.synth("—")
    k.max_tokens = 3
    with pytest.raises(NarrateError, match="7 tokens exceed 3"):
        k.synth("abcdfgh")


@pytest.mark.parametrize("missing", ["config.json", Kokoro.voices, Kokoro.model, "voice"])
def test_kokoro_invalid_directory(kokoro_dir: Path, missing: str) -> None:
    if missing != "voice":
        (kokoro_dir / missing).unlink()
    with pytest.raises(NarrateError, match="invalid Kokoro model directory"):
        Kokoro(kokoro_dir, voice="af_x" if missing != "voice" else "zz_none")


KOKORO = Path(os.environ.get("ANIMATH_KOKORO", "/nonexistent"))


@pytest.mark.skipif(not (KOKORO / Kokoro.model).is_file(), reason="ANIMATH_KOKORO model directory")
def test_kokoro_real_rate_and_spans() -> None:
    k = Kokoro(KOKORO, threads=4)
    text = "Krylov subspace methods minimise the residual over a growing space."
    pcm, spans = k.synth(text)
    assert len(spans) == len(text.split())
    assert all(a < b for a, b in spans)
    assert all(b <= c for (_, b), (c, _) in pairwise(spans))
    assert spans[0][0] > 0
    assert spans[-1][1] < pcm.size
    wpm = 60 * len(spans) * k.rate / (spans[-1][1] - spans[0][0])
    assert 110 < wpm < 190
    assert 0.1 < np.abs(pcm).max() / 32767 < 0.9
