"""Quality metrics on stored artifacts.

q1 render pass rate, q2 formula fidelity, q3 sync error (ms), q4 failed checks per scene,
q5 key-node coverage, q6 relative length error, q7 judge score, n1 untraced formula fraction.
"""

from collections.abc import Mapping

from animath.core.schemas import (
    DocIR,
    KnowledgeGraph,
    Manifest,
    Narration,
    Params,
    SceneRender,
    Storyboard,
)
from animath.eval import formula

TARGETS: dict[str, tuple[str, float]] = {
    "q1_render": (">=", 0.95),
    "q2_fidelity": (">=", 1.0),
    "q3_sync_ms": ("<=", 150.0),
    "q4_layout": ("<=", 0.0),
    "q5_coverage": (">=", 0.9),
    "q6_duration": ("<=", 0.1),
    "q7_pedagogy": (">=", 4.0),
    "n1_traced": (">=", 1.0),
}
VISUAL_CHECKS = ("layout", "critic")


def q1(renders: Mapping[str, SceneRender]) -> float:
    """Fraction of scenes whose render check passed."""
    return sum(r.checks.get("render", False) for r in renders.values()) / len(renders)


def q3(renders: Mapping[str, SceneRender], narrations: Mapping[str, Narration]) -> float:
    """max |t_visual - t_bookmark| in ms over the bookmarks of every scene."""
    gaps = [
        abs(t - narrations[sid].bookmarks[b])
        for sid, r in renders.items()
        for b, t in r.bookmarks.items()
        if b in narrations[sid].bookmarks
    ]
    return 1000.0 * max(gaps, default=0.0)


def q4(renders: Mapping[str, SceneRender]) -> float:
    """Failed layout and critic checks per scene."""
    bad = sum(not r.checks.get(c, True) for r in renders.values() for c in VISUAL_CHECKS)
    return bad / len(renders)


def q5(graph: KnowledgeGraph, board: Storyboard) -> float:
    """Fraction of key nodes addressed by some scene."""
    key = {n.id for n in graph.nodes if n.key}
    seen = {n for s in board.scenes for n in s.nodes}
    return len(key & seen) / len(key) if key else 1.0


def q6(manifest: Manifest, params: Params) -> float:
    """|T_actual - T| / T."""
    return abs(manifest.metrics["duration_s"] - params.duration_s) / params.duration_s


def n1(board: Storyboard, doc: DocIR) -> float:
    """Fraction of on-screen formulas traceable to the document or derived (formula.untraced)."""
    shown, bad = formula.untraced(board, doc)
    return 1.0 - len(bad) / shown if shown else 1.0


def automatic(
    doc: DocIR,
    graph: KnowledgeGraph,
    board: Storyboard,
    renders: Mapping[str, SceneRender],
    narrations: Mapping[str, Narration],
    manifest: Manifest,
    params: Params,
) -> dict[str, float]:
    """Metrics computable without reference data or judge."""
    return {
        "q1_render": q1(renders),
        "q3_sync_ms": q3(renders, narrations),
        "q4_layout": q4(renders),
        "q5_coverage": q5(graph, board),
        "q6_duration": q6(manifest, params),
        "n1_traced": n1(board, doc),
    }


def failures(values: Mapping[str, float]) -> list[str]:
    """Metrics of `values` missing their target."""
    return sorted(
        k
        for k, v in values.items()
        if k in TARGETS
        and not (v >= TARGETS[k][1] if TARGETS[k][0] == ">=" else v <= TARGETS[k][1])
    )
