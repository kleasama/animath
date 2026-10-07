import json
from typing import Any

import pytest
from pydantic import JsonValue

from animath.core.schemas import KnowledgeGraph, Node, NodeKind, Params
from animath.plan.check import build, plan, position, script, static, words
from animath.plan.draft import DAction, DData, DLine, DLoop, Draft, DScene
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


def act(visual: int = 0, do: str = "mark", **kw: Any) -> DAction:
    return DAction(visual=visual, do=do, **kw)


def loop_scene(brief: list[str], speedup: float = 2.0) -> DScene:
    """At 60 wpm one token lasts 1 s: pass 1 is 4 s of speech, 1 s hold and a 0.35 s gap."""
    first = DLine(text="a b c d", actions=[act(parts=["x{}"], word="c")])
    return DScene(
        id="s",
        goal="g",
        narration=[],
        loop=DLoop(over=["1", "2", "3"], lines=[first], brief=brief, speedup=speedup),
        visuals=[vis("equation", latex="x_1 x_2 x_3")],
    )


def test_words() -> None:
    assert words(r"Since $\frac{a}{b} = x_1$, done.") == 2 + 1.5 * 5
    assert words("...") == 0


def test_position() -> None:
    assert position(None, "a b") == 0.0
    assert position("Select", "we select a cluster") == 0.25
    assert position("cluster,", "we select a Cluster.") == 0.75
    assert position("sel", "we select a cluster") is None
    assert position("value", "the $x + y$ value") == pytest.approx(2 / 3)
    assert position("x", "the $x$ value") is None
    assert position("", "a b") is None


def test_script_holds_and_bookmarks() -> None:
    ds = DScene(
        id="s",
        goal="g",
        narration=[line(2, "a"), line(3), line(1, "c")],
        visuals=[vis("text", "c", text="t")],
    )
    errs: list[str] = []
    beats = script(ds, 60, errs)
    assert errs == []
    assert [b.bookmark for b in beats] == ["a", "#1", "c"]
    assert [b.pause for b in beats] == [0.0, 0.0, 1.0]
    assert [b.onset for b in beats] == pytest.approx([0.0, 2.35, 5.7])


def test_loop_per_item_brief() -> None:
    errs: list[str] = []
    beats = script(loop_scene(["e {}", "g"]), 60, errs)
    assert errs == []
    assert [b.text for b in beats] == ["a b c d", "e 2", "g"]
    assert [b.pause for b in beats] == pytest.approx([1.0, 0.325, 1.0])
    first = {"at": "#0", "do": "mark", "parts": ["x1"], "word": "c", "frac": 0.3738}
    assert beats[0].acts == [(0, first)]
    assert beats[1].acts == [
        (0, {"at": "#1", "do": "mark", "parts": ["x2"], "frac": 0.3738, "rate": 2.0})
    ]
    assert beats[2].acts == [
        (0, {"at": "#2", "do": "mark", "parts": ["x3"], "frac": 0.25, "rate": 4.0})
    ]


def test_loop_one_brief_for_all() -> None:
    beats = script(loop_scene(["h {}"]), 60, [])
    assert [b.text for b in beats] == ["a b c d", "h {}"]
    assert beats[1].pause == pytest.approx(3.0125)
    assert [(a["parts"], a["frac"], a["rate"]) for _, a in beats[1].acts] == [
        (["x2"], 0.2492, 2.0),
        (["x3"], 0.7913, 4.0),
    ]


def test_loop_floor_keeps_steps_readable() -> None:
    beats = script(loop_scene(["e", "g"], speedup=8.0), 60, [])
    assert [a["rate"] for b in beats[1:] for _, a in b.acts] == [5.35, 5.35]


def test_after_lines_follow_the_loop() -> None:
    ds = loop_scene(["e", "g"]).model_copy(update={"after": [line(1, "z")]})
    assert [b.bookmark for b in script(ds, 60, [])] == ["#0", "#1", "#2", "z"]
    assert script(DScene(id="s", goal="g", narration=[], visuals=[]), 60, []) == []


