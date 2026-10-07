# ruff: noqa: N806
from collections.abc import Callable
from typing import Literal, Self

import numpy as np
from pydantic import Field, model_validator
from scipy.linalg import eigh_tridiagonal

from animath.numerics.base import F64, Kernel, Result

Fn = Callable[[F64], F64]
INTEGRANDS: dict[str, tuple[Fn, Fn]] = {
    "exp": (np.exp, np.exp),
    "runge": (lambda x: 1.0 / (1.0 + 25.0 * x**2), lambda x: np.arctan(5.0 * x) / 5.0),
    "osc": (lambda x: np.cos(10.0 * x), lambda x: np.sin(10.0 * x) / 10.0),
    "abs": (np.abs, lambda x: x * np.abs(x) / 2.0),
}


def gauss_legendre(n: int) -> tuple[F64, F64]:
    """Nodes and weights of the n-point Gauss-Legendre rule on [-1, 1] (Golub-Welsch)."""
    k = np.arange(1.0, n)
    x, v = eigh_tridiagonal(np.zeros(n), k / np.sqrt(4.0 * k**2 - 1.0))
    return x, 2.0 * v[0] ** 2


def gauss(f: Fn, a: float, b: float, n: int) -> float:
    x, w = gauss_legendre(n)
    h = (b - a) / 2.0
    return h * float(w @ f(h * x + (a + b) / 2.0))


def trapezoid(f: Fn, a: float, b: float, n: int) -> float:
    y = f(np.linspace(a, b, n))
    return (b - a) / (n - 1) * float(y.sum() - (y[0] + y[-1]) / 2.0)


def simpson(f: Fn, a: float, b: float, n: int) -> float:
    if n % 2 == 0:
        raise ValueError("Simpson's rule needs an odd number of points")
    y = f(np.linspace(a, b, n))
    return (
        (b - a) / (3.0 * (n - 1)) * float(y[0] + y[-1] + 4 * y[1:-1:2].sum() + 2 * y[2:-1:2].sum())
    )


RULES = {"gauss": gauss, "trapezoid": trapezoid, "simpson": simpson}


class Interval(Kernel):
    a: float = -1.0
    b: float = 1.0

    @model_validator(mode="after")
    def _order(self) -> Self:
        if not self.a < self.b:
            raise ValueError("need a < b")
        return self


class Rule(Interval):
    """Gauss-Legendre nodes and weights on [a, b]."""

    n: int = Field(ge=1, le=512)

    def run(self) -> Result:
        x, w = gauss_legendre(self.n)
        h = (self.b - self.a) / 2.0
        return {"nodes": h * x + (self.a + self.b) / 2.0, "weights": h * w}, {
            "degree": 2 * self.n - 1
        }


class Convergence(Interval):
    """Absolute errors of Gauss, trapezoid and Simpson rules with n = 3, 5, ..., n_max points."""

    integrand: Literal["exp", "runge", "osc", "abs"]
    n_max: int = Field(ge=3, le=513)

    def run(self) -> Result:
        f, F = INTEGRANDS[self.integrand]
        exact = float(np.diff(F(np.array([self.a, self.b])))[0])
        n = np.arange(3, self.n_max + 1, 2)
        err = {
            name: np.array([abs(q(f, self.a, self.b, int(m)) - exact) for m in n])
            for name, q in RULES.items()
        }
        return {"n": n, **err}, {"exact": exact}
