from collections.abc import Mapping, Sequence

import numpy as np

from animath.core.errors import NarrateError
from animath.core.schemas import Word
from animath.narrate.tts import PCM, Spans

FRAME_S, FLOOR_DB, PAD_S, FADE_S = 0.01, -60.0, 0.05, 0.01
LEAD_S, GAP_S, TAIL_S = 0.4, 0.35, 0.6

Utterance = tuple[str, Mapping[str, int], float, PCM, Spans]


def bounds(pcm: PCM, rate: int, words: tuple[int, int]) -> tuple[int, int]:
    """[a, b) over the 10 ms frames with RMS above FLOOR_DB and the word samples `words`, widened
    by PAD_S: quiet word ends stay whole."""
    f = round(FRAME_S * rate)
    n = -(-pcm.size // f)
    x = np.zeros(n * f)
    x[: pcm.size] = pcm / 32768
    loud = np.flatnonzero((x.reshape(n, f) ** 2).mean(1) > 10 ** (FLOOR_DB / 10))
    if not loud.size:
        raise NarrateError("synthesized utterance is silent")
    pad = round(PAD_S * rate)
    a, b = min(int(loud[0]) * f, words[0]), max((int(loud[-1]) + 1) * f, words[1])
    return max(0, a - pad), min(pcm.size, b + pad)


def fade(pcm: PCM, rate: int) -> PCM:
    """Raised-cosine fade-in and fade-out of FADE_S."""
    k = min(round(FADE_S * rate), pcm.size // 2)
    ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(k) + 0.5) / k)
    y = pcm.astype(np.float64)
    y[:k] *= ramp
    y[pcm.size - k :] *= ramp[::-1]
    out: PCM = np.round(y).astype(np.int16)
    return out


def timeline(
    utterances: Sequence[Utterance], rate: int
) -> tuple[PCM, list[Word], dict[str, float]]:
    """Trimmed, faded utterances placed by their words (LEAD_S, GAP_S + pause,
    TAIL_S); returns PCM, word times and bookmark times (starts of their words)."""
    clips: list[tuple[int, PCM]] = []
    words: list[Word] = []
    marks: dict[str, float] = {}
    at, end, last, pause = round(LEAD_S * rate), 0, 0, 0.0
    for text, cues, pause, pcm, spans in utterances:
        a, b = bounds(pcm, rate, (spans[0][0], spans[-1][1]))
        off = max(end, at - spans[0][0] + a)
        t = (off + np.clip(np.reshape(spans, (-1, 2)), a, b) - a) / rate
        ws = [
            Word(text=w, start=float(s), end=float(e))
            for w, (s, e) in zip(text.split(), t, strict=True)
        ]
        marks |= {m: ws[min(i, len(ws) - 1)].start for m, i in cues.items()}
        words += ws
        clips.append((off, fade(pcm[a:b], rate)))
        end, last = off + b - a, off + spans[-1][1] - a
        at = last + round((GAP_S + pause) * rate)
    out = np.zeros(max(end, last + round(max(TAIL_S, pause) * rate)), np.int16)
    for off, x in clips:
        out[off : off + x.size] = x
    return out, words, marks


def captions(tokens: Sequence[tuple[str, str]], words: Sequence[Word]) -> list[Word]:
    """Written tokens timed by their spoken words, which `words` lists in order."""
    out: list[Word] = []
    at = 0
    for text, said in tokens:
        ws = words[at : at + len(said.split())]
        at += len(ws)
        if ws and text:
            out.append(Word(text=text, start=ws[0].start, end=ws[-1].end))
    return out
