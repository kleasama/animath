from collections.abc import Sequence

import numpy as np

from animath.core.errors import NarrateError
from animath.core.schemas import Word
from animath.narrate.tts import PCM

THRESHOLD = 328
GAP_S = 0.3


def voiced(pcm: PCM) -> tuple[int, int]:
    """Half-open sample range [a, b) whose ends exceed THRESHOLD (about -40 dBFS)."""
    idx = np.flatnonzero(np.abs(pcm.astype(np.int32)) > THRESHOLD)
    if not idx.size:
        raise NarrateError("synthesized line is silent")
    return int(idx[0]), int(idx[-1]) + 1


def timeline(
    lines: Sequence[tuple[str, str | None, PCM]], rate: int, gap_s: float = GAP_S
) -> tuple[PCM, list[Word], dict[str, float]]:
    """Concatenate trimmed line audio with gaps; bookmark = line onset, words by length share."""
    pieces: list[PCM] = []
    words: list[Word] = []
    marks: dict[str, float] = {}
    gap = np.zeros(round(gap_s * rate), dtype=np.int16)
    off = 0
    for text, mark, pcm in lines:
        a, b = voiced(pcm)
        n = b - a
        if mark:
            marks[mark] = off / rate
        tokens = text.split()
        cum = np.cumsum([0] + [1 + sum(c.isalnum() for c in t) for t in tokens])
        at = off + np.round(n * cum / cum[-1]).astype(int)
        words += [
            Word(text=t, start=at[i] / rate, end=at[i + 1] / rate) for i, t in enumerate(tokens)
        ]
        pieces += [pcm[a:b], gap]
        off += n + gap.size
    audio = np.concatenate(pieces[:-1]) if pieces else np.zeros(0, dtype=np.int16)
    return audio, words, marks
