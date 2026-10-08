import pytest

from animath.core.errors import PlanError
from animath.core.schemas import Audience, Edge, KnowledgeGraph, Node, NodeKind, Params, Relation
from animath.plan.select import seeds, select

D, U = Relation.DEPENDS_ON, Relation.USES


def chain(key: bool = True) -> KnowledgeGraph:
    """r -> c2 -> c1 -> c0 by depends_on; r uses x; x uses r (cycle outside depends_on); z apart."""
    n = [
        Node(id="z", kind=NodeKind.CONCEPT, name="Unrelated", sources=("b9",)),
        Node(id="c0", kind=NodeKind.CONCEPT, name="Vector space", sources=("b0",)),
        Node(id="x", kind=NodeKind.SYMBOL, name="x", latex="x", sources=("b1",)),
        Node(id="c1", kind=NodeKind.CONCEPT, name="Inner product", sources=("b1",)),
        Node(id="c2", kind=NodeKind.CONCEPT, name="Krylov space", sources=("b2",)),
        Node(id="r", kind=NodeKind.RESULT, name="GMRES optimality", key=key, sources=("b3",)),
    ]
    e = [
        Edge(src="r", dst="c2", rel=D),
        Edge(src="c2", dst="c1", rel=D),
        Edge(src="c1", dst="c0", rel=D),
        Edge(src="r", dst="x", rel=U),
        Edge(src="x", dst="r", rel=U),
    ]
    return KnowledgeGraph(nodes=tuple(n), edges=tuple(e))


@pytest.mark.parametrize(
    ("focus", "expected"),
    [("c1", ["c1"]), ("b1", ["x", "c1"]), ("krylov", ["c2"]), (None, ["r"])],
)
def test_seeds(focus: str | None, expected: list[str]) -> None:
    assert seeds(chain(), focus) == expected


def test_seeds_without_key_are_sinks_of_depends_on() -> None:
    assert seeds(chain(key=False), None) == ["z", "x", "r"]


def test_unmatched_focus_raises() -> None:
    with pytest.raises(PlanError, match="matches no node"):
        seeds(chain(), "lanczos")


@pytest.mark.parametrize(
    ("audience", "ids"),
    [
        (Audience.UNDERGRADUATE, ["c0", "x", "c1", "c2", "r"]),
        (Audience.GRADUATE, ["x", "c1", "c2", "r"]),
        (Audience.EXPERT, ["x", "c2", "r"]),
    ],
)
def test_closure_depth_and_order(audience: Audience, ids: list[str]) -> None:
    sel = select(chain(), Params(audience=audience))
    assert [n.id for n in sel.nodes] == ids
    assert sel.seeds == {"r"}
    assert sel.ids == set(ids)


def test_budget_keeps_nearest_hops() -> None:
    sel = select(chain(), Params(audience=Audience.UNDERGRADUATE, duration_s=45))
    assert [n.id for n in sel.nodes] == ["x", "c2", "r"]


def test_budget_never_drops_seeds() -> None:
    sel = select(chain(), Params(focus="b1", duration_s=1))
    assert sel.ids == {"x", "c1"}


def test_order_waits_for_all_prerequisites() -> None:
    g = chain()
    g = KnowledgeGraph(nodes=g.nodes, edges=(*g.edges, Edge(src="r", dst="c0", rel=D)))
    ids = [n.id for n in select(g, Params(audience=Audience.EXPERT)).nodes]
    assert ids == ["c0", "x", "c2", "r"]


def test_context_is_the_other_formula_nodes() -> None:
    g = chain()
    z = g.nodes[0].model_copy(update={"latex": "z"})
    g = KnowledgeGraph(nodes=(z, *g.nodes[1:]), edges=g.edges)
    assert select(g, Params(audience=Audience.EXPERT)).context == (z,)
    assert select(g, Params(focus="b9")).context == (g.nodes[2],)
