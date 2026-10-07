from pydantic import BaseModel

from animath.core.schemas import Block, BlockType, DocIR, Node, NodeKind, Relation

CHARS = 40_000
SYSTEM = """Extract the knowledge graph of the given blocks of a mathematical document.
- Node kinds: concept (defined notion), symbol (notation), equation (one display), result
  (theorem, lemma, proposition, corollary), algorithm.
- id: short lowercase slug of [a-z0-9_-]; reuse a known id for the same entity.
- name: a few words. latex: the symbol or the display, null for concepts and results.
  meaning: one sentence; required for symbols.
- sources: ids of the blocks that state or define the node.
- An equation node is one equation block; its latex is that block's latex.
- key: true only for the few results, equations and algorithms a short video must cover.
- Edges: a depends_on b if a cannot be understood before b; a defines b if a introduces
  symbol or concept b; a uses b if a refers to b otherwise. depends_on is acyclic.
- Edges may reference known nodes. Omit citations, formatting and trivial notation."""


class DNode(BaseModel):
    id: str
    kind: NodeKind
    name: str
    latex: str | None
    meaning: str | None
    key: bool
    sources: list[str]


class DEdge(BaseModel):
    src: str
    dst: str
    rel: Relation


class Draft(BaseModel):
    nodes: list[DNode]
    edges: list[DEdge]


def line(b: Block) -> str:
    tag = " ".join(x for x in (b.id, b.type, b.env, b.label) if x)
    return f"[{tag}] {b.latex if b.type is BlockType.EQUATION else b.text}"


def chunks(blocks: tuple[Block, ...], chars: int) -> list[list[Block]]:
    """Sections (heading to heading) packed greedily into chunks of at most `chars` characters;
    a longer section is packed block by block, a longer block stands alone."""
    secs: list[list[Block]] = []
    for b in blocks:
        if not secs or b.type is BlockType.HEADING:
            secs.append([])
        secs[-1].append(b)
    out: list[list[Block]] = [[]]
    size = 0
    for s in secs:
        n = sum(len(line(b)) + 1 for b in s)
        for u in ([b] for b in s) if n > chars else [s]:
            m = sum(len(line(b)) + 1 for b in u)
            if out[-1] and size + m > chars:
                out.append([])
                size = 0
            out[-1] += u
            size += m
    return out


def prompt(doc: DocIR, part: list[Block], known: list[Node]) -> str:
    head = [f"Document: {doc.title}"]
    if doc.macros:
        head += ["Macros:", *doc.macros.values()]
    if known:
        head += ["Known nodes:", *(f"{n.id} ({n.kind}): {n.name}" for n in known)]
    return "\n".join([*head, "Blocks:", *map(line, part)])
