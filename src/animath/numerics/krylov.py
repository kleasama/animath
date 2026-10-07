# ruff: noqa: N803, N806
from typing import Annotated, Any, Literal, NamedTuple

import numpy as np
from numpy.typing import NDArray
from pydantic import Field
from scipy.linalg import solve_triangular

from animath.core.errors import ComputeError
from animath.core.schemas import Model
from animath.numerics.base import C128, F64, Kernel, Result
from animath.numerics.kernels import Cylinder, Ellipse, dlp_ellipse, efie_cylinder, harmonic

Matrix = NDArray[Any]


class Trace(NamedTuple):
    x: Matrix
    residual: F64
    ritz: C128
    ritz_k: NDArray[np.int64]


def gmres(A: Matrix, b: Matrix, tol: float, maxiter: int, ritz: bool = True) -> Trace:
    """Full GMRES, x_0 = 0: Arnoldi (MGS), Givens QR; relative residuals and Ritz values of H_k."""
    n, m = b.size, min(maxiter, b.size)
    dt = np.result_type(A, b, np.float64)
    beta = float(np.linalg.norm(b))
    V, H = np.zeros((n, m + 1), dt), np.zeros((m + 1, m), dt)
    R, g = np.zeros((m + 1, m), dt), np.zeros(m + 1, dt)
    c, s = np.zeros(m), np.zeros(m, dt)
    V[:, 0], g[0] = b / beta, beta
    res, rv, rk = [1.0], [np.zeros(0, complex)], [np.zeros(0, np.int64)]
    k = 0
    while k < m:
        w = A @ V[:, k]
        scale = np.linalg.norm(w)
        for i in range(k + 1):
            H[i, k] = np.vdot(V[:, i], w)
            w = w - H[i, k] * V[:, i]
        H[k + 1, k] = np.linalg.norm(w)
        if ritz:
            rv.append(np.sort(np.linalg.eigvals(H[: k + 1, : k + 1])))
            rk.append(np.full(k + 1, k + 1, np.int64))
        R[: k + 2, k] = H[: k + 2, k]
        for i in range(k):
            R[i, k], R[i + 1, k] = (
                c[i] * R[i, k] + s[i] * R[i + 1, k],
                -np.conj(s[i]) * R[i, k] + c[i] * R[i + 1, k],
            )
        p, q = R[k, k], R[k + 1, k]
        d = np.hypot(abs(p), abs(q))
        c[k], s[k] = (abs(p) / d, p / abs(p) * np.conj(q) / d) if p else (0.0, 1.0)
        R[k, k], R[k + 1, k] = c[k] * p + s[k] * q, 0.0
        g[k + 1], g[k] = -np.conj(s[k]) * g[k], c[k] * g[k]
        res.append(abs(g[k + 1]) / beta)
        k += 1
        breakdown = abs(H[k, k - 1]) <= 1e-14 * scale
        if res[-1] <= tol or breakdown:
            break
        V[:, k] = w / H[k, k - 1]
    y = solve_triangular(R[:k, :k], g[:k])
    return Trace(
        x=V[:, :k] @ y,
        residual=np.array(res),
        ritz=np.concatenate(rv).astype(complex),
        ritz_k=np.concatenate(rk),
    )


def cg(A: Matrix, b: Matrix, tol: float, maxiter: int) -> tuple[Matrix, F64, F64]:
    """Conjugate gradients, x_0 = 0; relative residuals and relative A-norm errors."""
    if not _hpd(A):
        raise ComputeError("CG needs a Hermitian positive definite operator")
    xs = np.linalg.solve(A, b)
    x, r = np.zeros_like(b), b.copy()
    p, rr, nb = r.copy(), np.vdot(r, r).real, np.linalg.norm(b)
    ea = np.sqrt(np.vdot(xs, A @ xs).real)
    res, err = [1.0], [1.0]
    for _ in range(min(maxiter, b.size)):
        ap = A @ p
        alpha = rr / np.vdot(p, ap).real
        x, r = x + alpha * p, r - alpha * ap
        rr, rr0 = np.vdot(r, r).real, rr
        e = x - xs
        res.append(float(np.sqrt(rr) / nb))
        err.append(float(np.sqrt(abs(np.vdot(e, A @ e))) / ea))
        if res[-1] <= tol:
            break
        p = r + rr / rr0 * p
    return x, np.array(res), np.array(err)


