import textwrap
from collections.abc import Sequence

from animath.core.schemas import Narration, Word

WIDTH = 42
PAUSE_S = 0.25


def stamp(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}"


def cues(words: Sequence[Word], width: int = WIDTH) -> list[tuple[float, float, str]]:
    """Two-line cues of at most `width` columns; break at sentence ends and pauses."""
    groups: list[list[Word]] = []
    size = 0
    for w in words:
        prev = groups[-1][-1] if groups else None
        if (
            prev is None
            or size + 1 + len(w.text) > 2 * width
            or prev.text[-1] in ".?!"
            or w.start - prev.end > PAUSE_S
        ):
            groups.append([])
            size = -1
        groups[-1].append(w)
        size += 1 + len(w.text)
    return [
        (
            g[0].start,
            g[-1].end,
            "\n".join(textwrap.wrap(" ".join(w.text for w in g), width, break_long_words=False)),
        )
        for g in groups
    ]


def vtt(tracks: Sequence[tuple[Narration, float]]) -> str:
    """WebVTT for narrations placed at the given offsets (seconds) on the video timeline."""
    out = ["WEBVTT", ""]
    for n, off in tracks:
        for a, b, text in cues(n.words):
            out += [f"{stamp(a + off)} --> {stamp(b + off)}", text, ""]
    return "\n".join(out)
