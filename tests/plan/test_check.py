from typing import Any

import pytest
from pydantic import JsonValue

from animath.core.schemas import KnowledgeGraph, Node, NodeKind, Params
from animath.plan.check import build, words
from animath.plan.draft import DData, Draft, DScene
from animath.plan.select import Selection, select
from tests.plan.conftest import T, line, make_draft, vis

Cat = dict[str, dict[str, JsonValue]]


@pytest.fixture
def sel(graph: KnowledgeGraph) -> Selection:
    return select(graph, Params(duration_s=T))


def errors(d: Draft, sel: Selection, cat: Cat, kernels: Cat) -> list[str]:
    board, errs = build(d, sel, T, cat, kernels)
    assert (board is None) == bool(errs)
    return errs


def edit(scene: int = 0, **kw: Any) -> Draft:
    d = make_draft()
    d.scenes[scene] = d.scenes[scene].model_copy(update=kw)
    return d


def test_words() -> None:
    assert words(r"Since $\frac{a}{b} = x_1$, done.") == 7
    assert words("...") == 0


def test_valid_board(draft: Draft, sel: Selection, cat: Cat, kernels: Cat) -> None:
    board, errs = build(draft, sel, T, cat, kernels)
    assert errs == []
    assert board is not None
    assert [s.duration_s for s in board.scenes] == [12.0, 8.0]
    assert board.duration_s == T
    assert board.symbols == {"Z": "impedance matrix"}
    s1 = board.scenes[0]
    assert s1.visuals[1].args["series"] == [
        {"x": [0, 1], "y": {"data": 0, "array": "current", "part": "abs"}}
    ]
    assert s1.data[0].params == {"ka": 1, "n": 20}


def test_ledger_prefers_graph(sel: Selection, cat: Cat, kernels: Cat) -> None:
    z = Node(id="Z", kind=NodeKind.SYMBOL, name="Z", latex="Z", meaning="MoM", sources=("b1",))
    s = Selection((*sel.nodes, z), sel.seeds)
    board, _ = build(make_draft(), s, T, cat, kernels)
    assert board is not None
    assert board.symbols == {"Z": "MoM"}


def test_no_scenes(sel: Selection, cat: Cat, kernels: Cat) -> None:
    assert errors(Draft(title="x", scenes=[]), sel, cat, kernels) == ["no scenes"]


def test_word_budget(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = edit(1, narration=[line(30)])
    assert errors(d, sel, cat, kernels) == ["spoken words 60, target 50 within 10%"]


@pytest.mark.parametrize(
    ("visual", "message"),
    [
        (vis("cube"), "scene s2.visual[2]: unknown primitive 'cube'"),
        (vis("text", region="footer").model_copy(update={"args": "{"}), "invalid JSON"),
        (vis("text").model_copy(update={"args": "[1]"}), "not a JSON object"),
        (vis("equation", region="footer"), "$: 'latex' is a required property"),
        (vis("equation", latex="x", region="moon"), "$.region: 'moon' is not one of"),
        (
            vis(
                "plot",
                series=[{"x": [0], "y": {"data": 3, "array": "a", "part": "real"}}],
                region="footer",
            ),
            "names no data request",
        ),
        (
            vis("field", values={"data": 0, "array": "current"}, region="footer"),
            "lacks part",
        ),
        (vis("text", text="t", region="footer", until="zz"), "is no bookmark after at"),
        (vis("text", text="t", region="left"), "regions left, left overlap in time"),
    ],
)
def test_visual_errors(visual: Any, message: str, sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[1].visuals.append(visual)
    errs = errors(d, sel, cat, kernels)
    assert len(errs) == 1
    assert message in errs[0]


def test_until_must_follow_at(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].visuals[0] = vis("equation", "b", latex="x", until="a")
    assert any("until 'a' is no bookmark after at" in e for e in errors(d, sel, cat, kernels))


def test_sequential_visuals_share_region(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].visuals.append(vis("equation", "a", latex="y", region="footer", until="b"))
    d.scenes[0].visuals.append(vis("equation", "b", latex="z", region="footer"))
    assert errors(d, sel, cat, kernels) == []


def test_scene_errors(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = edit(1, visuals=[], nodes=["mom", "ghost"])
    errs = errors(d, sel, cat, kernels)
    assert errs == ["scene s2: no visuals", "scene s2: nodes outside the selection ['ghost']"]


def test_schema_validators_reported(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[1].visuals.append(vis("text", "nope", text="t", region="footer"))
    (e,) = errors(d, sel, cat, kernels)
    assert e.startswith("scene s2: Value error, scene s2: visuals cue unknown bookmarks ['nope']")


def test_coverage(sel: Selection, cat: Cat, kernels: Cat) -> None:
    assert errors(edit(1, nodes=[]), sel, cat, kernels) == ["seed nodes not covered: ['mom']"]


def test_duplicate_scene_ids(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = edit(1, id="s1")
    assert errors(d, sel, cat, kernels) == ["Value error, duplicate scene ids: ['s1']"]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (DData(kind="fft", params="{}"), "scene s2.data[0]: unknown kind 'fft'"),
        (DData(kind="krylov.cg", params='{"tol": -1}'), "scene s2.data[0]: $"),
        (DData(kind="krylov.cg", params="x"), "invalid JSON"),
    ],
)
def test_data_errors(data: DData, message: str, sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = edit(1, data=[data])
    errs = errors(d, sel, cat, kernels)
    assert errs
    assert all(message in e or "names no data request" in e for e in errs)
    assert any(message in e for e in errs)


def test_kernels_optional(sel: Selection, cat: Cat) -> None:
    d = edit(1, data=[DData(kind="anything", params="{}")])
    assert errors(d, sel, cat, {}) == []


def test_scene_returns_none_only_for_own_errors(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes.append(DScene(id="s3", goal="g", narration=[line(1)], visuals=[], nodes=[]))
    assert errors(d, sel, cat, kernels) == ["scene s3: no visuals"]
