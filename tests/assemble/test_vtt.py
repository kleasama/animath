import pytest

from animath.assemble import vtt
from animath.core.schemas import Word


@pytest.mark.parametrize(
    ("t", "s"),
    [(0.0, "00:00:00.000"), (3661.5, "01:01:01.500"), (59.9996, "00:01:00.000")],
)
def test_stamp(t: float, s: str) -> None:
    assert vtt.stamp(t) == s


def _words(texts: list[str], step: float = 0.5) -> list[Word]:
    return [Word(text=x, start=i * step, end=(i + 1) * step) for i, x in enumerate(texts)]


def test_cues_break_at_stops_and_shift() -> None:
    cs = vtt.cues(_words(["Let", "x.", "Then", "y?", "Done"]), 10.0)
    assert cs == [(10.0, 11.0, "Let x."), (11.0, 12.0, "Then y?"), (12.0, 12.5, "Done")]


def test_cues_break_at_length_and_wrap() -> None:
    words = _words(["abcdefghi"] * 10, step=0.1)
    cs = vtt.cues(words, 0.0)
    assert [c[2].replace("\n", " ") for c in cs] == [
        " ".join(["abcdefghi"] * 8),
        "abcdefghi abcdefghi",
    ]
    assert all(len(line) <= vtt.LINE_CHARS for line in cs[0][2].split("\n"))
    assert cs[0][2].count("\n") == 1


def test_cues_break_at_duration() -> None:
    cs = vtt.cues(_words(["a", "b", "c", "d"], step=2.0), 0.0)
    assert [(a, b) for a, b, _ in cs] == [(0.0, 6.0), (6.0, 8.0)]


def test_cue_never_empty_interval_and_long_token_unwrapped() -> None:
    long = "x" * 60
    assert vtt.cues([Word(text=long, start=1.0, end=1.0)], 0.0) == [(1.0, 1.001, long)]


def test_webvtt_escapes() -> None:
    assert vtt.webvtt([(0.0, 1.0, "a<b & c>d")]) == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\na&lt;b &amp; c&gt;d\n\n"
    )
    assert vtt.webvtt([]) == "WEBVTT\n\n"
