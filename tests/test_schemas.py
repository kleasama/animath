import pytest
from pydantic import ValidationError

from animath.core.hashing import canonical, digest, digest_of
from animath.core.schemas import (
    ARTIFACTS,
    Block,
    BlockType,
    DataRequest,
    DataSet,
    DocIR,
    Edge,
    KnowledgeGraph,
    Line,
    Manifest,
    Narration,
    Node,
    NodeKind,
    Params,
    Relation,
    Scene,
    SceneRender,
    SourceBundle,
    SourceFile,
    SourceFormat,
    Storyboard,
    Usage,
    Visual,
    Word,
)
from tests.conftest import H


def test_digest_is_sha256_and_canonical_ignores_key_order() -> None:
    assert digest(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert canonical({"b": 1, "a": [2, "é"]}) == '{"a":[2,"é"],"b":1}'.encode()
    assert digest_of({"x": 1, "y": 2}) == digest_of({"y": 2, "x": 1})


def test_params_bounds() -> None:
    p = Params()
    assert (p.width, p.height, p.fps, p.duration_s) == (1920, 1080, 60, 180.0)
    for bad in ({"width": 1921}, {"duration_s": 0}, {"fps": 240}, {"budget_usd": 0}):
        with pytest.raises(ValidationError):
            Params.model_validate(bad)


def test_models_are_frozen_and_closed() -> None:
    with pytest.raises(ValidationError):
        Params().fps = 30  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Params.model_validate({"colour": "red"})


@pytest.mark.parametrize("path", ["/etc/passwd", "../x.tex", "a/../../b", ""])
def test_source_file_rejects_escaping_paths(path: str) -> None:
    with pytest.raises(ValidationError, match="relative"):
        SourceFile(path=path, blob=H)


def test_source_bundle_entry_and_uniqueness() -> None:
    f = SourceFile(path="main.tex", blob=H)
    assert SourceBundle(format=SourceFormat.LATEX, entry="main.tex", files=(f,)).kind == "source"
    with pytest.raises(ValidationError, match="not among files"):
        SourceBundle(format=SourceFormat.LATEX, entry="ch1.tex", files=(f,))
    with pytest.raises(ValidationError, match="duplicate paths"):
        SourceBundle(format=SourceFormat.LATEX, entry="main.tex", files=(f, f))


def test_block_shape() -> None:
    with pytest.raises(ValidationError, match="lacks latex"):
        Block(id="e", type=BlockType.EQUATION)
    with pytest.raises(ValidationError, match="headings only"):
        Block(id="h", type=BlockType.HEADING)
    with pytest.raises(ValidationError, match="headings only"):
        Block(id="p", type=BlockType.PARAGRAPH, level=2)


def test_doc_refs_resolve_to_labels_or_bib(doc: DocIR) -> None:
    assert len(doc.blocks) == 3
    blocks = list(doc.blocks)
    with pytest.raises(ValidationError, match=r"unresolved refs: \['eq:x'\]"):
        DocIR(
            title="t",
            blocks=(*blocks, Block(id="b3", type=BlockType.LIST, refs=("eq:x",))),
            bib=doc.bib,
        )
    with pytest.raises(ValidationError, match="duplicate block ids"):
        DocIR(title="t", blocks=(blocks[0], blocks[0]))
    dup_label = blocks[1].model_copy(update={"id": "b9"})
    with pytest.raises(ValidationError, match="duplicate labels"):
        DocIR(title="t", blocks=(blocks[1], dup_label))


def test_graph_edges_and_acyclicity(graph: KnowledgeGraph) -> None:
    nodes = graph.nodes
    with pytest.raises(ValidationError, match=r"unknown nodes: \['ghost'\]"):
        KnowledgeGraph(nodes=nodes, edges=(Edge(src="mom", dst="ghost", rel=Relation.USES),))
    back = Edge(src="efie", dst="mom", rel=Relation.DEPENDS_ON)
    with pytest.raises(ValidationError, match=r"cycle among \['efie', 'mom'\]"):
        KnowledgeGraph(nodes=nodes, edges=(*graph.edges, back))
    uses = Edge(src="efie", dst="mom", rel=Relation.USES)
    assert len(KnowledgeGraph(nodes=nodes, edges=(*graph.edges, uses)).edges) == 2
    with pytest.raises(ValidationError):
        Node(id="n", kind=NodeKind.CONCEPT, name="n", sources=())


def test_graph_diamond_is_acyclic() -> None:
    ids = "abcd"
    nodes = tuple(Node(id=i, kind=NodeKind.CONCEPT, name=i, sources=("b",)) for i in ids)
    pairs = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
    edges = tuple(Edge(src=s, dst=d, rel=Relation.DEPENDS_ON) for s, d in pairs)
    assert len(KnowledgeGraph(nodes=nodes, edges=edges).edges) == 4


def test_scene_cues_and_storyboard(board: Storyboard) -> None:
    assert board.duration_s == pytest.approx(20.0)
    line = Line(text="x", bookmark="a")
    with pytest.raises(ValidationError, match="duplicate bookmarks"):
        Scene(id="s", goal="g", narration=(line, line), duration_s=1)
    with pytest.raises(ValidationError, match=r"unknown bookmarks \['b'\]"):
        Scene(
            id="s",
            goal="g",
            narration=(line,),
            visuals=(Visual(primitive="p", at="b"),),
            duration_s=1,
        )
    with pytest.raises(ValidationError, match="duplicate scene ids"):
        Storyboard(title="t", scenes=(board.scenes[0], board.scenes[0]))


def test_data_request_digest_is_order_independent() -> None:
    a = DataRequest(kind="gmres", params={"n": 64, "tol": 1e-8})
    b = DataRequest(kind="gmres", params={"tol": 1e-8, "n": 64})
    assert a.digest == b.digest != DataRequest(kind="gmres", params={"n": 65, "tol": 1e-8}).digest


def test_narration_timeline() -> None:
    words = (Word(text="a", start=0.0, end=0.4), Word(text="b", start=0.5, end=1.0))
    n = Narration(scene_id="s", audio=H, duration_s=1.0, words=words, bookmarks={"m": 0.5})
    assert n.words[-1].end == 1.0
    with pytest.raises(ValidationError, match="ends before"):
        Word(text="x", start=1.0, end=0.5)
    with pytest.raises(ValidationError, match="not monotone"):
        Narration(scene_id="s", audio=H, duration_s=1.0, words=words[::-1])
    with pytest.raises(ValidationError, match="exceed"):
        Narration(scene_id="s", audio=H, duration_s=0.9, words=words)
    with pytest.raises(ValidationError, match="outside"):
        Narration(scene_id="s", audio=H, duration_s=1.0, bookmarks={"m": 1.5})
    with pytest.raises(ValidationError, match="outside"):
        SceneRender(scene_id="s", clip=H, duration_s=2.0, bookmarks={"m": -0.1})


def test_usage_addition() -> None:
    u = Usage(input_tokens=3, output_tokens=5) + Usage(input_tokens=1, cache_read_tokens=7)
    assert u == Usage(input_tokens=4, output_tokens=5, cache_read_tokens=7)


def test_registry_roundtrip(doc: DocIR, graph: KnowledgeGraph, board: Storyboard) -> None:
    samples = [
        SourceBundle(
            format=SourceFormat.MD, entry="a.md", files=(SourceFile(path="a.md", blob=H),)
        ),
        doc,
        graph,
        board,
        DataSet(request=DataRequest(kind="k"), arrays={"x": H}),
        Narration(scene_id="s", audio=H, duration_s=1.0),
        SceneRender(scene_id="s", clip=H, duration_s=1.0),
        Manifest(video=H, subtitles=H, artifacts={"doc": H}),
    ]
    assert sorted(ARTIFACTS) == sorted(type(s).kind for s in samples)
    for s in samples:
        assert ARTIFACTS[s.kind].model_validate_json(s.model_dump_json()) == s
    with pytest.raises(ValidationError):
        DataSet(request=DataRequest(kind="k"), arrays={"x": "abc"})
