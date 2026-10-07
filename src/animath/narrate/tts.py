import hashlib
import io
import json
import wave
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from animath.core.errors import NarrateError
from animath.core.hashing import digest_of
from animath.narrate import g2p
from animath.narrate.proc import run

PCM = npt.NDArray[np.int16]
Spans = list[tuple[int, int]]


class TTS(Protocol):
    """Text to mono 16-bit PCM at `rate` Hz with the sample span of each whitespace-separated word.

    `id` determines the output for a given text.
    """

    id: str
    rate: int

    def synth(self, text: str) -> tuple[PCM, Spans]: ...


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


def spread(words: Sequence[str], n: int) -> Spans:
    """Spans of `words` over n samples in proportion to 1 + their alphanumeric count."""
    cum = np.cumsum([0] + [1 + sum(c.isalnum() for c in w) for w in words])
    at = np.round(n * cum / max(1, cum[-1])).astype(int)
    return [(int(a), int(b)) for a, b in pairwise(at)]


class Espeak:
    """espeak-ng formant synthesis (subprocess); word spans estimated by `spread`."""

    rate = 22050

    def __init__(self, voice: str = "en-us", wpm: int = 140, cmd: str = "espeak-ng") -> None:
        self.voice, self.wpm, self.cmd = voice, wpm, cmd
        self.id = f"espeak-ng:{voice}:{wpm}:{digest_of([g2p.LEXICON, sorted(g2p.WORDS)])[:8]}"

    def synth(self, text: str) -> tuple[PCM, Spans]:
        words = text.split()
        said = [
            p + s + q
            for (p, _, q), s in zip(map(g2p.split, words), g2p.speakable(words), strict=True)
        ]
        cmd = [self.cmd, "-v", self.voice, "-s", str(self.wpm), "--stdout"]
        pcm = from_wav(run(cmd, " ".join(said).encode()), self.rate)
        return pcm, spread(words, pcm.size)