class Poisson(Model):
    """tridiag(-1, 2, -1), b = 1."""

    name: Literal["poisson1d"] = "poisson1d"
    n: int = Field(64, ge=2, le=1024)

    def build(self) -> tuple[Matrix, Matrix]:
        return _tridiag(self.n, -1.0, -1.0), np.ones(self.n)


class ConvDiff(Model):
    """Central differences of -u'' + c u' with cell Peclet number P: tridiag(-1-P, 2, -1+P)."""

    name: Literal["convdiff"] = "convdiff"
    n: int = Field(64, ge=2, le=1024)
    peclet: float = Field(0.5, ge=0, le=100)

    def build(self) -> tuple[Matrix, Matrix]:
        return _tridiag(self.n, -1.0 - self.peclet, -1.0 + self.peclet), np.ones(self.n)


class Efie(Cylinder):
    name: Literal["efie"] = "efie"

    def build(self) -> tuple[Matrix, Matrix]:
        z, v, _ = efie_cylinder(self.ka, self.n)
        return z, v


class Dlp(Ellipse):
    name: Literal["dlp"] = "dlp"
    n: int = Field(64, ge=8, le=1024)

    def build(self) -> tuple[Matrix, Matrix]:
        A, y, _, _ = dlp_ellipse(self.a, self.b, self.n)
        return A, harmonic(y)


def _hpd(A: Matrix) -> bool:
    if not np.allclose(A, A.conj().T, rtol=0.0, atol=1e-13 * np.abs(A).max()):
        return False
    try:
        np.linalg.cholesky(A)
    except np.linalg.LinAlgError:
        return False
    return True


def _tridiag(n: int, lower: float, upper: float) -> Matrix:
    return 2.0 * np.eye(n) + lower * np.eye(n, k=-1) + upper * np.eye(n, k=1)


Operator = Annotated[Poisson | ConvDiff | Efie | Dlp, Field(discriminator="name")]


class Gmres(Kernel):
    """GMRES trace: residual history, Ritz values per step (`ritz_k` = step), spectrum of A."""

    operator: Operator
    tol: float = Field(1e-10, gt=0, lt=1)
    maxiter: int = Field(100, ge=1, le=256)
    ritz: bool = True

    def run(self) -> Result:
        A, b = self.operator.build()
        t = gmres(A, b, self.tol, self.maxiter, self.ritz)
        true = float(np.linalg.norm(b - A @ t.x) / np.linalg.norm(b))
        arrays = {"x": t.x, "residual": t.residual, "eigs": np.sort(np.linalg.eigvals(A))}
        if self.ritz:
            arrays |= {"ritz": t.ritz, "ritz_k": t.ritz_k}
        return arrays, {
            "iterations": t.residual.size - 1,
            "converged": bool(t.residual[-1] <= self.tol),
            "true_residual": true,
        }


class Cg(Kernel):
    """CG trace with the bound 2 ((sqrt(kappa) - 1) / (sqrt(kappa) + 1))^k."""

    operator: Operator
    tol: float = Field(1e-10, gt=0, lt=1)
    maxiter: int = Field(1024, ge=1, le=1024)

    def run(self) -> Result:
        A, b = self.operator.build()
        x, res, err = cg(A, b, self.tol, self.maxiter)
        kappa = float(np.linalg.cond(A))
        q = (np.sqrt(kappa) - 1.0) / (np.sqrt(kappa) + 1.0)
        bound = 2.0 * q ** np.arange(res.size)
        return {"x": x, "residual": res, "error_a": err, "bound": bound}, {
            "kappa": kappa,
            "iterations": res.size - 1,
            "converged": bool(res[-1] <= self.tol),
        }
