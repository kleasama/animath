from pathlib import Path

import pytest

from animath.core.schemas import (
    Block,
    BlockType,
    DocIR,
    Edge,
    KnowledgeGraph,
    Line,
    Node,
    NodeKind,
    Relation,
    Scene,
    Storyboard,
    Visual,
)
from animath.core.store import Store

H = "0" * 64


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "store")


@pytest.fixture
def doc() -> DocIR:
    return DocIR(
        title="EFIE",
        blocks=(
            Block(id="b0", type=BlockType.HEADING, text="Method of moments", level=1),
            Block(
                id="b1",
                type=BlockType.EQUATION,
                latex=r"\mathbf{Z}\mathbf{I}=\mathbf{V}",
                label="eq:mom",
            ),
            Block(
                id="b2",
                type=BlockType.PARAGRAPH,
                text="By (eq:mom) [harr]",
                refs=("eq:mom", "harr"),
            ),
        ),
        bib={"harr": "R. F. Harrington, Field Computation by Moment Methods, 1968."},
    )


@pytest.fixture
def graph() -> KnowledgeGraph:
    return KnowledgeGraph(
        nodes=(
            Node(
                id="efie",
                kind=NodeKind.EQUATION,
                name="EFIE",
                latex=r"\mathbf{Z}\mathbf{I}=\mathbf{V}",
                sources=("b1",),
            ),
            Node(id="mom", kind=NodeKind.ALGORITHM, name="MoM", key=True, sources=("b1", "b2")),
        ),
        edges=(Edge(src="mom", dst="efie", rel=Relation.DEPENDS_ON),),
    )


@pytest.fixture
def board() -> Storyboard:
    return Storyboard(
        title="MoM",
        scenes=(
            Scene(
                id="s1",
                goal="state the system",
                narration=(Line(text="Discretise.", bookmark="a"), Line(text="Solve.")),
                visuals=(Visual(primitive="equation", args={"latex": "ZI=V"}, at="a"),),
                duration_s=12.5,
            ),
            Scene(id="s2", goal="solve", narration=(Line(text="GMRES."),), duration_s=7.5),
        ),
    )
