import pytest

from animath.core.schemas import Block, BlockType, DocIR, Line, Scene, Storyboard, Visual
from animath.eval import formula


def doc(*eqs: tuple[str | None, str]) -> DocIR:
    return DocIR(
        title="t",
        blocks=tuple(
            Block(id=f"b{i}", type=BlockType.EQUATION, label=lab, latex=tex)
            for i, (lab, tex) in enumerate(eqs)
        ),
    )


def test_fidelity() -> None:
    want = doc(("e1", "a=b"), (None, "x^2"), ("e3", "c+d"))
    assert formula.fidelity(want, doc(("e1", "a = b"), (None, "x^{2}"), ("e3", "c+d"))) == (1.0, [])
    q, bad = formula.fidelity(want, doc(("e1", "b=a"), (None, "y")))
    assert q == pytest.approx(0.0)
    assert bad == [
        {"equation": "e1", "expected": "a=b", "actual": "b=a", "equivalent": True},
        {"equation": "#1", "expected": "x^2", "actual": "y", "equivalent": False},
        {"equation": "e3", "expected": "c+d", "actual": None, "equivalent": None},
    ]
    assert (
        formula.fidelity(DocIR(title="t", blocks=(Block(id="p", type=BlockType.PARAGRAPH),)), want)[
            0
        ]
        == 1.0
    )


def test_untraced() -> None:
    src = doc(
        ("e", "(a+b)^2"),
    )
    vis = (
        Visual(primitive="equation", args={"latex": "(a + b)^{2}"}),
        Visual(primitive="derive", args={"steps": ["{{(a+b)^2}}", "a^2+2ab+b^2", "q"]}),
        Visual(primitive="equation", args={"latex": 3}),
        Visual(primitive="text", args={"text": "x"}),
    )
    s = Scene(
        id="s",
        goal="g",
        narration=(Line(text="w"),),
        visuals=vis,
        math=("b^2+2ab+a^2", "z"),
        duration_s=1,
    )
    board = Storyboard(title="t", scenes=(s,))
    assert formula.untraced(board, src) == (6, ["z", "q"])


def test_untraced_parts_inline_markers() -> None:
    src = DocIR(
        title="t",
        blocks=(
            Block(id="e", type=BlockType.EQUATION, latex=r"a=\langle f,g\rangle,\quad x=y+z,"),
            Block(id="p", type=BlockType.PARAGRAPH, text=r"Here $G(r,s)=\mathrm e^{r}$ holds."),
        ),
    )
    steps = ["x=y+z", r"\mathbf E^{\mathrm{inc}}", "{{x}}=y+{{z}}"]
    listed = r"\begin{gathered} x=y+z \\ G(r,s)=\mathrm e^{r} \end{gathered}"
    s = Scene(
        id="s",
        goal="g",
        narration=(Line(text="w"),),
        visuals=(Visual(primitive="derive", args={"steps": steps}),),
        math=(
            r"a=\langle f,g\rangle",
            r"G(r,s)=\mathrm{e}^{r}",
            "x=y",
            r"\langle f",
            listed,
            "x=y+z, q",
        ),
        duration_s=1,
    )
    board = Storyboard(title="t", scenes=(s,))
    bad = ["x=y", r"\langle f", "x=y+z, q", r"\mathbf E^{\mathrm{inc}}"]
    assert formula.untraced(board, src) == (9, bad)
