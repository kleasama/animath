from collections.abc import Iterable, Sequence
from html import escape

from animath.core.schemas import Word

MAX_CHARS = 84
LINE_CHARS = 42
MAX_CUE_S = 6.0
STOPS = (".", "?", "!", ";", ":")

Cue = tuple[float, float, str]


def _wrap(text: str) -> str:
    if len(text) <= LINE_CHARS or " " not in text:
        return text
    mid = len(text) // 2
    cut = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - mid))
    return f"{text[:cut]}\n{text[cut + 1 :]}"


def cues(words: Sequence[Word], offset: float) -> list[Cue]:
    """Timed words to cues shifted by offset; break at stops, MAX_CHARS, MAX_CUE_S."""
    out: list[Cue] = []
    run: list[Word] = []

    def flush() -> None:
        a, b = run[0].start, max(run[-1].end, run[0].start + 1e-3)
        out.append((offset + a, offset + b, _wrap(" ".join(w.text for w in run))))
        run.clear()

    for w in words:
        if run and (
            sum(len(x.text) + 1 for x in run) + len(w.text) > MAX_CHARS
            or w.end - run[0].start > MAX_CUE_S
        ):
            flush()
        run.append(w)
        if w.text.endswith(STOPS):
            flush()
    if run:
        flush()
    return out


def stamp(t: float) -> str:
    h, ms = divmod(round(t * 1000), 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def webvtt(cs: Iterable[Cue]) -> str:
    body = "".join(f"{stamp(a)} --> {stamp(b)}\n{escape(t, quote=False)}\n\n" for a, b, t in cs)
    return "WEBVTT\n\n" + body
