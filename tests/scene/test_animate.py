import json

import pytest

from animath.core.errors import AnimateError
from animath.core.schemas import DataSet, Narration, Params, Visual
from animath.core.store import Store
from animath.scene.animate import animate
from animath.scene.critic import Issue, Verdict
from animath.scene.repair import Fix, Patch, pitfalls
from tests.scene.conftest import REQ, npy, scene
from tests.scene.fake import Fake

P = Params(width=320, height=240, fps=15, max_retries=2)
CIRCLE = json.dumps({"code": "def build(array):\n    return Circle(radius=2, color=BLUE)"})


def fix(i: int, primitive: str, args: str) -> Patch:
    return Patch(fixes=[Fix(index=i, primitive=primitive, args=args)])


def test_primitives_only_and_cache(store: Store) -> None:
    s = scene(Visual(primitive="equation", args={"latex": "x"}))
    llm = Fake(Verdict())
    out = animate(s, {}, None, store, llm, P)
    assert out.checks == {"layout": True, "render": True, "static": True, "critic": True}
    assert (out.scene_id, out.duration_s) == ("s", 4.0)
    assert [c[0] for c in llm.calls] == ["Verdict"]
    assert animate(s, {}, None, store, Fake(), P) == out
    assert animate(s, {}, None, store, Fake(Verdict()), P.model_copy(update={"fps": 30})) != out


def test_codegen_for_uncovered_visual(store: Store) -> None:
    s = scene(Visual(primitive="contour", args={"region": "main", "of": "|E|"}))
    llm = Fake(fix(0, "code", CIRCLE), Verdict())
    animate(s, {}, None, store, llm, P)
    assert [c[0] for c in llm.calls] == ["Patch", "Verdict"]
    assert "s.0:contour: not a catalog primitive" in llm.calls[0][1]


@pytest.mark.parametrize(
    ("visual", "first", "error"),
    [
        (
            Visual(primitive="equation", args={"latex": r"\frac{"}),
            None,
            "s.0:equation: build failed",
        ),
        (Visual(primitive="code", args={"code": "import os"}), None, "s.0:code: line 1: Import"),
        (
            Visual(primitive="equation", args={"latex": "x"}),
            Verdict(issues=(Issue(visual=0, problem="tiny"),)),
            "s.0:equation: tiny",
        ),
    ],
)
def test_repair_loop(store: Store, visual: Visual, first: Verdict | None, error: str) -> None:
    outs = [first] if first else []
    llm = Fake(*outs, fix(0, "code", CIRCLE), Verdict())
    out = animate(scene(visual), {}, None, store, llm, P)
    assert out.checks["critic"]
    patch = next(c for c in llm.calls if c[0] == "Patch")
    assert error in patch[1]
    assert any(error in p for p in pitfalls(store, [visual.primitive]))


def test_exhaustion(store: Store) -> None:
    s = scene(Visual(primitive="contour"))
    bad = fix(3, "code", CIRCLE)
    llm = Fake(bad, bad, bad)
    with pytest.raises(AnimateError, match=r"unresolved after 2 repairs: .*touches visual 3"):
        animate(s, {}, None, store, llm, P)
    assert len(llm.calls) == 3
    assert "touches visual 3" in llm.calls[1][1]


def test_key_covers_data_and_narration(store: Store) -> None:
    s = scene(Visual(primitive="equation", args={"latex": "x"}))
    data = {REQ.digest: DataSet(request=REQ, arrays={"u": npy(store, [1.0])})}
    nar = Narration(scene_id="s", audio="0" * 64, duration_s=3.0, bookmarks={"a": 0.0, "b": 1.5})
    out = animate(s, data, nar, store, Fake(Verdict()), P)
    assert (out.duration_s, out.bookmarks) == (3.0, {"a": 0.0, "b": 1.5})
    assert animate(s, data, nar, store, Fake(), P) == out
    other = {REQ.digest: DataSet(request=REQ, arrays={"u": npy(store, [2.0])})}
    llm = Fake(Verdict())
    animate(s, other, nar, store, llm, P)
    assert len(llm.calls) == 1
