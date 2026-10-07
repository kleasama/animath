import numpy as np
import pytest

from animath.core.errors import NarrateError
from animath.core.schemas import Narration, Word
from animath.narrate.align import bounds, captions, fade, timeline
from tests.narrate.conftest import tone

RATE = 1000


@pytest.mark.parametrize(
    ("pcm", "span"),
    [
        (tone(300, lead=200, tail=300), (150, 550)),
        (tone(300), (0, 300)),
        (tone(95, lead=3, tail=2), (0, 100)),
        (np.concatenate([np.full(400, 20), np.full(100, 40), np.full(500, 20)]), (350, 550)),
    ],
)
def test_bounds_by_frame_rms_with_padding(pcm: np.ndarray, span: tuple[int, int]) -> None:
    assert bounds(pcm.astype(np.int16), RATE) == span


def test_bounds_rejects_silence_below_floor() -> None:
    with pytest.raises(NarrateError, match="silent"):
        bounds(np.full(100, 32, np.int16), RATE)


def test_fade_is_raised_cosine_at_both_ends() -> None:
    y = fade(np.full(100, 1000, np.int16), RATE)
    assert (y[0], y[9]) == (6, 994)
    assert np.all(y[10:90] == 1000)
    assert np.array_equal(y, y[::-1])
    assert fade(np.array([5], np.int16), RATE).tolist() == [5]


def test_timeline_layout_words_and_marks() -> None:
    u1 = ("ab cdefg,", {"m1": 0, "m2": 1}, tone(300, lead=200, tail=300), [(150, 260), (300, 600)])
    u2 = ("x.", {"m3": 0, "end": 4}, tone(100, lead=60), [(0, 160)])
    audio, words, marks = timeline([u1, u2], RATE)
    assert audio.size == 300 + 400 + 400 + 150 + 600
    assert not audio[:300].any()
    assert not audio[700:1100].any()
    assert not audio[1250:].any()
    assert max(abs(int(audio[300])), abs(int(audio[699]))) < 10
    assert [(w.text, w.start, w.end) for w in words] == [
        ("ab", 0.3, 0.41),
        ("cdefg,", 0.45, 0.7),
        ("x.", 1.1, 1.25),
    ]
    assert marks == {"m1": 0.3, "m2": 0.45, "m3": 1.1, "end": 1.1}
    n = Narration(
        scene_id="s",
        audio="0" * 64,
        duration_s=audio.size / RATE,
        words=tuple(words),
        bookmarks=marks,
    )
    assert n.duration_s - n.words[-1].end == pytest.approx(0.6)


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