@pytest.mark.parametrize(
    ("loop", "message"),
    [
        (DLoop(over=[], lines=[line(1)], brief=["b"]), "needs two items, lines"),
        (DLoop(over=["1"], lines=[line(1)], brief=["b"]), "needs two items, lines"),
        (DLoop(over=["1", "2"], lines=[], brief=["b"]), "needs two items, lines"),
        (DLoop(over=["1", "2"], lines=[line(1)], brief=["b"], speedup=0.5), "speedup >= 1"),
        (DLoop(over=["1", "2", "3", "4"], lines=[line(1)], brief=["b", "c"]), "one for all"),
    ],
)
def test_loop_rejects(loop: DLoop, message: str) -> None:
    errs: list[str] = []
    script(DScene(id="s", goal="g", narration=[line(1)], loop=loop, visuals=[]), 60, errs)
    assert len(errs) == 1
    assert message in errs[0]


def test_word_must_be_spoken() -> None:
    errs: list[str] = []
    ln = DLine(text="the $t$ cluster", actions=[act(word="t")])
    script(DScene(id="s", goal="g", narration=[ln], visuals=[]), 60, errs)
    assert errs == ["scene s.narration[0].actions[0]: word 't' is no plain word of the line"]


def test_static_stretches(sel: Selection, cat: Cat) -> None:
    ds = DScene(id="s", goal="g", narration=[line(10)], visuals=[vis("text", text="t")])
    p = plan(ds, sel, cat, {}, 60, {}, [])
    assert static(p) == ["scene s: nothing changes for 11 s from scene s.narration[0]; add actions"]
    ds.narration[0].actions.append(act(word="word"))
    assert static(plan(ds, sel, cat, {}, 60, {}, [])) == [
        "scene s: nothing changes for 11 s from scene s.narration[0]; add actions"
    ]
    ds.narration[:] = [line(5), line(5, None, act(do="indicate"))]
    assert static(plan(ds, sel, cat, {}, 60, {}, [])) == []


def test_valid_board(draft: Draft, sel: Selection, cat: Cat, kernels: Cat) -> None:
    board, errs = build(draft, sel, T, cat, kernels)
    assert errs == []
    assert board is not None
    assert [s.duration_s for s in board.scenes] == pytest.approx([16.869, 11.131], abs=1e-3)
    assert board.duration_s == pytest.approx(T)
    assert board.symbols == {"Z": "impedance matrix"}
    s1 = board.scenes[0]
    assert s1.visuals[1].args["series"] == [
        {"x": [0, 1], "y": {"data": 0, "array": "current", "part": "abs"}}
    ]
    assert s1.visuals[1].args["actions"] == [{"at": "#2", "do": "indicate", "parts": []}]
    assert [(ln.bookmark, ln.pause_s) for ln in s1.narration] == [("a", 1), ("b", 1), ("#2", 1)]
    assert s1.data[0].params == {"ka": 1, "n": 20}


def test_ledger_prefers_graph(sel: Selection, cat: Cat, kernels: Cat) -> None:
    z = Node(id="Z", kind=NodeKind.SYMBOL, name="Z", latex="Z", meaning="MoM", sources=("b1",))
    s = Selection((*sel.nodes, z), sel.seeds)
    board, _ = build(make_draft(), s, T, cat, kernels)
    assert board is not None
    assert board.symbols == {"Z": "MoM"}


def test_no_scenes(sel: Selection, cat: Cat, kernels: Cat) -> None:
    assert errors(Draft(title="x", scenes=[]), sel, cat, kernels) == ["no scenes"]


def test_length_budget(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = edit(1, narration=[line(10, None, act(1, "indicate")) for _ in range(3)])
    assert errors(d, sel, cat, kernels) == [
        "estimated length 33 s at 135 words per minute with gaps and pauses, target 28 s within "
        "10%: cut about 11 words"
    ]
    (e,) = errors(edit(1, narration=[line(10)]), sel, cat, kernels)
    assert e.endswith("target 28 s within 10%: add about 12 words")


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
        (vis("text", text="t", region="footer", replaces=1), "replaces 1 names no earlier"),
    ],
)
def test_visual_errors(visual: Any, message: str, sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[1].visuals.append(visual)
    errs = errors(d, sel, cat, kernels)
    assert len(errs) == 1
    assert message in errs[0]


def test_replaces_follows_until(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].visuals.append(vis("equation", "b", latex="y", replaces=0, region="footer"))
    assert errors(d, sel, cat, kernels) == []
    d.scenes[0].visuals[3] = vis("equation", "a", latex="y", replaces=0, region="footer")
    assert any("replaces 0 names no earlier visual" in e for e in errors(d, sel, cat, kernels))


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (act(5), "scene s2: actions on visuals [5]; the scene has 2"),
        (act(1, "fly"), "scene s2.narration[0].actions[0]: $.do: 'fly' is not one of"),
        (act(1, color="pink"), "$.color: 'pink' is not valid under any of the given schemas"),
        (act(1, word="nope"), "word 'nope' is no plain word of the line"),
    ],
)
def test_action_errors(
    action: DAction, message: str, sel: Selection, cat: Cat, kernels: Cat
) -> None:
    d = make_draft()
    d.scenes[1].narration[0].actions.append(action)
    assert any(message in e for e in errors(d, sel, cat, kernels))


