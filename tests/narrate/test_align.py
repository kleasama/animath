import numpy as np
import pytest

from animath.core.errors import NarrateError
from animath.core.schemas import Narration, Word
from animath.narrate.align import bounds, captions, fade, timeline
from tests.narrate.conftest import tone

RATE = 1000


QUIET_LOUD_QUIET = np.concatenate([np.full(400, 20), np.full(100, 40), np.full(500, 20)])


@pytest.mark.parametrize(
    ("pcm", "words", "span"),
    [
        (tone(300, lead=200, tail=300), (250, 450), (150, 550)),
        (tone(300, lead=200, tail=300), (120, 700), (70, 750)),
        (tone(300), (0, 300), (0, 300)),
        (tone(95, lead=3, tail=2), (3, 98), (0, 100)),
        (QUIET_LOUD_QUIET, (420, 480), (350, 550)),
        (QUIET_LOUD_QUIET, (300, 900), (250, 950)),
    ],
)
def test_bounds_cover_loud_frames_and_words_with_padding(
    pcm: np.ndarray, words: tuple[int, int], span: tuple[int, int]
) -> None:
    assert bounds(pcm.astype(np.int16), RATE, words) == span


def test_bounds_rejects_silence_below_floor() -> None:
    with pytest.raises(NarrateError, match="silent"):
        bounds(np.full(100, 32, np.int16), RATE, (0, 100))


def test_fade_is_raised_cosine_at_both_ends() -> None:
    y = fade(np.full(100, 1000, np.int16), RATE)
    assert (y[0], y[9]) == (6, 994)
    assert np.all(y[10:90] == 1000)
    assert np.array_equal(y, y[::-1])
    assert fade(np.array([5], np.int16), RATE).tolist() == [5]


def test_timeline_layout_words_and_marks() -> None:
    u1 = (
        "ab cdefg,",
        {"m1": 0, "m2": 1},
        0.2,
        tone(300, lead=200, tail=300),
        [(150, 260), (300, 600)],
    )
    u2 = ("x.", {"m3": 0, "end": 4}, 1.0, tone(100, lead=60), [(0, 160)])
    audio, words, marks = timeline([u1, u2], RATE)
    assert audio.size == 350 + 550 + 500 + 160 + 1000
    assert not audio[:450].any()
    assert not audio[750:1460].any()
    assert not audio[1560:].any()
    assert (audio[450], audio[749]) == (8000, 8000)
    assert [(w.text, w.start, w.end) for w in words] == [
        ("ab", 0.4, 0.51),
        ("cdefg,", 0.55, 0.85),
        ("x.", 1.4, 1.56),
    ]
    assert marks == {"m1": 0.4, "m2": 0.55, "m3": 1.4, "end": 1.4}
    n = Narration(
        scene_id="s",
        audio="0" * 64,
        duration_s=audio.size / RATE,
        words=tuple(words),
        bookmarks=marks,
    )
    assert n.duration_s - n.words[-1].end == pytest.approx(1.0)
    short = timeline([(*u2[:2], 0.3, *u2[3:])], RATE)[0]
    assert short.size == 400 + 160 + 600


def test_timeline_never_overlaps_audio() -> None:
    early = ("y.", {"y": 0}, 0.0, tone(500), [(450, 500)])
    audio, words, marks = timeline([early, early], RATE)
    assert audio.size == 500 + 500 + 600
    assert [(w.start, w.end) for w in words] == [(0.45, 0.5), (0.95, 1.0)]
    assert marks == {"y": 0.95}


def test_captions_time_written_tokens_by_their_spoken_words() -> None:
    said = [
        ("Take", 0.0, 0.2),
        ("um", 0.2, 0.3),
        ("L", 0.3, 0.4),
        ("2", 0.4, 0.5),
        ("1.", 0.5, 0.7),
    ]
    words = [Word(text=t, start=a, end=b) for t, a, b in said]
    tokens = [("Take", "Take"), ("", "um"), ("L₂₁.", "L 2 1."), ("∅", "")]
    assert captions(tokens, words) == [
        Word(text="Take", start=0.0, end=0.2),
        Word(text="L₂₁.", start=0.3, end=0.7),
    ]
