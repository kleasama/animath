import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animath.core.errors import AnimateError
from animath.core.schemas import Narration, Params, SceneRender, Usage, Visual
from animath.core.store import Store
from animath.scene.codegen import registered
from animath.scene.critic import Issue, Verdict, blank, critique, frames, keyframes, png
from animath.scene.render import render
from tests.scene.conftest import scene
from tests.scene.fake import Fake

EQ = Visual(primitive="equation", args={"latex": "x", "until": "b"})
TXT = Visual(primitive="text", args={"text": "T", "region": "title"}, at="b")
S = scene(EQ, TXT)


def test_keyframes() -> None:
    times = {"a": 0.0, "b": 2.0}
    assert keyframes(S, times, 4.0, 10) == [(14, [0]), (34, [1])]
    late = scene(Visual(primitive="text", args={"text": "T"}, at="b"))
    assert keyframes(late, times, 4.0, 10) == [(34, [0])]
    marks = tuple("abcde")
    many = scene(
        *(Visual(primitive="text", args={"text": m, "until": m}) for m in marks[1:]), marks=marks
    )
    t = {m: float(i) for i, m in enumerate(marks)}
    assert keyframes(many, t, 5.0, 10) == [
        (4, [0, 1, 2, 3]),
        (14, [1, 2, 3]),
        (24, [2, 3]),
        (34, [3]),
    ]
    assert keyframes(many, t, 5.0, 10, k=2) == [(4, [0, 1, 2, 3]), (34, [3])]


def test_blank_and_png() -> None:
    img = np.zeros((240, 426, 3), np.uint8)
    img[20, 200] = 255
    assert not blank(img, "title")
    assert blank(img, "main")
    assert blank(img, "footer")
    assert np.array_equal(np.asarray(Image.open(io.BytesIO(png(img)))), img)


@pytest.fixture(scope="module")
def draft(tmp_path_factory: pytest.TempPathFactory) -> tuple[Store, SceneRender]:
    store = Store(tmp_path_factory.mktemp("critic"))
    return store, render(S, Params(), store, draft=True)


def test_frames(draft: tuple[Store, SceneRender]) -> None:
    store, d = draft
    path = str(store.blob_path(d.clip))
    a, b = frames(path, [21, 0])
    assert a.shape == (240, 426, 3)
    assert a.max() > 128
    assert b.max() < 128
    with pytest.raises(AnimateError, match=r"frames \[60\] missing"):
        frames(path, [60])


def test_critique_vlm(draft: tuple[Store, SceneRender]) -> None:
    store, d = draft
    issues = (
        Issue(visual=1, problem="clipped"),
        Issue(problem="dull"),
        Issue(visual=9, problem="odd"),
    )
    llm = Fake(Verdict(), Verdict(issues=issues))
    assert critique(S, d, store, llm) == ([], Usage(input_tokens=1))
    out, _ = critique(S, d, store, llm)
    assert out == ["s.1:text: clipped", "scene s: dull", "scene s: odd"]
    name, prompt, images = llm.calls[0]
    assert name == "Verdict"
    assert len(images) == 2
    assert all(i.startswith(b"\x89PNG") for i in images)
    assert '"t": 1.4' in prompt


def test_critique_blank_skips_vlm(tmp_path: Path) -> None:
    store = Store(tmp_path)
    s = scene(Visual(primitive="code", args={"code": "def build(array):\n    return VGroup()"}))
    with registered():
        d = render(s, Params(), store, draft=True)
    llm = Fake()
    assert critique(s, d, store, llm) == (
        ["s.0:code: nothing visible in region main at t=3.40 s"],
        Usage(),
    )
    assert llm.calls == []


def test_critique_ignores_entering_visuals(tmp_path: Path) -> None:
    store = Store(tmp_path)
    code = {"code": "def build(array):\n    return VGroup()"}
    s = scene(Visual(primitive="code", args=code, at="b"))
    nar = Narration(scene_id="s", audio="0" * 64, duration_s=4.0, bookmarks={"a": 0.0, "b": 3.6})
    with registered():
        d = render(s, Params(), store, nar, draft=True)
    llm = Fake(Verdict())
    assert critique(s, d, store, llm) == ([], Usage(input_tokens=1))
