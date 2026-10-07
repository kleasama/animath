import threading
from pathlib import Path

import pytest

from animath.core.schemas import Line, Narration, Scene, Storyboard, Visual
from animath.core.store import Store
from animath.narrate import key, narrate, sentences
from animath.narrate.tts import PCM, Spans, from_wav
from animath.narrate.verbalize import Verbalizer
from tests.narrate.conftest import Script, tone

SAY = 'r = json.load(sys.stdin); print(json.dumps(["ex " * len(t) for t in r["latex"]]))'


class FakeTTS:
    """Each word is 40 samples of tone after 3 silent samples; 9 silent samples close."""

    id = "fake:1"
    rate = 1000

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def synth(self, text: str) -> tuple[PCM, Spans]:
        with self.lock:
            self.calls.append(text)
        n = len(text.split())
        return tone(40 * n, lead=3, tail=9), [(3 + 40 * i, 43 + 40 * i) for i in range(n)]


@pytest.fixture
def verbalizer(script: Script) -> Verbalizer:
    return Verbalizer(cmd=[script(SAY)])


def scene(sid: str, *lines: Line) -> Scene:
    return Scene(id=sid, goal="g", narration=lines, duration_s=5)


BOARD = Storyboard(
    title="GMRES",
    scenes=(
        scene("s1", Line(text="Minimise $r$ over K.", bookmark="k"), Line(text="Stop.")),
        scene("s2", Line(text="Restart.", bookmark="r")),
    ),
)


def test_sentences_join_lines_until_a_stop() -> None:
    lines = [
        Line(text="Take one leaf,", bookmark="t"),
        Line(text="with its coordinates.", bookmark="c"),
        Line(text="Then stop"),
        Line(text='here, he said "now."', bookmark="h"),
        Line(text="Tail", bookmark="z"),
    ]
    assert sentences(lines, [ln.text for ln in lines]) == [
        ("Take one leaf, with its coordinates.", {"t": 0, "c": 3}),
        ('Then stop here, he said "now."', {"h": 2}),
        ("Tail", {"z": 0}),
    ]


def test_narrate_produces_valid_narrations(store: Store, verbalizer: Verbalizer) -> None:
    tts = FakeTTS()
    out = narrate(BOARD, store, tts, verbalizer)
    assert list(out) == ["s1", "s2"]
    assert tts.calls == ["Minimise ex over K.", "Stop.", "Restart."]
    n = store.get(Narration, out["s1"])
    assert n.scene_id == "s1"
    assert n.bookmarks == {"k": 0.303}
    assert [w.text for w in n.words] == ["Minimise", "ex", "over", "K.", "Stop."]
    assert [c.text for c in n.captions] == ["Minimise", "r", "over", "K.", "Stop."]
    assert [(c.start, c.end) for c in n.captions] == [(w.start, w.end) for w in n.words]
    assert (n.words[3].end, n.words[4].start) == (0.463, 0.875)
    assert n.duration_s == (300 + 172 + 400 + 52 + 600) / 1000
    assert from_wav(store.get_blob(n.audio), 1000).size == 1524
    assert store.lookup(Narration, key(BOARD.scenes[1], tts, verbalizer)) is not None


def test_cached_scenes_are_skipped(store: Store, verbalizer: Verbalizer, tmp_path: Path) -> None:
    first = narrate(BOARD, store, FakeTTS(), verbalizer)
    tts = FakeTTS()
    edited = Storyboard(
        title="GMRES",
        scenes=(BOARD.scenes[0], scene("s2", Line(text="Restart now.", bookmark="r"))),
    )
    second = narrate(edited, store, tts, Verbalizer(cmd=["/nonexistent"]))
    assert second["s1"] == first["s1"]
    assert second["s2"] != first["s2"]
    assert tts.calls == ["Restart now."]


def test_key_ignores_visuals_and_tracks_backends(verbalizer: Verbalizer) -> None:
    s = BOARD.scenes[0]
    tts = FakeTTS()
    moved = s.model_copy(update={"visuals": (Visual(primitive="equation", at="k"),)})
    assert key(moved, tts, verbalizer) == key(s, tts, verbalizer)
    other = FakeTTS()
    other.id = "fake:2"
    assert key(s, other, verbalizer) != key(s, tts, verbalizer)
    assert key(s, tts, Verbalizer("mathspeak")) != key(s, tts, verbalizer)


def test_parallel_matches_serial(tmp_path: Path, verbalizer: Verbalizer) -> None:
    board = Storyboard(
        title="t", scenes=tuple(scene(f"s{i}", Line(text="a " * (i + 1))) for i in range(8))
    )
    serial = narrate(board, Store(tmp_path / "a"), FakeTTS(), verbalizer)
    parallel = narrate(board, Store(tmp_path / "b"), FakeTTS(), verbalizer, workers=4)
    assert serial == parallel
