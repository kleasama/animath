import hashlib
import io
import json
import wave
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from animath.core.errors import NarrateError
from animath.narrate.proc import run

PCM = npt.NDArray[np.int16]


class TTS(Protocol):
    """Text to mono 16-bit PCM at `rate` Hz; `id` determines the output for a given text."""

    id: str
    rate: int

    def synth(self, text: str) -> PCM: ...


def to_wav(pcm: PCM, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype("<i2").tobytes())
    return buf.getvalue()


def from_wav(data: bytes, rate: int) -> PCM:
    try:
        with wave.open(io.BytesIO(data)) as w:
            shape = (w.getnchannels(), w.getsampwidth(), w.getframerate())
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        raise NarrateError(f"invalid WAV: {e}") from e
    if shape != (1, 2, rate):
        raise NarrateError(f"expected mono 16-bit {rate} Hz, got {shape}")
    return np.frombuffer(frames[: len(frames) // 2 * 2], dtype="<i2").astype(np.int16)


class Espeak:
    """espeak-ng formant synthesis (subprocess)."""

    rate = 22050

    def __init__(self, voice: str = "en-us", wpm: int = 160, cmd: str = "espeak-ng") -> None:
        self.voice, self.wpm, self.cmd = voice, wpm, cmd
        self.id = f"espeak-ng:{voice}:{wpm}"

    def synth(self, text: str) -> PCM:
        cmd = [self.cmd, "-v", self.voice, "-s", str(self.wpm), "--stdout"]
        return from_wav(run(cmd, text.encode()), self.rate)


class Kokoro:
    """Kokoro-82M ONNX; phonemes from espeak-ng IPA.

    `root` holds `model.onnx`, `config.json` (key `vocab`), `voices/<voice>.bin` (float32, N x 256).
    """

    rate = 24000
    max_tokens = 510

    def __init__(
        self,
        root: Path,
        voice: str = "af_heart",
        speed: float = 1.0,
        threads: int = 1,
        espeak: str = "espeak-ng",
    ) -> None:
        import onnxruntime as ort  # type: ignore[import-untyped]

        self.speed, self.espeak = speed, espeak
        try:
            self.vocab: dict[str, int] = json.loads((root / "config.json").read_text())["vocab"]
            self.style = np.fromfile(root / "voices" / f"{voice}.bin", dtype="<f4").reshape(-1, 256)
            with (root / "model.onnx").open("rb") as f:
                model = hashlib.file_digest(f, "sha256").hexdigest()
        except (OSError, KeyError, ValueError) as e:
            raise NarrateError(f"invalid Kokoro model directory {root}: {e}") from e
        opts = ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = threads, 1
        self.session = ort.InferenceSession(
            str(root / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.ids = self.session.get_inputs()[0].name
        self.id = f"kokoro:{model[:16]}:{voice}:{speed}"

    def tokens(self, text: str) -> list[list[int]]:
        """Vocabulary ids of the IPA transcription, packed by word into chunks of max_tokens."""
        ipa = run([self.espeak, "-q", "--ipa", "-v", "en-us"], text.encode()).decode()
        chunks: list[list[int]] = [[]]
        for word in ipa.split():
            ids = [self.vocab[c] for c in word if c in self.vocab]
            if not ids:
                continue
            sep = [self.vocab[" "]] if chunks[-1] else []
            if len(chunks[-1]) + len(sep) + len(ids) > self.max_tokens:
                chunks.append([])
                sep = []
            chunks[-1] += sep + ids[: self.max_tokens]
        if not chunks[0]:
            raise NarrateError(f"nothing to pronounce in {text!r}")
        return chunks

    def synth(self, text: str) -> PCM:
        out = []
        for tok in self.tokens(text):
            feed = {
                self.ids: np.array([[0, *tok, 0]], dtype=np.int64),
                "style": self.style[len(tok) - 1][None],
                "speed": np.array([self.speed], dtype=np.float32),
            }
            out.append(np.asarray(self.session.run(None, feed)[0], dtype=np.float32).ravel())
        pcm: PCM = np.round(np.clip(np.concatenate(out), -1.0, 1.0) * 32767).astype(np.int16)
        return pcm
