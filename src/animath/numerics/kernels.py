# ruff: noqa: N806
from typing import Self

import numpy as np
from pydantic import Field, model_validator
from scipy.special import hankel2

from animath.core.schemas import Model
from animath.numerics.base import C128, F64, Kernel, Result

ETA0 = 376.730313412
K0 = 2.0 * np.pi


def efie_cylinder(ka: float, n: int) -> tuple[C128, C128, F64]:
    """TM EFIE on a PEC circular cylinder, pulse basis, point matching (lambda = 1).

    Returns Z, V and the match angles phi; Z I = V with V = E_z^inc = exp(-j k x).
    """
    a = ka / K0
    phi = 2.0 * np.pi * np.arange(n) / n
    p = a * np.stack((np.cos(phi), np.sin(phi)), axis=-1)
    w = 2.0 * np.pi * a / n
    r = np.linalg.norm(p[:, None] - p[None], axis=-1) + np.eye(n)
    z = K0 * ETA0 * w / 4.0 * hankel2(0, K0 * r)
    gamma = np.exp(np.euler_gamma)
    diag = 1.0 - 2j / np.pi * np.log(gamma * K0 * w / (4.0 * np.e))
    np.fill_diagonal(z, K0 * ETA0 * w / 4.0 * diag)
    return z, np.exp(-1j * K0 * p[:, 0]), phi


def efie_exact(ka: float, phi: F64) -> C128:
    """Surface current of the PEC cylinder under the unit TM plane wave (eigenfunction series)."""
    m = np.arange(-int(ka + 4.0 * ka ** (1 / 3) + 10), int(ka + 4.0 * ka ** (1 / 3) + 10) + 1)
    terms = (1j ** (-m) / hankel2(m, ka))[None] * np.exp(1j * np.outer(phi, m))
    return 2.0 / (np.pi * ETA0 * ka) * terms.sum(axis=1)


def dlp_ellipse(a: float, b: float, n: int) -> tuple[F64, F64, F64, F64]:
    """Nystrom matrix of -I/2 + K (interior Dirichlet, double layer) on an ellipse, trapezoid rule.

    Returns A, nodes y (n, 2), unit outward normals (n, 2), weights.
    """
    t = 2.0 * np.pi * np.arange(n) / n
    y = np.stack((a * np.cos(t), b * np.sin(t)), axis=-1)
    s = np.hypot(a * np.sin(t), b * np.cos(t))
    nu = np.stack((b * np.cos(t), a * np.sin(t)), axis=-1) / s[:, None]
    w = 2.0 * np.pi / n * s
    k = dlp_kernel(y, y, nu)
    np.fill_diagonal(k, -a * b / s**3 / (4.0 * np.pi))
    return k * w[None] - 0.5 * np.eye(n), y, nu, w


def dlp_kernel(x: F64, y: F64, nu: F64) -> F64:
    """d/dnu_y of -(1/2pi) log|x - y| for targets x (m, 2), sources y (n, 2); 0 where x = y."""
    d = x[:, None] - y[None]
    r2 = np.sum(d * d, axis=-1)
    num = np.sum(d * nu[None], axis=-1)
    return np.divide(num, 2.0 * np.pi * r2, out=np.zeros_like(r2), where=r2 > 0)


def harmonic(x: F64) -> F64:
    """u = Re exp(z), z = x_1 + i x_2."""
    return np.exp(x[..., 0]) * np.cos(x[..., 1])


class Cylinder(Model):
    """PEC cylinder of electrical radius ka, n cells, at least 10 cells per wavelength."""

    ka: float = Field(gt=0, le=50)
    n: int = Field(ge=8, le=2048)

    @model_validator(mode="after")
    def _sampling(self) -> Self:
        if self.n < 10.0 * self.ka:
            raise ValueError("need n >= 10 ka (10 cells per wavelength)")
        return self


class EfieCylinder(Cylinder, Kernel):
    """MoM surface current vs. the exact series."""

    def run(self) -> Result:
        z, v, phi = efie_cylinder(self.ka, self.n)
        j = np.linalg.solve(z, v)
        exact = efie_exact(self.ka, phi)
        err = float(np.linalg.norm(j - exact) / np.linalg.norm(exact))
        return {"phi": phi, "current": j, "exact": exact}, {"rel_error": err}


class Ellipse(Model):
    a: float = Field(2.0, gt=0, le=10)
    b: float = Field(1.0, gt=0, le=10)

    @property
    def target(self) -> F64:
        return np.array([[self.a / 4.0, self.b / 4.0]])


class DlpEllipse(Ellipse, Kernel):
    """Nystrom error at an interior point for n = 8, 16, ..., n_max; density at n_max."""

    n_max: int = Field(64, ge=8, le=1024)

    def solve(self, n: int) -> tuple[F64, float]:
        A, y, nu, w = dlp_ellipse(self.a, self.b, n)
        mu = np.linalg.solve(A, harmonic(y))
        u = float(((dlp_kernel(self.target, y, nu) * w[None]) @ mu)[0])
        return mu, abs(u - float(harmonic(self.target)[0]))

    def run(self) -> Result:
        n = np.arange(8, self.n_max + 1, 8)
        err = np.array([self.solve(int(m))[1] for m in n])
        mu, _ = self.solve(int(n[-1]))
        t = 2.0 * np.pi * np.arange(n[-1]) / n[-1]
        return {"n": n, "error": err, "t": t, "density": mu}, {"target": self.target[0].tolist()}
