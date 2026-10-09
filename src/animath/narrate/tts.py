import hashlib
import io
import json
import wave
from collections.abc import Iterator, Sequence
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
    """Text to mono int16 PCM at `rate` Hz with per-word sample spans; `natural` is the length in
    seconds at speed 1, `wpm` the target rate, `id` determines the output."""

    id: str
    rate: int
    wpm: int

    def natural(self, text: str) -> float: ...

    def synth(self, text: str, speed: float = 1.0) -> tuple[PCM, Spans]: ...


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

    def __init__(self, voice: str = "en-us", wpm: int = 135, cmd: str = "espeak-ng") -> None:
        self.voice, self.wpm, self.cmd = voice, wpm, cmd
        self.id = f"espeak-ng:{voice}:{wpm}:{digest_of([g2p.LEXICON, sorted(g2p.WORDS)])[:8]}"

    def natural(self, text: str) -> float:
        """Nominal length at `wpm`: espeak-ng's `-s` already counts words."""
        return 60 * len(text.split()) / self.wpm

    def synth(self, text: str, speed: float = 1.0) -> tuple[PCM, Spans]:
        words = text.split()
        said = [
            p + s + q
            for (p, _, q), s in zip(map(g2p.split, words), g2p.speakable(words), strict=True)
        ]
        cmd = [self.cmd, "-v", self.voice, "-s", str(round(self.wpm * speed)), "--stdout"]
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


def fields(buf: bytes, pos: int, end: int) -> Iterator[tuple[int, int, int, int]]:
    """(number, start, payload start, end) of each protobuf field in buf[pos:end]; only varint and
    length-delimited fields occur in ONNX models."""
    while pos < end:
        start = pos
        key, pos = _read(buf, pos)
        if key & 7 not in (0, 2):
            raise NarrateError(f"unexpected wire type {key & 7} in ONNX model")
        n, pos = _read(buf, pos)
        yield key >> 3, start, pos, pos + n * (key & 7 == 2)
        pos += n * (key & 7 == 2)
    if pos != end:
        raise NarrateError("truncated ONNX model")


def with_outputs(model: bytes, names: Sequence[str], prune: bool = False) -> bytes:
    """ONNX `model` with tensors `names` added as graph outputs or, if `prune`, as its only outputs
    with just their ancestor nodes and initializers (HANDBOOK §10.4)."""
    m = memoryview(model)

    def strings(lo: int, hi: int, tag: int) -> set[str]:
        return {bytes(m[a:b]).decode() for f, _, a, b in fields(model, lo, hi) if f == tag}

    try:
        _, start, lo, hi = next(f for f in fields(model, 0, len(model)) if f[0] == 7)
        parts = list(fields(model, lo, hi))
        need, keep, made = set(names), set(), set()
        for f, a, b, c in reversed(parts):
            if f == 1:
                made |= (outs := strings(b, c, 2))
                if outs & need:
                    keep.add(a)
                    need |= strings(b, c, 1)
        if prune:
            parts = [
                (f, a, b, c)
                for f, a, b, c in parts
                if f != 12 and (f != 1 or a in keep) and (f != 5 or strings(b, c, 8) & need)
            ]
    except StopIteration:
        raise NarrateError("ONNX model has no graph") from None
    except IndexError as e:
        raise NarrateError("truncated ONNX model") from e
    if missing := sorted(set(names) - made):
        raise NarrateError(f"no node of the ONNX model computes {missing}")
    body = b"".join(
        [*(m[a:c] for _, a, _, c in parts), *(_field(12, _field(1, n.encode())) for n in names)]
    )
    return b"".join([m[:start], _uvarint(7 << 3 | 2), _uvarint(len(body)), body, m[hi:]])


def fit(d: npt.NDArray[np.float32], speed: float) -> float:
    """Speed input near `speed` for which Kokoro's frame counts max(1, round(d/s)) of the
    unrounded counts d at speed 1 sum closest to sum(d)/speed; ties go to the nearest speed."""
    s = (speed * (1 + np.arange(-200, 201) / 1000)).astype(np.float32)
    err = np.abs(np.maximum(1, np.round(d[None] / s[:, None])).sum(1) - d.sum() / speed)
    return float(s[np.lexsort((np.abs(s - speed), err))[0]])


