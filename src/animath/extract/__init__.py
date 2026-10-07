"""Stage Φ2: DocIR -> KnowledgeGraph."""

from animath.core.errors import ExtractError
from animath.core.hashing import digest_of
from animath.core.schemas import Block, DocIR, Edge, KnowledgeGraph, Node, Usage
from animath.core.store import Store
from animath.extract import draft, graph
from animath.llm import LLM

VERSION = "1"
__all__ = ["VERSION", "run"]


def part(
    doc: DocIR,
    blocks: list[Block],
    nodes: dict[str, Node],
    edges: list[Edge],
    llm: LLM,
    retries: int,
    final: bool,
) -> tuple[dict[str, Node], list[Edge], Usage]:
    base = p = draft.prompt(doc, blocks, list(nodes.values()))
    usage = Usage()
    for _ in range(retries + 1):
        d, u = llm.parse(draft.Draft, draft.SYSTEM, p)
        usage += u
        n, e, problems = graph.merge(doc, nodes, edges, d, final)
        if not problems:
            return n, e, usage
        fix = "\n".join(f"- {x}" for x in problems)
        p = f"{base}\nYour previous graph:\n{d.model_dump_json()}\nFix these problems:\n{fix}"
    raise ExtractError(f"blocks {blocks[0].id}..{blocks[-1].id} invalid after {retries} retries")


def run(doc: DocIR, store: Store, llm: LLM, retries: int = 3) -> tuple[KnowledgeGraph, Usage]:
    """Extract `doc`; skipped iff a graph is indexed under the stage key (Invariant 4.1.2)."""
    key = Store.key("extract", VERSION, digest_of(doc))
    if (kg := store.lookup(KnowledgeGraph, key)) is not None:
        return kg, Usage()
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    usage = Usage()
    parts = draft.chunks(doc.blocks, draft.CHARS)
    for i, blocks in enumerate(parts):
        nodes, edges, u = part(doc, blocks, nodes, edges, llm, retries, i == len(parts) - 1)
        usage += u
    kg = KnowledgeGraph(nodes=tuple(nodes.values()), edges=tuple(edges))
    store.put(kg, key)
    return kg, usage
