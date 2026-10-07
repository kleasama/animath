import pytest

from animath.core.schemas import Block, BlockType, DocIR, Line, Scene, Storyboard, Visual
from animath.eval import formula


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (r"\left( x^{2} \right)\,+\alpha x.", r"(x^2)+\alpha x"),
        (r"\displaystyle a_{i}\quad=b", "a_i = b"),
        (r"\Bigl( a \Bigr) ;", "(a)"),
    ],
)
def test_normalize_equal(a: str, b: str) -> None:
    assert formula.normalize(a) == formula.normalize(b)


def test_normalize_distinct() -> None:
    assert formula.normalize(r"\alpha x") != formula.normalize(r"\alphax")
    assert formula.normalize("x^{ab}") != formula.normalize("x^ab")


@pytest.mark.parametrize(
    ("a", "b", "verdict"),
    [
        ("x^2+2x+1=(x+1)^2", "(x+1)^2=x^2+2x+1", True),
        ("a-b=0", "b-a=0", True),
        (r"\frac{1}{2}\mu(x)", r"\mu(x)/2", True),
        (r"\int_{-1}^{1} p(x)\,dx", r"\int_{-1}^{1} p(x) dx", True),
        ("a+b", "a-b", False),
        ("a=b", "a+b", False),
        (r"a \le b", r"a \le b", True),
        (r"\|r\|", "r", None),
        ("x+", "x", None),
        (r"\mathbf{x}+1", "1+x", True),
    ],
)
def test_equivalent(a: str, b: str, verdict: bool | None) -> None:
    assert formula.equivalent(a, b) is verdict


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