def test_action_outside_lifetime(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].narration[2].actions.append(act(0))
    assert errors(d, sel, cat, kernels) == [
        "scene s1.narration[2].actions[1]: visual 0 is not on screen during this line"
    ]


def test_view_continues(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].visuals[2] = vis("equation", latex="A = LU", region="title", view="op")
    d.scenes[0].narration[1].actions[:] = [act(2, parts=["L"]), act(2, "indicate", parts=["U"])]
    d.scenes[1].visuals.append(vis("equation", region="footer", view="op", until="#1"))
    d.scenes[1].narration[0].actions.append(act(2, "unmark", parts=["L"]))
    board, errs = build(d, sel, T, cat, kernels)
    assert errs == []
    assert board is not None
    old, new = board.scenes[0].visuals[2], board.scenes[1].visuals[2]
    assert old.args["persist"] is True
    assert new.args == {
        "latex": "A = LU",
        "region": "title",
        "view": "op",
        "enter": "none",
        "until": "#1",
        "actions": [
            {"do": "mark", "parts": ["L"]},
            {"at": "#0", "do": "unmark", "parts": ["L"]},
        ],
    }


def test_view_returns_after_a_zoom(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].narration[2].bookmark = "c"
    d.scenes[0].narration[0].actions.append(act(2, parts=["L"]))
    s1 = d.scenes[0].visuals
    s1[2] = vis("equation", latex="A = LU", region="title", view="op", until="b")
    s1.append(vis("equation", "b", latex="L", region="title", replaces=2, until="c"))
    s1.append(vis("equation", "c", region="footer", view="op", replaces=3))
    d.scenes[1].visuals.append(vis("equation", view="op"))
    board, errs = build(d, sel, T, cat, kernels)
    assert errs == []
    assert board is not None
    op = {"latex": "A = LU", "region": "title", "view": "op"}
    state = [{"do": "mark", "parts": ["L"]}]
    first, back = board.scenes[0].visuals[2].args, board.scenes[0].visuals[4].args
    assert "persist" not in first
    assert back == op | {"replaces": 3, "actions": state, "persist": True}
    assert board.scenes[1].visuals[2].args == op | {"enter": "none", "actions": state}


def test_view_reenters_after_a_scene_without_it(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].visuals[2] = vis("equation", latex="A", region="title", view="op")
    d.scenes.append(
        DScene(id="s3", goal="g", narration=[line(10)], visuals=[vis("equation", view="op")])
    )
    board, errs = build(d, sel, T + 10 * 60 / 135 + 1.0, cat, kernels)
    assert errs == []
    assert board is not None
    assert "persist" not in board.scenes[0].visuals[2].args
    assert board.scenes[2].visuals[0].args == {
        "latex": "A",
        "region": "title",
        "view": "op",
        "actions": [],
    }


def test_view_needs_same_primitive(sel: Selection, cat: Cat, kernels: Cat) -> None:
    d = make_draft()
    d.scenes[0].visuals[2] = vis("equation", latex="A", region="title", view="op")
    d.scenes[1].visuals.append(vis("text", region="footer", view="op"))
    assert errors(d, sel, cat, kernels) == [
        "scene s2.visual[2]: view 'op' continues a equation, not a text"
    ]


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
    d.scenes[1].narration[1].actions.clear()
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


def test_board_args_are_json(sel: Selection, cat: Cat, kernels: Cat) -> None:
    board, _ = build(make_draft(), sel, T, cat, kernels)
    assert board is not None
    assert json.loads(board.model_dump_json())["scenes"][1]["narration"][1]["pause_s"] == 1.0
