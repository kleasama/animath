import heapq
import math
from collections import deque
from dataclasses import dataclass

from animath.core.errors import PlanError
from animath.core.schemas import Audience, KnowledgeGraph, Node, Params, Relation

SECONDS_PER_NODE = 15.0
DEPTH: dict[Audience, int | None] = {
    Audience.UNDERGRADUATE: None,
    Audience.GRADUATE: 2,
    Audience.EXPERT: 1,
}


@dataclass(frozen=True)
class Selection:
    """Nodes to teach, in order; their seeds; the other nodes with formulas, which scenes may
    show."""

    nodes: tuple[Node, ...]
    seeds: frozenset[str]
    context: tuple[Node, ...] = ()

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(n.id for n in self.nodes)


def seeds(g: KnowledgeGraph, focus: str | None) -> list[str]:
    """Focus matches by id, source block id or name substring; else key nodes; else sinks."""
    if focus is not None:
        f = focus.casefold()
        hit = [
            n.id for n in g.nodes if focus == n.id or focus in n.sources or f in n.name.casefold()
        ]
        if not hit:
            raise PlanError(f"focus {focus!r} matches no node")
        return hit
    if key := [n.id for n in g.nodes if n.key]:
        return key
    needed = {e.dst for e in g.edges if e.rel is Relation.DEPENDS_ON}
    return [n.id for n in g.nodes if n.id not in needed]


def select(g: KnowledgeGraph, p: Params) -> Selection:
    """Algorithm 7.1: hop-limited, budgeted prerequisite closure of the seeds, ordered, and the
    other nodes with latex as context."""
    s = seeds(g, p.focus)
    out: dict[str, list[str]] = {n.id: [] for n in g.nodes}
    for e in g.edges:
        out[e.src].append(e.dst)
    hops = dict.fromkeys(s, 0)
    queue = deque(s)
    limit = DEPTH[p.audience]
    while queue:
        u = queue.popleft()
        if limit is not None and hops[u] >= limit:
            continue
        for v in out[u]:
            if v not in hops:
                hops[v] = hops[u] + 1
                queue.append(v)
    pos = {n.id: i for i, n in enumerate(g.nodes)}
    budget = max(len(s), math.ceil(p.duration_s / SECONDS_PER_NODE))
    keep = set(sorted(hops, key=lambda i: (hops[i], pos[i]))[:budget])
    nodes = tuple(g.nodes[pos[i]] for i in order(g, keep, pos))
    return Selection(nodes, frozenset(s), tuple(n for n in g.nodes if n.latex and n.id not in keep))


def order(g: KnowledgeGraph, keep: set[str], pos: dict[str, int]) -> list[str]:
    """Kahn's algorithm on depends_on restricted to `keep`, prerequisites first, ties by `pos`."""
    succ: dict[str, list[str]] = {i: [] for i in keep}
    indeg = dict.fromkeys(keep, 0)
    for e in g.edges:
        if e.rel is Relation.DEPENDS_ON and e.src in keep and e.dst in keep:
            succ[e.dst].append(e.src)
            indeg[e.src] += 1
    heap = [(pos[i], i) for i in keep if not indeg[i]]
    heapq.heapify(heap)
    res: list[str] = []
    while heap:
        _, u = heapq.heappop(heap)
        res.append(u)
        for v in succ[u]:
            indeg[v] -= 1
            if not indeg[v]:
                heapq.heappush(heap, (pos[v], v))
    return res
