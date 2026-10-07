"""Stage Φ3: (KnowledgeGraph, Params) -> Storyboard."""

from animath.core.errors import PlanError
from animath.core.hashing import digest_of
from animath.core.schemas import KnowledgeGraph, Params, Storyboard, Usage
from animath.core.store import Store
from animath.llm import LLM
from animath.plan.check import build
from animath.plan.draft import SYSTEM, Draft, Schemas, prompt, repair
from animath.plan.select import Selection, select

VERSION = "2"
PLAN_PARAMS = {"duration_s", "wpm", "audience", "focus", "language", "max_retries"}
__all__ = ["VERSION", "Selection", "run", "select"]


def run(
    graph: KnowledgeGraph,
    params: Params,
    catalog: Schemas,
    store: Store,
    llm: LLM,
    kernels: Schemas | None = None,
) -> tuple[Storyboard, Usage]:
    """Algorithm 7.3; skipped iff a Storyboard is indexed under the stage key."""
    kernels = kernels or {}
    p = params.model_dump(mode="json", include=PLAN_PARAMS)
    key = Store.key("plan", VERSION, digest_of(graph), digest_of([p, dict(catalog), dict(kernels)]))
    if (hit := store.lookup(Storyboard, key)) is not None:
        return hit, Usage()
    sel = select(graph, params)
    base = prompt(graph, sel, params, catalog, kernels)
    text, usage = base, Usage()
    for _ in range(params.max_retries + 1):
        d, u = llm.parse(Draft, SYSTEM, text)
        usage += u
        board, errors = build(d, sel, params.duration_s, catalog, kernels, params.wpm)
        if board is not None:
            store.put(board, key)
            return board, usage
        text = repair(base, d, errors)
    raise PlanError(f"storyboard invalid after {params.max_retries} repairs: {errors}")
