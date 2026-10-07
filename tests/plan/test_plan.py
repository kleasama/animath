import json

import pytest
from pydantic import JsonValue

from animath.core.errors import LLMError, PlanError
from animath.core.schemas import KnowledgeGraph, Params, Storyboard, Usage
from animath.core.store import Store
from animath.llm import Replay
from animath.plan import run
from animath.plan.draft import Draft
from tests.plan.conftest import Fake, T, line, make_draft

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
    assert usage == Usage(input_tokens=7)
    task = json.loads(fake.prompts[0])
    assert (task["words_target"], task["scenes_target"], task["seeds"]) == (50, 1, ["mom"])
    assert [n["id"] for n in task["nodes"]] == ["efie", "mom"]
    assert task["edges"] == [{"src": "mom", "dst": "efie", "rel": "depends_on"}]
    again = run(graph, Params(duration_s=T, fps=30, voice="x"), cat, store, Fake(), kernels)
    assert again == (board, Usage())


def test_repair_then_success(
    graph: KnowledgeGraph, store: Store, draft: Draft, cat: Cat, kernels: Cat
) -> None:
    fake = Fake(bad(), draft)
    board, usage = run(graph, Params(duration_s=T), cat, store, fake, kernels)
    assert usage == Usage(input_tokens=14)
    assert fake.prompts[1].startswith(fake.prompts[0])
    assert "Errors:\nspoken words 60, target 50 within 10%" in fake.prompts[1]
    assert board.duration_s == T


def test_retries_exhausted(graph: KnowledgeGraph, store: Store, cat: Cat) -> None:
    fake = Fake(bad(), bad())
    with pytest.raises(PlanError, match=r"after 1 repairs.*spoken words 60"):
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