def _uvarint(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append(n & 0x7F | 0x80)
        n >>= 7
    return bytes(out) + bytes([n])


def _field(tag: int, payload: bytes) -> bytes:
    return _uvarint(tag << 3 | 2) + _uvarint(len(payload)) + payload


def _read(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while data[pos] & 0x80:
        value |= (data[pos] & 0x7F) << shift
        pos, shift = pos + 1, shift + 7
    return value | data[pos] << shift, pos + 1


def with_output(model: bytes, name: str) -> bytes:
    """ONNX `model` with tensor `name` appended to the graph outputs.

    Top-level ModelProto fields are varints or length-delimited; field 7 is the GraphProto,
    whose field 12 lists the outputs (ValueInfoProto, field 1 = name).
    """
    pos = 0
    try:
        while pos < len(model):
            start = pos
            key, pos = _read(model, pos)
            if key & 7 not in (0, 2):
                raise NarrateError(f"unexpected wire type {key & 7} in ONNX model")
            n, pos = _read(model, pos)
            if key == 7 << 3 | 2:
                extra, m = _field(12, _field(1, name.encode())), memoryview(model)
                head = _uvarint(key) + _uvarint(n + len(extra))
                return b"".join([m[:start], head, m[pos : pos + n], extra, m[pos + n :]])
            pos += n if key & 7 else 0
    except IndexError as e:
        raise NarrateError("truncated ONNX model") from e
    raise NarrateError("ONNX model has no graph")


class Kokoro:
    """Kokoro-82M v1.0 ONNX, release `model-files-v1.0` of thewh1teagle/kokoro-onnx.

    `root` holds `kokoro-v1.0.onnx`, `voices-v1.0.bin` (npz, voice -> 510 x 1 x 256 float32) and
    `config.json` (key `vocab`). Word spans come from the predicted token durations.
    """

    rate, hop, max_tokens, headroom = 24000, 600, 510, 0.5
    model, voices, durations = "kokoro-v1.0.onnx", "voices-v1.0.bin", "/encoder/Clip_output_0"

    def __init__(
        self,
        root: Path,
        voice: str = "af_heart",
        speed: float = 0.85,
        threads: int = 1,
        espeak: str = "espeak-ng",
    ) -> None:
        import onnxruntime as ort  # type: ignore[import-untyped]

        self.speed = speed
        try:
            self.vocab: dict[str, int] = json.loads((root / "config.json").read_text())["vocab"]
            with np.load(root / self.voices, allow_pickle=False) as v:
                self.style = v[voice].astype("<f4").reshape(-1, 256)
            model = (root / self.model).read_bytes()
            opts = ort.SessionOptions()
            opts.intra_op_num_threads, opts.inter_op_num_threads = threads, 1
            self.session = ort.InferenceSession(
                with_output(model, self.durations), opts, providers=["CPUExecutionProvider"]
            )
        except Exception as e:
            raise NarrateError(f"invalid Kokoro model directory {root}: {e}") from e
        self.g2p = g2p.Phonemizer("en-gb" if voice.startswith("b") else "en-us", espeak)
        style = hashlib.sha256(self.style).hexdigest()
        tables = [g2p.LEXICON, sorted(g2p.WORDS), self.g2p.table, self.vocab, style]
        self.id = ":".join(
            [
                "kokoro",
                hashlib.sha256(model).hexdigest()[:16],
                voice,
                str(speed),
                digest_of(tables)[:8],
            ]
        )

    def size(self, w: g2p.Word) -> int:
        return sum(c in self.vocab for c in "".join(w)) + 1

    def pieces(self, words: Sequence[g2p.Word], lo: int, hi: int) -> list[tuple[int, int]]:
        """Word ranges of at most max_tokens tokens, split at the clause end nearest the middle."""
        sizes = [self.size(w) for w in words[lo:hi]]
        if sum(sizes) <= self.max_tokens + 1 or hi - lo == 1:
            return [(lo, hi)]
        cum = np.cumsum(sizes)
        ends = [lo + i + 1 for i in range(hi - lo - 1) if words[lo + i][2]] or list(
            range(lo + 1, hi)
        )
        mid = min(ends, key=lambda j: abs(2 * cum[j - lo - 1] - cum[-1]))
        return self.pieces(words, lo, mid) + self.pieces(words, mid, hi)

    def tokens(self, words: Sequence[g2p.Word]) -> tuple[list[int], Spans]:
        """Vocabulary ids and the [start, end) token range of each word's phonemes."""
        out: list[int] = []
        ranges = []
        for pre, ipa, post in words:
            out += [self.vocab[c] for c in pre if c in self.vocab]
            ids = [self.vocab[c] for c in ipa if c in self.vocab]
            ranges.append((len(out), len(out) + len(ids)))
            out += ids + [self.vocab[c] for c in post if c in self.vocab] + [self.vocab[" "]]
        return out[:-1], ranges

    def synth(self, text: str) -> tuple[PCM, Spans]:
        words = self.g2p.words(text)
        audio: list[npt.NDArray[np.float32]] = []
        spans: Spans = []
        at = 0
        for lo, hi in self.pieces(words, 0, len(words)):
            tok, ranges = self.tokens(words[lo:hi])
            if not any(b > a for a, b in ranges):
                raise NarrateError(f"nothing to pronounce in {text!r}")
            if len(tok) > self.max_tokens:
                raise NarrateError(f"{len(tok)} tokens exceed {self.max_tokens} in {text!r}")
            feed = {
                "tokens": np.array([[0, *tok, 0]], dtype=np.int64),
                "style": self.style[len(tok) - 1][None],
                "speed": np.array([self.speed], dtype=np.float32),
            }
            wave_, dur = self.session.run(None, feed)
            frames = self.hop * np.concatenate([[0], np.cumsum(np.ravel(dur))]).astype(int)
            spans += [(at + int(frames[a + 1]), at + int(frames[b + 1])) for a, b in ranges]
            audio.append(np.ravel(wave_).astype(np.float32))
            at += audio[-1].size
        x = np.concatenate(audio) * self.headroom
        pcm: PCM = np.round(np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
        return pcm, spans
