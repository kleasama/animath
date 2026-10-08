import json

import pytest

from animath.core.errors import AnimateError
from animath.core.schemas import Usage, Visual
from animath.core.store import Store
from animath.scene.repair import (
    PITFALLS,
    SYSTEM,
    Fix,
    Patch,
    apply,
    indices,
    pitfalls,
    record,
    repair,
)
from tests.scene.conftest import scene
from tests.scene.fake import Fake

EQ = Visual(primitive="equation", args={"latex": "x", "until": "b"})
TXT = Visual(primitive="text", args={"text": "T"}, at="b")
S = scene(EQ, TXT)


def fix(i: int, args: object = None, **kw: object) -> Fix:
    return Fix.model_validate(
        {"index": i, "primitive": "equation", "args": json.dumps(args or {"latex": "y"}), **kw}
    )


def test_indices() -> None:
    assert indices(S, "scene s: layout: s.1:text overlaps s.0:equation; s.7:x") == [0, 1]
    assert indices(S, "t.0:equation and ss.1:text") == []


def test_pitfall_memory(store: Store) -> None:
    assert pitfalls(store, ["equation"]) == []
    record(store, S, ["s.0:equation: build failed: a", "scene s: render failed: b"])
    record(store, S, ["s.0:equation: build failed: a"])
    assert pitfalls(store, ["equation"]) == ["s.0:equation: build failed: a"]
    assert pitfalls(store, ["scene", "equation", "scene"]) == [
        "s.0:equation: build failed: a",
        "scene s: render failed: b",
    ]
    record(store, S, [f"s.1:text: e{k}" for k in range(PITFALLS + 2)])
    assert pitfalls(store, ["text"]) == [f"s.1:text: e{k}" for k in range(2, PITFALLS + 2)]


def test_apply() -> None:
    out = apply(S, Patch(fixes=[fix(1, at="a")]), [1])
    assert out.visuals == (EQ, Visual(primitive="equation", args={"latex": "y"}, at="a"))


@pytest.mark.parametrize(
    ("f", "match"),
    [
        (fix(0), r"touches visual 0, not in \[1\]"),
        (Fix(index=1, primitive="equation", args="{"), "s.1:equation: args not JSON"),
        (Fix(index=1, primitive="equation", args="[1]"), "args not a JSON object"),
        (fix(1, at="z"), "patched scene invalid"),
    ],
)
def test_apply_rejects(f: Fix, match: str) -> None:
    with pytest.raises(AnimateError, match=match):
        apply(S, Patch(fixes=[f]), [1])


def test_repair_localizes(store: Store) -> None:
    record(store, S, ["s.1:text: old"])
    llm = Fake(Patch(fixes=[fix(1)]))
    out, bad, usage = repair(S, ["s.1:text: build failed: bad"], llm, store)
    assert (bad, usage.input_tokens) == ([], 1)
    assert out.visuals[1].primitive == "equation"
    ((name, prompt, images),) = llm.calls
    task = json.loads(prompt)
    assert (name, images, task["repair"], task["pitfalls"]) == ("Patch", (), [1], ["s.1:text: old"])
    assert task["errors"] == ["s.1:text: build failed: bad"]
    assert [v["index"] for v in task["visuals"]] == [0, 1]


def test_repair_memo_ignores_pitfalls(store: Store) -> None:
    llm = Fake(Patch(fixes=[fix(1)]))
    first = repair(S, ["s.1:text: bad"], llm, store)
    record(store, S, ["s.1:text: later"])
    assert repair(S, ["s.1:text: bad"], llm, store) == (first[0], [], Usage())
    assert len(llm.calls) == 1
    repair(S, ["s.1:text: other"], Fake(Patch(fixes=[fix(1)])), store)


def test_repair_memo_per_model(store: Store) -> None:
    a, b = Fake(Patch(fixes=[fix(1)])), Fake(Patch(fixes=[fix(1)]))
    a.tag, b.tag = "m:low", "m:high"  # type: ignore[attr-defined]
    repair(S, ["s.1:text: bad"], a, store)
    repair(S, ["s.1:text: bad"], b, store)
    repair(S, ["s.1:text: bad"], a, store)
    assert (len(a.calls), len(b.calls)) == (1, 1)


def test_repair_whole_scene(store: Store) -> None:
    llm = Fake(Patch(fixes=[fix(0)]))
    repair(S, ["scene s: render failed: x"], llm, store)
    assert json.loads(llm.calls[0][1])["repair"] == [0, 1]


def test_repair_rejected_patch(store: Store) -> None:
    out, bad, usage = repair(S, ["s.1:text: x"], Fake(Patch(fixes=[fix(0)])), store)
    assert out is S
    assert bad == ["scene s: patch touches visual 0, not in [1]"]
    assert usage.input_tokens == 1


def test_system_prompt() -> None:
    assert '"code": {' in SYSTEM
    assert '"derive": {' in SYSTEM
    assert "MathTex(*tex_strings" in SYSTEM
    assert '"main": [13.08, 5.6]' in SYSTEM
