import pytest

from animath.core.errors import ExtractError
from animath.core.schemas import Block, BlockType, DocIR, Edge, Node, NodeKind, Relation, Usage
from animath.core.store import Store
from animath.extract import draft, graph, run
from animath.extract.draft import DEdge, DNode, Draft, chunks, line, prompt
from tests.extract.conftest import Fake


def nd(id: str, kind: str = "concept", src: tuple[str, ...] = ("b0",), **kw: object) -> DNode:
    f: dict[str, object] = {"latex": None, "meaning": None, "key": False} | kw
    return DNode.model_validate({"id": id, "kind": kind, "name": id, "sources": list(src)} | f)


def ed(src: str, dst: str, rel: str = "depends_on") -> DEdge:
    return DEdge(src=src, dst=dst, rel=Relation(rel))


def blk(i: int, kind: BlockType = BlockType.PARAGRAPH, text: str = "x") -> Block:
    level = 1 if kind is BlockType.HEADING else None
    return Block(id=f"b{i}", type=kind, text=text, level=level)


def test_line(doc: DocIR) -> None:
    thm = Block(id="t", type=BlockType.THEOREM, text="T.", env="lemma", label="lem:a")
    assert [line(b) for b in (*doc.blocks[:2], thm)] == [
        "[b0 heading] Method of moments",
        r"[b1 equation eq:mom] \mathbf{Z}\mathbf{I}=\mathbf{V}",
        "[t theorem lemma lem:a] T.",
    ]


def test_chunks() -> None:
    h = BlockType.HEADING
    y = "y" * 30
    bs = (*(blk(i, h) if i % 2 == 0 else blk(i) for i in range(4)), blk(4, h))
    bs += (blk(5, text=y), blk(6, text=y), blk(7, text=y * 4))
    n = sum(len(line(b)) + 1 for b in bs[:4])
    ids = [[b.id for b in c] for c in chunks(bs, n)]
    assert ids == [["b0", "b1", "b2", "b3"], ["b4", "b5"], ["b6"], ["b7"]]
    assert chunks(bs, 10**6) == [list(bs)]


def test_prompt(doc: DocIR) -> None:
    known = Node(id="k", kind=NodeKind.CONCEPT, name="known", sources=("b0",))
    full = prompt(doc.model_copy(update={"macros": {r"\R": r"\def\R{\mathbb R}"}}), [], [known])
    assert full.splitlines() == [
        "Document: EFIE",
        "Macros:",
        r"\def\R{\mathbb R}",
        "Known nodes:",
        "k (concept): known",
        "Blocks:",
    ]
    assert prompt(doc, list(doc.blocks[:1]), []).splitlines() == [
        "Document: EFIE",
        "Blocks:",
        "[b0 heading] Method of moments",
    ]


@pytest.mark.parametrize(
    ("n", "msg"),
    [
        (nd("Bad Id"), "id must match"),
        (nd("a", src=()), "sources must be existing"),
        (nd("a", src=("b0", "zz")), "sources must be existing"),
        (nd("a", "equation", ("b0", "b2")), "without an equation block"),
        (nd("a", "symbol", latex="x"), "needs latex and meaning"),
        (nd("a", "symbol", meaning="m"), "needs latex and meaning"),
    ],
)
def test_node_problems(doc: DocIR, n: DNode, msg: str) -> None:
    out = graph.node({b.id: b for b in doc.blocks}, n)
    assert isinstance(out, str)
    assert msg in out


def test_node_equation_latex_from_source(doc: DocIR) -> None:
    n = graph.node(
        {b.id: b for b in doc.blocks}, nd("e", "equation", ("b2", "b1", "b1"), latex="Z")
    )
    assert isinstance(n, Node)
    assert (n.latex, n.sources) == (r"\mathbf{Z}\mathbf{I}=\mathbf{V}", ("b2", "b1"))


def test_merge_unites(doc: DocIR) -> None:
    old = {"a": Node(id="a", kind=NodeKind.CONCEPT, name="a", key=True, sources=("b0",))}
    d = Draft(
        nodes=[nd("a", src=("b2", "b0")), nd("s", "symbol", ("b2",), latex="x", meaning="m")],
        edges=[ed("s", "a"), ed("s", "a"), ed("a", "s", "uses")],
    )
    nodes, edges, problems = graph.merge(
        doc, old, [Edge(src="s", dst="a", rel=Relation.DEPENDS_ON)], d, True
    )
    assert problems == []
    assert nodes["a"].sources == ("b0", "b2")
    assert nodes["a"].key
    assert edges == [
        Edge(src="s", dst="a", rel=Relation.DEPENDS_ON),
        Edge(src="a", dst="s", rel=Relation.USES),
    ]


@pytest.mark.parametrize(
    ("d", "final", "msg"),
    [
        (Draft(nodes=[nd("A")], edges=[]), False, "id must match"),
        (Draft(nodes=[nd("a"), nd("a", "result")], edges=[]), False, "conflicts with"),
        (Draft(nodes=[nd("a")], edges=[ed("a", "a")]), False, "self-loop"),
        (Draft(nodes=[nd("a")], edges=[ed("a", "z")]), False, "unknown nodes ['z']"),
        (Draft(nodes=[nd("a"), nd("b")], edges=[ed("a", "b"), ed("b", "a")]), False, "cycle"),
        (Draft(nodes=[nd("a")], edges=[]), True, "no node is key"),
        (Draft(nodes=[], edges=[]), True, "no node is key"),
    ],
)
def test_merge_problems(doc: DocIR, d: Draft, final: bool, msg: str) -> None:
    problems = graph.merge(doc, {}, [], d, final)[2]
    assert len(problems) == 1
    assert msg in problems[0]


def test_merge_partial_without_key(doc: DocIR) -> None:
    assert graph.merge(doc, {}, [], Draft(nodes=[nd("a")], edges=[]), False)[2] == []


def test_run_repairs_and_caches(store: Store, doc: DocIR) -> None:
    bad = Draft(nodes=[nd("a", key=True)], edges=[ed("a", "z")])
    good = Draft(nodes=[nd("a", key=True)], edges=[])
    fake = Fake(bad, good)
    kg, usage = run(doc, store, fake)
    assert [n.id for n in kg.nodes] == ["a"]
    assert usage == Usage(input_tokens=14)
    assert fake.prompts[1].startswith(fake.prompts[0])
    assert "Fix these problems:\n- edge a depends_on z: unknown nodes ['z']" in fake.prompts[1]
    assert run(doc, store, Fake()) == (kg, Usage())


def test_run_gives_up(store: Store, doc: DocIR) -> None:
    bad = Draft(nodes=[nd("a")], edges=[])
    with pytest.raises(ExtractError, match=r"blocks b0..b2 invalid after 1 retries"):
        run(doc, store, Fake(bad, bad), retries=1)


def test_run_chunks_share_nodes(store: Store, doc: DocIR, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(draft, "CHARS", 1)
    first = Draft(nodes=[nd("a")], edges=[])
    second = Draft(nodes=[nd("e", "equation", ("b1",), key=True)], edges=[ed("e", "a")])
    third = Draft(nodes=[nd("a", src=("b2",))], edges=[ed("a", "e", "uses")])
    fake = Fake(first, second, third)
    kg, _ = run(doc, store, fake)
    assert "Known nodes:\na (concept): a" in fake.prompts[1]
    assert [(n.id, n.sources) for n in kg.nodes] == [("a", ("b0", "b2")), ("e", ("b1",))]
    assert len(kg.edges) == 2
