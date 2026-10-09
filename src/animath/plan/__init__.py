"""Stage Φ3: (KnowledgeGraph, Params) -> Storyboard."""

from collections.abc import Sequence
from typing import Protocol

from animath.core.errors import PlanError
from animath.core.hashing import digest_of
from animath.core.schemas import KnowledgeGraph, Params, Storyboard, Usage
from animath.core.store import Store
from animath.llm import LLM
from animath.plan.check import build
from animath.plan.draft import SYSTEM, Draft, Schemas, prompt, repair
from animath.plan.select import Selection, select

VERSION = "5"
PLAN_PARAMS = {"duration_s", "wpm", "audience", "focus", "language", "max_retries"}
__all__ = ["VERSION", "Selection", "Speaker", "run", "select"]


class Speaker(Protocol):
    """Spoken form of narration lines, as the narration speaks them (`narrate.Verbalizer`)."""

    id: str

    def lines(self, texts: Sequence[str]) -> list[str]: ...


def run(
    graph: KnowledgeGraph,
    params: Params,
    catalog: Schemas,
    store: Store,
    llm: LLM,
    kernels: Schemas | None = None,
    speaker: Speaker | None = None,
) -> tuple[Storyboard, Usage]:
    """Skipped iff a Storyboard is indexed under the stage key. `speaker` counts
    the spoken words of lines; without it, tokens are estimated."""
    kernels = kernels or {}
    p = params.model_dump(mode="json", include=PLAN_PARAMS)
    said = speaker.lines if speaker else None
    inputs = [p, dict(catalog), dict(kernels), speaker.id if speaker else None]
    key = Store.key("plan", VERSION, digest_of(graph), digest_of(inputs))
    if (hit := store.lookup(Storyboard, key)) is not None:
        return hit, Usage()
    sel = select(graph, params)
    base = prompt(graph, sel, params, catalog, kernels)
    text, usage = base, Usage()
    for _ in range(params.max_retries + 1):
        d, u = llm.parse(Draft, SYSTEM, text)
        usage += u
        board, errors = build(d, sel, params.duration_s, catalog, kernels, params.wpm, said)
        if board is not None:
            store.put(board, key)
            return board, usage
        text = repair(base, d, errors)
    raise PlanError(f"storyboard invalid after {params.max_retries} repairs: {errors}")
