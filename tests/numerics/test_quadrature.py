from math import factorial

import numpy as np
import pytest
from pydantic import ValidationError

from animath.numerics.quadrature import Convergence, Rule, gauss, gauss_legendre, simpson, trapezoid


@pytest.mark.parametrize("n", [1, 2, 5, 20, 64])
def test_golub_welsch_matches_newton_nodes(n: int) -> None:
    x, w = gauss_legendre(n)
    xr, wr = np.polynomial.legendre.leggauss(n)
    np.testing.assert_allclose(x, xr, atol=1e-14)
    np.testing.assert_allclose(w, wr, atol=1e-14)


@pytest.mark.parametrize("n", [1, 3, 8])
def test_gauss_exact_to_degree_2n_minus_1_with_known_remainder(n: int) -> None:
    def q(k: int) -> float:
        return gauss(lambda x: x**k, 0.0, 1.0, n) - 1.0 / (k + 1)

    assert max(abs(q(k)) for k in range(2 * n)) < 1e-15
    remainder = factorial(n) ** 4 / ((2 * n + 1) * factorial(2 * n) ** 2)
    assert q(2 * n) == pytest.approx(-remainder, rel=1e-5)


def test_newton_cotes_exactness() -> None:
    assert trapezoid(lambda x: 3 * x + 1, 0.0, 2.0, 2) == pytest.approx(8.0, rel=1e-15)
    assert simpson(lambda x: x**3, 0.0, 2.0, 3) == pytest.approx(4.0, rel=1e-15)
    assert simpson(lambda x: x**4, 0.0, 2.0, 3) != pytest.approx(6.4, rel=1e-3)
    with pytest.raises(ValueError, match="odd"):
        simpson(np.exp, 0.0, 1.0, 4)


def test_rule_maps_to_interval() -> None:
    arrays, meta = Rule(n=6, a=0.0, b=3.0).run()
    assert meta == {"degree": 11}
    assert arrays["weights"].sum() == pytest.approx(3.0, rel=1e-14)
    assert np.all((arrays["nodes"] > 0.0) & (arrays["nodes"] < 3.0))
    assert arrays["weights"] @ arrays["nodes"] ** 2 == pytest.approx(9.0, rel=1e-14)


def test_convergence_rates() -> None:
    arrays, meta = Convergence(integrand="exp", n_max=33).run()
    assert meta["exact"] == pytest.approx(np.e - 1 / np.e, rel=1e-15)
    np.testing.assert_array_equal(arrays["n"], np.arange(3, 34, 2))
    assert arrays["gauss"][4] < 1e-14
    h = 2.0 / (arrays["n"] - 1)
    np.testing.assert_allclose(arrays["trapezoid"] / h**2, (np.e - 1 / np.e) / 12, rtol=0.05)
    np.testing.assert_allclose(
        arrays["simpson"][5:] / h[5:] ** 4, (np.e - 1 / np.e) / 180, rtol=0.05
    )


def test_nonsmooth_integrand_converges_algebraically() -> None:
    arrays, _ = Convergence(integrand="abs", a=-1.0, b=2.0, n_max=101).run()
    assert 1e-6 < arrays["gauss"][-1] < 1e-3


@pytest.mark.parametrize(
    "params",
    [
        {"n": 3, "a": 1.0, "b": 1.0},
        {"n": 3, "a": float("nan")},
        {"n": 0},
        {"n": 3, "extra": 1},
    ],
)
def test_rule_rejects_invalid(params: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Rule.model_validate(params)


def test_convergence_rejects_unknown_integrand() -> None:
    with pytest.raises(ValidationError):
        Convergence.model_validate({"integrand": "sin", "n_max": 5})
