import json
from collections.abc import Sequence

import pytest
from pydantic import JsonValue

from animath.core.errors import LLMError, PlanError
from animath.core.schemas import KnowledgeGraph, Node, NodeKind, Params, Storyboard, Usage
from animath.core.store import Store
from animath.llm import Replay
from animath.plan import run, select
from animath.plan.draft import Draft, prompt
from tests.fake import Fake
from tests.plan.conftest import T, line, make_draft

Cat = dict[str, dict[str, JsonValue]]


def bad() -> Draft:
    d = make_draft()
    d.scenes[1] = d.scenes[1].model_copy(update={"narration": [line(30)]})
    return d


def test_run_caches(
    graph: KnowledgeGraph, store: Store, draft: Draft, cat: Cat, kernels: Cat
) -> None:
    fake = Fake(draft)
    board, usage = run(graph, Params(duration_s=T), cat, store, fake, kernels)
    assert isinstance(board, Storyboard)
    assert usage == Usage(input_tokens=1)
    task = json.loads(fake.prompts[0])
    assert (task["words_target"], task["scenes_target"], task["seeds"]) == (54, 1, ["mom"])
    assert task["wpm"] == 135
    assert [n["id"] for n in task["nodes"]] == ["efie", "mom"]
    assert task["edges"] == [{"src": "mom", "dst": "efie", "rel": "depends_on"}]
    assert task["formulas"] == {}
    again = run(graph, Params(duration_s=T, fps=30, voice="x"), cat, store, Fake(), kernels)
    assert again == (board, Usage())


def test_run_keys_on_the_speaker(
    graph: KnowledgeGraph, store: Store, draft: Draft, cat: Cat, kernels: Cat
) -> None:
    class Speaker:
        id = "sre:t"

        def lines(self, texts: Sequence[str]) -> list[str]:
            return list(texts)

    p, sp = Params(duration_s=T), Speaker()
    board, _ = run(graph, p, cat, store, Fake(draft), kernels)
    assert run(graph, p, cat, store, Fake(draft), kernels, sp) == (board, Usage(input_tokens=1))
    assert run(graph, p, cat, store, Fake(), kernels, sp) == (board, Usage())


def test_repair_then_success(
    graph: KnowledgeGraph, store: Store, draft: Draft, cat: Cat, kernels: Cat
) -> None:
    fake = Fake(bad(), draft)
    board, usage = run(graph, Params(duration_s=T), cat, store, fake, kernels)
    assert usage == Usage(input_tokens=2)
    assert fake.prompts[1].startswith(fake.prompts[0])
    assert fake.prompts[1].endswith(
        "Errors:\nscene s2: nothing changes for 15 s from scene s2.narration[0]; add actions\n"
        "estimated length 32 s at 135 words per minute with gaps and pauses, target 28 s within "
        "10%: cut about 9 words"
    )
    assert board.duration_s == T


def test_retries_exhausted(graph: KnowledgeGraph, store: Store, cat: Cat) -> None:
    fake = Fake(bad(), bad())
    with pytest.raises(PlanError, match=r"after 1 repairs.*estimated length 32 s"):
        run(graph, Params(duration_s=T, max_retries=1), cat, store, fake)
    assert not fake.outs


def test_replay_offline(graph: KnowledgeGraph, store: Store, draft: Draft, cat: Cat) -> None:
    p = Params(duration_s=T)
    board, _ = run(graph, p, cat, store, Replay(store, Fake(draft), "t"))
    fresh = Store(store.root.parent / "fresh")
    fresh_llm = Replay(store, None, "t")
    assert run(graph, p, cat, fresh, fresh_llm) == (board, Usage())
    with pytest.raises(LLMError, match="offline"):
        run(graph, Params(duration_s=T, audience="expert"), cat, fresh, fresh_llm)


def test_prompt_offers_the_other_formulas(graph: KnowledgeGraph, cat: Cat, kernels: Cat) -> None:
    w = Node(id="w", kind=NodeKind.EQUATION, name="W", latex="w = 1", sources=("b3",))
    g = KnowledgeGraph(nodes=(*graph.nodes, w), edges=graph.edges)
    p = Params(duration_s=T)
    task = json.loads(prompt(g, select(g, p), p, cat, kernels))
    assert ([n["id"] for n in task["nodes"]], task["formulas"]) == (["efie", "mom"], {"w": "w = 1"})
