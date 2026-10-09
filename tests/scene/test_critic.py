import io
from functools import partial
from pathlib import Path

import numpy as np
import pytest
from manim import FadeIn, Square
from PIL import Image

from animath.core.errors import AnimateError
from animath.core.schemas import Narration, Params, SceneRender, Usage, Visual
from animath.core.store import Store
from animath.scene.critic import (
    Issue,
    Verdict,
    blank,
    critique,
    frames,
    keyframes,
    png,
    silent,
    static,
)
from animath.scene.primitives import Cue
from animath.scene.render import shoot
from tests.fake import Fake
from tests.scene.conftest import scene

EQ = Visual(primitive="equation", args={"latex": "x", "until": "b"})
TXT = Visual(primitive="text", args={"text": "T", "region": "title"}, at="b")
S = scene(EQ, TXT)
H = "0" * 64


def cue(t: float, rt: float, what: str = "") -> Cue:
    return Cue(t, rt, partial(FadeIn, Square()), None, what)


def test_keyframes() -> None:
    d = SceneRender(scene_id="s", clip=H, duration_s=4.0, bookmarks={"a": 0.0, "b": 2.0})
    cues = [cue(0.0, 1.0), cue(2.0, 1.0), cue(2.5, 0.5)]
    assert keyframes(S, d, cues, 10) == [(19, [0]), (39, [1])]
    assert keyframes(S, d, [cue(0.0, 4.0)], 10) == []
    many = [cue(t, 0.1) for t in np.arange(0.0, 4.0, 0.5)]
    assert keyframes(S, d, many, 10, k=3) == [(4, [0]), (24, [1]), (39, [1])]


def test_static() -> None:
    assert static([cue(0.0, 1.5), cue(5.0, 1.0), cue(14.5, 1.0)], 24.0) == [
        (6.0, 14.5),
        (15.5, 24.0),
    ]
    assert static([cue(0.0, 20.0), cue(1.0, 1.0)], 24.0) == []
    assert static([], 8.5) == [(0.0, 8.5)]


def test_blank_and_png() -> None:
    img = np.zeros((240, 426, 3), np.uint8)
    img[20, 200] = 255
    assert not blank(img, "title")
    assert blank(img, "main")
    assert blank(img, "footer")
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(png(img)))), img)


@pytest.fixture(scope="module")
def draft(tmp_path_factory: pytest.TempPathFactory) -> tuple[Store, SceneRender, list[Cue]]:
    store = Store(tmp_path_factory.mktemp("critic"))
    return (store, *shoot(S, Params(), store, draft=True))


def test_frames(draft: tuple[Store, SceneRender, list[Cue]]) -> None:
    store, d, _ = draft
    path = str(store.blob_path(d.clip))
    a, b = frames(path, [25, 0])
    assert a.shape == (240, 426, 3)
    assert a.max() > 128
    assert b.max() < 128
    with pytest.raises(AnimateError, match=r"frames \[60\] missing"):
        frames(path, [60])


def test_silent(store: Store) -> None:
    acts = [
        {"at": "a", "do": "mark", "parts": ["x"], "color": "RED"},
        {"at": "b", "do": "mark", "parts": ["x"], "color": "RED"},
    ]
    s = scene(Visual(primitive="equation", args={"latex": "x + y", "actions": acts}))
    d, cues = shoot(s, Params(), store, draft=True)
    (quiet,) = silent(str(store.blob_path(d.clip)), cues, 15)
    assert quiet.what == "s.0:equation: mark x at 2.40 s"


def test_critique_vlm(draft: tuple[Store, SceneRender, list[Cue]]) -> None:
    store, d, cues = draft
    issues = (
        Issue(visual=1, problem="clipped"),
        Issue(problem="dull"),
        Issue(visual=9, problem="odd"),
    )
    llm = Fake(Verdict(), Verdict(issues=issues))
    assert critique(S, d, cues, store, llm) == ([], Usage(input_tokens=1))
    out, _ = critique(S, d, cues, store, llm)
    assert out == ["s.1:text: clipped", "scene s: dull", "scene s: odd"]
    name, prompt, images = llm.calls[0]
    assert name == "Verdict"
    assert len(images) == len(keyframes(S, d, cues, 15)) == 1
    assert all(i.startswith(b"\x89PNG") for i in images)
    assert '"t": 1.867' in prompt


def test_critique_motion_skips_vlm(store: Store) -> None:
    s = scene(Visual(primitive="equation", args={"latex": "x"}), duration=12.0)
    d, cues = shoot(s, Params(), store, draft=True)
    llm = Fake()
    assert critique(s, d, cues, store, llm) == (
        ["scene s: nothing changes from 1.5 s to 11.4 s while the narration goes on; add actions"],
        Usage(),
    )
    acts = [{"at": "b", "do": "mark", "parts": ["x"], "color": "WHITE"}]
    s = scene(Visual(primitive="equation", args={"latex": "x", "actions": acts}))
    d, cues = shoot(s, Params(), store, draft=True)
    (e,) = critique(s, d, cues, store, llm)[0]
    assert e == "s.0:equation: mark x at 2.40 s: no visible change"
    assert llm.calls == []


def test_critique_blank_skips_vlm(tmp_path: Path) -> None:
    store = Store(tmp_path)
    s = scene(Visual(primitive="code", args={"code": "def build(array):\n    return VGroup()"}))
    d, cues = shoot(s, Params(), store, draft=True)
    llm = Fake()
    assert critique(s, d, cues, store, llm) == (
        ["s.0:code: nothing visible in region main at t=3.33 s"],
        Usage(),
    )
    assert llm.calls == []


def test_critique_ignores_entering_visuals(tmp_path: Path) -> None:
    store = Store(tmp_path)
    code = {"code": "def build(array):\n    return VGroup()"}
    s = scene(Visual(primitive="code", args=code, at="b"))
    nar = Narration(scene_id="s", audio=H, duration_s=4.0, bookmarks={"a": 0.0, "b": 3.6})
    d, cues = shoot(s, Params(), store, nar, draft=True)
    llm = Fake(Verdict())
    assert critique(s, d, cues, store, llm) == ([], Usage(input_tokens=1))
