# ruff: noqa: N803, N806
import numpy as np
import pytest
from pydantic import ValidationError

from animath.core.errors import ComputeError
from animath.numerics.krylov import Cg, ConvDiff, Dlp, Efie, Gmres, Poisson, cg, gmres


def test_gmres_solves_nonsymmetric_with_monotone_residual() -> None:
    A, b = ConvDiff(n=30, peclet=2.0).build()
    t = gmres(A, b, 1e-12, 30)
    np.testing.assert_allclose(t.x, np.linalg.solve(A, b), rtol=1e-9)
    assert np.all(np.diff(t.residual) <= 1e-15)
    assert t.residual[0] == 1.0


def test_gmres_final_ritz_values_are_the_spectrum() -> None:
    A, b = ConvDiff(n=8, peclet=0.5).build()
    t = gmres(A, b + np.arange(8.0), 1e-300, 8)
    last = t.ritz[t.ritz_k == t.residual.size - 1]
    assert last.size == 8
    np.testing.assert_allclose(
        np.sort_complex(last), np.sort_complex(np.linalg.eigvals(A)), atol=1e-10
    )
    assert np.array_equal(np.unique(t.ritz_k), np.arange(1, 9))


def test_gmres_zero_pivot_and_happy_breakdown() -> None:
    t = gmres(np.array([[0.0, 1.0], [1.0, 0.0]]), np.array([1.0, 0.0]), 1e-12, 10)
    np.testing.assert_allclose(t.x, [0.0, 1.0], atol=1e-15)
    np.testing.assert_allclose(t.residual, [1.0, 1.0, 0.0], atol=1e-15)


def test_gmres_kernel_on_complex_efie() -> None:
    arrays, meta = Gmres(operator=Efie(ka=2.0, n=40), tol=1e-10).run()
    assert meta["converged"] is True
    assert isinstance(meta["true_residual"], float)
    assert meta["true_residual"] < 1e-9
    assert arrays["x"].dtype == np.complex128
    assert arrays["eigs"].size == 40
    assert meta["iterations"] == arrays["residual"].size - 1


def test_second_kind_converges_faster_than_first_kind() -> None:
    first = Gmres(operator=Efie(ka=5.0, n=200), ritz=False).run()[1]["iterations"]
    second = Gmres(operator=Dlp(a=2.0, b=1.0, n=200), ritz=False).run()[1]["iterations"]
    assert isinstance(first, int)
    assert isinstance(second, int)
    assert second < 15 < first


def test_gmres_stops_at_maxiter_without_ritz() -> None:
    arrays, meta = Gmres(operator=ConvDiff(n=64, peclet=1.5), maxiter=5, ritz=False).run()
    assert meta["converged"] is False
    assert meta["iterations"] == 5
    assert "ritz" not in arrays


def test_cg_error_obeys_chebyshev_bound() -> None:
    arrays, meta = Cg(operator=Poisson(n=40)).run()
    assert meta["converged"] is True
    assert np.all(arrays["error_a"] <= arrays["bound"] + 1e-14)
    A, b = Poisson(n=40).build()
    np.testing.assert_allclose(arrays["x"], np.linalg.solve(A, b), rtol=1e-9)
    assert isinstance(meta["kappa"], float)
    assert meta["kappa"] == pytest.approx(np.linalg.cond(A))


def test_cg_terminates_within_n_steps() -> None:
    A, b = Poisson(n=12).build()
    _, res, err = cg(A, b + np.arange(12.0), 1e-13, 100)
    assert res.size - 1 <= 13
    assert err[-1] < 1e-12


@pytest.mark.parametrize(
    "A", [np.array([[2.0, 1.0], [0.0, 2.0]]), np.diag([1.0, -1.0])], ids=["nonsym", "indef"]
)
def test_cg_rejects_non_hpd(A: np.ndarray) -> None:
    with pytest.raises(ComputeError, match="Hermitian positive definite"):
        cg(A, np.ones(2), 1e-10, 10)


def test_operator_discriminator() -> None:
    g = Gmres.model_validate({"operator": {"name": "dlp", "n": 16}})
    assert isinstance(g.operator, Dlp)
    with pytest.raises(ValidationError):
        Gmres.model_validate({"operator": {"name": "laplace3d"}})


def test_cg_stops_at_maxiter() -> None:
    arrays, meta = Cg(operator=Poisson(n=40), maxiter=3).run()
    assert meta["converged"] is False
    assert arrays["residual"].size == 4
