# ruff: noqa: N806
import numpy as np
import pytest
from pydantic import ValidationError

from animath.numerics.kernels import (
    DlpEllipse,
    EfieCylinder,
    dlp_ellipse,
    dlp_kernel,
    efie_cylinder,
    efie_exact,
)


def test_efie_matrix_is_symmetric_and_rhs_is_incident_field() -> None:
    z, v, phi = efie_cylinder(2.0, 40)
    np.testing.assert_allclose(z, z.T, rtol=1e-14)
    np.testing.assert_allclose(np.abs(v), 1.0, rtol=1e-15)
    assert v[0] == pytest.approx(np.exp(-2j), rel=1e-14)
    assert phi[10] == pytest.approx(np.pi / 2)


def test_efie_current_converges_first_order_to_series() -> None:
    e1 = EfieCylinder(ka=1.0, n=60).run()[1]["rel_error"]
    e2 = EfieCylinder(ka=1.0, n=120).run()[1]["rel_error"]
    assert isinstance(e1, float)
    assert isinstance(e2, float)
    assert e2 < 3e-3
    assert e1 / e2 == pytest.approx(2.0, rel=0.05)


def test_exact_current_symmetry_and_shadow() -> None:
    phi = np.array([0.3, 2 * np.pi - 0.3, 0.0, np.pi])
    j = efie_exact(5.0, phi)
    assert j[0] == pytest.approx(j[1], rel=1e-12)
    assert abs(j[3]) > 5 * abs(j[2])  # lit side at phi = pi for incidence along +x


def test_efie_sampling_rule() -> None:
    with pytest.raises(ValidationError, match="10 cells per wavelength"):
        EfieCylinder(ka=5.0, n=40)


def test_dlp_gauss_lemma() -> None:
    A, _, _, _ = dlp_ellipse(3.0, 1.0, 64)
    np.testing.assert_allclose(A @ np.ones(64), -1.0, atol=1e-12)


def test_dlp_circle_is_rank_one_update() -> None:
    A, _, nu, w = dlp_ellipse(2.0, 2.0, 16)
    np.testing.assert_allclose(A, -0.5 * np.eye(16) - np.full((16, 16), 1.0 / 32), atol=1e-14)
    np.testing.assert_allclose(w, np.pi / 4, rtol=1e-14)
    np.testing.assert_allclose(np.linalg.norm(nu, axis=1), 1.0, rtol=1e-15)


def test_dlp_kernel_vanishes_on_coincident_points() -> None:
    y = np.array([[1.0, 0.0], [0.0, 1.0]])
    k = dlp_kernel(y, y, y)
    assert k[0, 0] == 0.0
    assert k[0, 1] == pytest.approx(-1.0 / (4 * np.pi), rel=1e-15)


def test_dlp_nystrom_converges_exponentially() -> None:
    arrays, meta = DlpEllipse(n_max=96).run()
    err = arrays["error"]
    np.testing.assert_array_equal(arrays["n"], np.arange(8, 97, 8))
    assert err[-1] < 1e-14
    assert err[3] < 1e-5
    assert err[6] < 1e-4 * err[2]
    assert arrays["density"].shape == arrays["t"].shape == (96,)
    assert meta == {"target": [0.5, 0.25]}
