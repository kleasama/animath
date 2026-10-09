"""Evaluation of a produced video."""

from animath.core.schemas import (
    DocIR,
    KnowledgeGraph,
    Manifest,
    Narration,
    SceneRender,
    SourceBundle,
    Storyboard,
)
from animath.core.store import Store
from animath.eval import formula, judge, metrics
from animath.llm import LLM

__all__ = ["evaluate", "formula", "judge", "metrics"]


def evaluate(
    store: Store, digest: str, expected: DocIR | None = None, llm: LLM | None = None
) -> dict[str, float]:
    """Q1..Q7 and N1 of the manifest `digest`; Q2 needs `expected`, Q7 needs `llm`."""
    m = store.get(Manifest, digest)
    a = m.artifacts
    board = store.get(Storyboard, a["storyboard"])
    doc = store.get(DocIR, a["doc"])
    ids = [s.id for s in board.scenes]
    renders = {i: store.get(SceneRender, a[f"render/{i}"]) for i in ids}
    narrations = {i: store.get(Narration, a[f"narration/{i}"]) for i in ids}
    params = store.get(SourceBundle, a["source"]).params
    out = metrics.automatic(
        doc, store.get(KnowledgeGraph, a["graph"]), board, renders, narrations, m, params
    )
    if expected is not None:
        out["q2_fidelity"] = formula.fidelity(expected, doc)[0]
    if llm is not None:
        frames = judge.keyframes(store.blob_path(m.video), m.metrics["duration_s"])
        out["q7_pedagogy"] = judge.judge(board, doc, frames, llm)[0].score
    return out
