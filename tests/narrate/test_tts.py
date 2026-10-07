import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from animath.core.errors import NarrateError
from animath.narrate.tts import Espeak, Kokoro, from_wav, to_wav
from tests.narrate.conftest import Script, tone

WAV = """
import io, wave
text, buf = sys.stdin.read(), io.BytesIO()
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


def test_espeak_subprocess_contract(script: Script) -> None:
    e = Espeak("en-gb", 140, cmd=script(WAV.format(ch=1, rate=22050)))
    assert e.id == "espeak-ng:en-gb:140"
    assert e.synth("abc").size == 3
    bad = Espeak(cmd=script(WAV.format(ch=2, rate=22050)))
    with pytest.raises(NarrateError, match="mono"):
        bad.synth("abc")


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng")
def test_espeak_real_scales_with_text() -> None:
    e = Espeak()
    short, long = e.synth("Krylov."), e.synth("Krylov subspace methods minimise the residual.")
    assert short.dtype == np.int16
    assert 0.2 * e.rate < short.size < long.size
    assert np.abs(long).max() > 1000


IPA = "print('  '.join(['ab', 'c?d', 'xyz'][: len(sys.stdin.read().split())]))"
VOCAB = {" ": 16, "a": 1, "b": 2, "c": 3, "d": 4}


class FakeSession:
    def __init__(self, path: str, opts: Any, providers: list[str]) -> None:
        self.path, self.opts, self.providers = path, opts, providers
        self.feeds: list[dict[str, np.ndarray]] = []

    def get_inputs(self) -> list[Any]:
        return [type("I", (), {"name": "input_ids"})()]

    def run(self, out: None, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.feeds.append(feed)
        return [np.array([[0.5, -2.0, 2.0]], dtype=np.float32)]


@pytest.fixture
def kokoro_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ort = SimpleNamespace(InferenceSession=FakeSession, SessionOptions=SimpleNamespace)
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    root = tmp_path / "kokoro"
    (root / "voices").mkdir(parents=True)
    (root / "model.onnx").write_bytes(b"onnx")
    (root / "config.json").write_text(json.dumps({"vocab": VOCAB}))
    np.arange(8 * 256, dtype="<f4").tofile(root / "voices" / "v.bin")
    return root


def test_kokoro_feeds_padded_ids_style_speed(kokoro_dir: Path, script: Script) -> None:
    k = Kokoro(kokoro_dir, voice="v", speed=1.25, threads=2, espeak=script(IPA))
    assert k.id.startswith("kokoro:")
    assert k.id.endswith(":v:1.25")
    s = k.session
    assert s.providers == ["CPUExecutionProvider"]
    assert s.opts.intra_op_num_threads == 2
    pcm = k.synth("two words")
    assert pcm.tolist() == [16384, -32767, 32767]
    (feed,) = s.feeds
    assert feed["input_ids"].tolist() == [[0, 1, 2, 16, 3, 4, 0]]
    assert np.array_equal(feed["style"], np.arange(4 * 256, 5 * 256, dtype="<f4")[None])
    assert feed["speed"].tolist() == [1.25]


def test_kokoro_chunks_at_word_boundaries(kokoro_dir: Path, script: Script) -> None:
    k = Kokoro(kokoro_dir, voice="v", espeak=script(IPA))
    k.max_tokens = 3
    assert k.tokens("one two three") == [[1, 2], [3, 4]]
    assert k.synth("one two").size == 6


def test_kokoro_rejects_unpronounceable(kokoro_dir: Path, script: Script) -> None:
    k = Kokoro(kokoro_dir, voice="v", espeak=script("print('?!')"))
    with pytest.raises(NarrateError, match="nothing to pronounce"):
        k.synth("—")


@pytest.mark.parametrize("missing", ["config.json", "voices/v.bin", "model.onnx"])
def test_kokoro_invalid_directory(kokoro_dir: Path, missing: str) -> None:
    (kokoro_dir / missing).unlink()
    with pytest.raises(NarrateError, match="invalid Kokoro"):
        Kokoro(kokoro_dir, voice="v")
