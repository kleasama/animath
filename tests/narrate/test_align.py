import numpy as np
import pytest

from animath.core.errors import NarrateError
from animath.core.schemas import Narration
from animath.narrate.align import THRESHOLD, timeline, voiced
from tests.narrate.conftest import tone


def test_voiced_bounds() -> None:
    assert voiced(tone(100, lead=7, tail=30)) == (7, 107)
    quiet = np.full(50, THRESHOLD, dtype=np.int16)
    with pytest.raises(NarrateError, match="silent"):
        voiced(quiet)


def test_timeline_trims_gaps_and_marks_onsets() -> None:
    rate = 1000
    lines = [
        ("ab cdefg", "m1", tone(300, lead=50, tail=80)),
        ("x", None, tone(100, lead=5)),
        ("go", "m2", tone(200, tail=1)),
    ]
    audio, words, marks = timeline(lines, rate, gap_s=0.1)
    assert audio.size == 300 + 100 + 100 + 100 + 200
    assert marks == {"m1": 0.0, "m2": 0.6}
    assert [(w.text, w.start, w.end) for w in words] == [
        ("ab", 0.0, 0.1),
        ("cdefg", 0.1, 0.3),
        ("x", 0.4, 0.5),
        ("go", 0.6, 0.8),
    ]
    n = Narration(
        scene_id="s",
        audio="0" * 64,
        duration_s=audio.size / rate,
        words=tuple(words),
        bookmarks=marks,
    )
    assert n.words[-1].end == n.duration_s


def test_timeline_empty() -> None:
    audio, words, marks = timeline([], 1000)
    assert audio.size == 0
    assert words == []
    assert marks == {}
