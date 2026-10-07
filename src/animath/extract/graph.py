import re

from pydantic import ValidationError

from animath.core.schemas import Block, BlockType, DocIR, Edge, KnowledgeGraph, Node, NodeKind
from animath.extract.draft import DNode, Draft

SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")


def node(blocks: dict[str, Block], n: DNode) -> Node | str:
    """Validated node, or the problem; equation latex is copied from its first equation source."""
    eqs = [b.latex for s in n.sources if (b := blocks.get(s)) and b.type is BlockType.EQUATION]
    if not SLUG.fullmatch(n.id):
        return f"node {n.id!r}: id must match {SLUG.pattern}"
    if not n.sources or not blocks.keys() >= set(n.sources):
        return f"node {n.id}: sources must be existing block ids, got {n.sources}"
    if n.kind is NodeKind.EQUATION and not eqs:
        return f"node {n.id}: equation node without an equation block among its sources"
    if n.kind is NodeKind.SYMBOL and not (n.latex and n.meaning):
        return f"node {n.id}: symbol node needs latex and meaning"
    latex = eqs[0] if n.kind is NodeKind.EQUATION else n.latex
    return Node(
        id=n.id,
        kind=n.kind,
        name=n.name,
        latex=latex,
        meaning=n.meaning,
        key=n.key,
        sources=tuple(dict.fromkeys(n.sources)),
    )


def merge(
    doc: DocIR, nodes: dict[str, Node], edges: list[Edge], draft: Draft, final: bool
) -> tuple[dict[str, Node], list[Edge], list[str]]:
    """Fold `draft` into the graph (`nodes`, `edges`); same ids unite sources and key."""
    blocks = {b.id: b for b in doc.blocks}
    out, problems = dict(nodes), []
    for d in draft.nodes:
        n = node(blocks, d)
        if isinstance(n, str):
            problems.append(n)
        elif (old := out.get(n.id)) is None:
            out[n.id] = n
        elif old.kind is not n.kind:
            problems.append(f"node {n.id}: kind {n.kind} conflicts with {old.kind}")
        else:
            src = tuple(dict.fromkeys(old.sources + n.sources))
            out[n.id] = old.model_copy(update={"sources": src, "key": old.key or n.key})
    new = list(edges)
    for e in draft.edges:
        if e.src == e.dst:
            problems.append(f"edge {e.src} {e.rel} {e.dst}: self-loop")
        elif missing := sorted({e.src, e.dst} - out.keys()):
            problems.append(f"edge {e.src} {e.rel} {e.dst}: unknown nodes {missing}")
        else:
            new.append(Edge(src=e.src, dst=e.dst, rel=e.rel))
    new = list(dict.fromkeys(new))
    if final and not any(n.key for n in out.values()):
        problems.append("no node is key")
    if out and not problems:
        try:
            KnowledgeGraph(nodes=tuple(out.values()), edges=tuple(new))
        except ValidationError as e:
            problems += [str(x["msg"]) for x in e.errors()]
    return out, new, problems
