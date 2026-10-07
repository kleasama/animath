from animath.core.schemas import Narration, Word
from animath.narrate.subtitles import cues, stamp, vtt


def words(*spec: tuple[str, float, float]) -> tuple[Word, ...]:
    return tuple(Word(text=t, start=a, end=b) for t, a, b in spec)


def test_stamp() -> None:
    assert stamp(0) == "00:00:00.000"
    assert stamp(3723.4567) == "01:02:03.457"


def test_cues_break_at_sentence_pause_and_width() -> None:
    ws = words(
        ("One.", 0.0, 0.4),
        ("Two", 0.5, 0.7),
        ("three", 0.7, 1.0),
        ("four", 1.5, 1.8),
        ("abcdefghij", 1.8, 2.0),
        ("klmnopqrst", 2.0, 2.2),
    )
    assert cues(ws, width=8) == [
        (0.0, 0.4, "One."),
        (0.5, 1.0, "Two\nthree"),
        (1.5, 2.0, "four\nabcdefghij"),
        (2.0, 2.2, "klmnopqrst"),
    ]
    assert cues(()) == []


def test_vtt_offsets_tracks() -> None:
    n1 = Narration(scene_id="a", audio="0" * 64, duration_s=1, words=words(("Hi.", 0.1, 0.5)))
    n2 = Narration(scene_id="b", audio="0" * 64, duration_s=1, words=words(("Bye", 0.0, 0.25)))
    assert vtt([(n1, 0.0), (n2, 61.0)]) == (
        "WEBVTT\n\n00:00:00.100 --> 00:00:00.500\nHi.\n\n00:01:01.000 --> 00:01:01.250\nBye\n"
    )