class Kokoro:
    """Kokoro-82M v1.0 ONNX voice from the model files in `root` (HANDBOOK §10.2); word spans from
    predicted token durations (Algorithm 10.1)."""

    rate, hop, max_tokens, headroom = 24000, 600, 510, 0.5
    model, voices = "kokoro-v1.0.onnx", "voices-v1.0.bin"
    durations, predicted = "/encoder/Clip_output_0", "/encoder/predictor/ReduceSum_output_0"

    def __init__(
        self,
        root: Path,
        voice: str = "af_heart",
        wpm: int = 135,
        threads: int = 1,
        espeak: str = "espeak-ng",
    ) -> None:
        import onnxruntime as ort  # type: ignore[import-untyped]

        self.wpm = wpm
        try:
            self.vocab: dict[str, int] = json.loads((root / "config.json").read_text())["vocab"]
            with np.load(root / self.voices, allow_pickle=False) as v:
                self.style = v[voice].astype("<f4").reshape(-1, 256)
            model = (root / self.model).read_bytes()
            opts = ort.SessionOptions()
            opts.intra_op_num_threads, opts.inter_op_num_threads = threads, 1
            self.session, self.predictor = (
                ort.InferenceSession(m, opts, providers=["CPUExecutionProvider"])
                for m in (
                    with_outputs(model, [self.durations]),
                    with_outputs(model, [self.predicted], prune=True),
                )
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
                f"{wpm}wpm",
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

    def chunks(self, text: str) -> Iterator[tuple[list[int], Spans]]:
        """Token ids and word token ranges of each piece of `text`."""
        words = self.g2p.words(text)
        for lo, hi in self.pieces(words, 0, len(words)):
            tok, ranges = self.tokens(words[lo:hi])
            if not any(b > a for a, b in ranges):
                raise NarrateError(f"nothing to pronounce in {text!r}")
            if len(tok) > self.max_tokens:
                raise NarrateError(f"{len(tok)} tokens exceed {self.max_tokens} in {text!r}")
            yield tok, ranges

    def feed(self, tok: Sequence[int], speed: float) -> dict[str, npt.NDArray[np.generic]]:
        return {
            "tokens": np.array([[0, *tok, 0]], dtype=np.int64),
            "style": self.style[len(tok) - 1][None],
            "speed": np.array([speed], dtype=np.float32),
        }

    def predict(self, tok: Sequence[int]) -> npt.NDArray[np.float32]:
        """Unrounded frames at speed 1 of each token of the padded sequence."""
        (d,) = self.predictor.run(None, self.feed(tok, 1.0))
        return np.ravel(d).astype(np.float32)

    def natural(self, text: str) -> float:
        """Seconds from the start of the first word to the end of the last at speed 1."""
        parts = [(self.predict(t), r) for t, r in self.chunks(text)]
        (d0, r0), (d1, r1) = parts[0], parts[-1]
        head, tail = float(d0[: r0[0][0] + 1].sum()), float(d1[r1[-1][1] + 1 :].sum())
        return (sum(float(d.sum()) for d, _ in parts) - head - tail) * self.hop / self.rate

    def synth(self, text: str, speed: float = 1.0) -> tuple[PCM, Spans]:
        audio: list[npt.NDArray[np.float32]] = []
        spans: Spans = []
        at = 0
        for tok, ranges in self.chunks(text):
            feed = self.feed(tok, fit(self.predict(tok), speed))
            wave_, dur = self.session.run(None, feed)
            frames = self.hop * np.concatenate([[0], np.cumsum(np.ravel(dur))]).astype(int)
            spans += [(at + int(frames[a + 1]), at + int(frames[b + 1])) for a, b in ranges]
            audio.append(np.ravel(wave_).astype(np.float32))
            at += audio[-1].size
        x = np.concatenate(audio) * self.headroom
        pcm: PCM = np.round(np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
        return pcm, spans
