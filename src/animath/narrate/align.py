from collections.abc import Mapping, Sequence

import numpy as np

from animath.core.errors import NarrateError
from animath.core.schemas import Word
from animath.narrate.tts import PCM, Spans

FRAME_S, FLOOR_DB, PAD_S, FADE_S = 0.01, -60.0, 0.05, 0.01
LEAD_S, GAP_S, TAIL_S = 0.3, 0.4, 0.6

Utterance = tuple[str, Mapping[str, int], PCM, Spans]


def bounds(pcm: PCM, rate: int) -> tuple[int, int]:
    """[a, b) from the first to the last 10 ms frame with RMS above FLOOR_DB, widened by PAD_S."""
    f = round(FRAME_S * rate)
    n = -(-pcm.size // f)
    x = np.zeros(n * f)
    x[: pcm.size] = pcm / 32768
    loud = np.flatnonzero((x.reshape(n, f) ** 2).mean(1) > 10 ** (FLOOR_DB / 10))
    if not loud.size:
        raise NarrateError("synthesized utterance is silent")
    pad = round(PAD_S * rate)
    return max(0, int(loud[0]) * f - pad), min(pcm.size, (int(loud[-1]) + 1) * f + pad)


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
    """Trimmed, faded utterances after LEAD_S, joined by GAP_S, before TAIL_S.

    Word times are the spans shifted to the timeline and clamped to the trimmed audio; a bookmark
    (name -> word index in its utterance) is the start of that word.
    """
    pieces = [np.zeros(round(LEAD_S * rate), np.int16)]
    gap = np.zeros(round(GAP_S * rate), np.int16)
    words: list[Word] = []
    marks: dict[str, float] = {}
    off = pieces[0].size
    for text, cues, pcm, spans in utterances:
        a, b = bounds(pcm, rate)
        t = (off + np.clip(np.reshape(spans, (-1, 2)), a, b) - a) / rate
        ws = [
            Word(text=w, start=float(s), end=float(e))
            for w, (s, e) in zip(text.split(), t, strict=True)
        ]
        marks |= {m: ws[min(i, len(ws) - 1)].start for m, i in cues.items()}
        words += ws
        pieces += [fade(pcm[a:b], rate), gap]
        off += b - a + gap.size
    pieces[-1] = np.zeros(round(TAIL_S * rate), np.int16)
    return np.concatenate(pieces), words, marks
