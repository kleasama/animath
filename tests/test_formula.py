import pytest

from animath.core import formula
from animath.core.schemas import Line, Scene, Visual


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (r"\left( x^{2} \right)\,+\alpha x.", r"(x^2)+\alpha x"),
        (r"\displaystyle a_{i}\quad=b", "a_i = b"),
        (r"\Bigl( a \Bigr) ;", "(a)"),
        (r"\mathrm{d}x", r"\mathrm dx"),
        (r"\frac{1}{\sqrt{3}}", r"\frac1{\sqrt3}"),
        (r"a &= b", "a = b"),
        (r"s_{i}\,Z\;t\!u", "s_i Z t u"),
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


@pytest.mark.parametrize(
    ("tex", "items"),
    [
        ("a, b;c", ["a", "b", "c"]),
        ("x=y+z,", ["x = y + z"]),
        (r"\langle f,g\rangle", []),
        (r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}", []),
        (r"\begin{gathered} x=y \\[2pt] z \end{gathered}", ["x = y", "[ 2 p t ] z"]),
        (r"\begin{aligned} a &= b \end{aligned}", ["a = b"]),
        ("x", []),
    ],
)
def test_parts(tex: str, items: list[str]) -> None:
    assert formula.parts(tex) == items


REFS = ["x=y+z", r"\mathbf Z\mathbf I=\mathbf V", r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}"]


@pytest.mark.parametrize(
    ("f", "prev", "verdict"),
    [
        (r"\begin{gathered} x = y+z \\ \mathbf{Z}\mathbf{I}=\mathbf{V} \end{gathered}", None, True),
        (r"x=y+z,\quad q", None, False),
        (r"\begin{bmatrix}a&b\\c&d\end{bmatrix}", None, True),
        (r"\begin{bmatrix}a&b\end{bmatrix}", None, False),
        ("y+z=x", None, True),
        ("x-y=w", "x-y=z", False),
        ("x-w=y", "x=y+w", True),
        ("x=2", "x=y+z", False),
    ],
)
def test_traced(f: str, prev: str | None, verdict: bool) -> None:
    assert formula.traced(f, prev, REFS) is verdict


def test_traced_item_with_control_symbol() -> None:
    ref = r"A_{ij}=s_{\pi(i)}\,Z_{\pi(i)\pi(j)}\,s_{\pi(j)}"
    f = rf"\begin{{gathered}}|A_{{ii}}|=1\\ {ref}\end{{gathered}}"
    assert formula.traced(f, None, [ref, "|A_{ii}|=1"])


def test_untraced_scene() -> None:
    vis = (
        Visual(primitive="derive", args={"steps": ["{{x}}=y+{{z}}", "x-y=z", "w"]}),
        Visual(primitive="equation", args={"latex": 3}),
        Visual(primitive="text", args={"text": "q"}),
    )
    s = Scene(id="s", goal="g", narration=(Line(text="w"),), visuals=vis, math=("q",), duration_s=1)
    assert formula.on_screen(s) == [["q"], ["x=y+z", "x-y=z", "w"]]
    assert formula.untraced(s, REFS) == ["q", "w"]
