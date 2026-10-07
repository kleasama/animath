# ruff: noqa: RUF001
import pytest

from animath.narrate.written import script, written


@pytest.mark.parametrize(
    ("tex", "out"),
    [
        (r"L_{21}", "L₂₁"),
        (r"D_{RR}", "D_RR"),
        (r"\mathcal N(t)", "𝒩(t)"),
        (r"\epsilon_L/u", "ε_L/u"),
        (r"\chi/(1-\chi)", "χ/(1−χ)"),
        (r"\mathcal{H}^2", "ℋ²"),
        (r"\|A^{-1}\|_2", "‖A⁻¹‖₂"),
        (r"Q_t^*", "Qₜ*"),
        (r"x^2+\frac{1}{2}", "x²+1/2"),
        (r"\frac{a+b}{2}", "(a+b)/2"),
        (r"\mathbf{Z}\mathbf{I}=\mathbf{V}", "ZI = V"),
        (r"U_t^{\mathrm{aug}}", "Uₜ^aug"),
        (r"O(N \log N)", "O(N log N)"),
        (r"\max_{i} x_i", "maxᵢ xᵢ"),
        (r"\lambda_{\max}", "λ_max"),
        (r"\left( \frac{1}{2} \right.", "(1/2"),
        (r"\text{if } x \le 0", "if x ≤ 0"),
        (r"A^\top x = b", "Aᵀx = b"),
        (r"\hat{x}", "x̂"),
        (r"\mathbb{R}^{n \times n}", "ℝ^(n×n)"),
        (r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", "a b; c d"),
        (r"\{1,\dots,n\}", "{1,…,n}"),
        (r"\epsilon_{L,1}", "ε_(L,1)"),
        ("x^", "x^"),
        (r"\sum_{i=1}^{n} a_i \to \infty", "∑ᵢ₌₁ⁿaᵢ → ∞"),
        (r"\log(x) = (a)", "log(x) = (a)"),
        (r"\det (A) \in [0, 1]", "det(A) ∈ [0,1]"),
        ("", ""),
    ],
)
def test_written_form(tex: str, out: str) -> None:
    assert written(tex) == out


@pytest.mark.parametrize(
    ("body", "kind", "out"),
    [
        ("ij", "_", "ᵢⱼ"),
        ("k+1", "_", "ₖ₊₁"),
        ("max", "_", "_max"),
        ("T", "^", "ᵀ"),
        ("Q", "^", "^Q"),
    ],
)
def test_script(body: str, kind: str, out: str) -> None:
    assert script(body, kind) == out
