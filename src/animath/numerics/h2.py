# ruff: noqa: E741, N803, N806
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import count
from math import isqrt
from typing import Any, Literal, NamedTuple, Self

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator
from scipy.linalg import (
    get_blas_funcs,
    get_lapack_funcs,
    lu_solve,
    qr,
    solve,
    solve_triangular,
    svdvals,
)

from animath.numerics.base import F64, Kernel, Result

I64 = NDArray[np.int64]
Matrix = NDArray[Any]
LU = tuple[Matrix, NDArray[np.int32]]
GL16 = np.polynomial.legendre.leggauss(16)


def level(t: int) -> int:
    return (t + 1).bit_length() - 1


def nodes(lvl: int) -> range:
    """Clusters of level lvl in breadth-first numbering; children of t are 2t + 1, 2t + 2."""
    return range(2**lvl - 1, 2 ** (lvl + 1) - 1)


class Tree(NamedTuple):
    x: F64
    perm: I64
    lo: F64
    hi: F64
    begin: I64
    size: I64
    depth: int

    def idx(self, t: int) -> I64:
        return np.arange(self.begin[t], self.begin[t] + self.size[t])


def _diam(p: F64) -> float:
    return float(np.linalg.norm(p.max(axis=0) - p.min(axis=0)))


def cluster_tree(x: F64, leaf: int) -> Tree:
    """Balanced binary tree of depth d = min{d : leaf 2^d >= N}: rank-median cuts on the axis
    minimising the larger child diameter (first minimiser); tight bounding boxes."""
    n = len(x)
    if leaf < 2 or not n:
        raise ValueError(f"cluster_tree needs leaf >= 2 and points, got leaf={leaf}, n={n}")
    d = next(k for k in count() if leaf << k >= n)
    begin, size = np.zeros(2 ** (d + 1) - 1, np.int64), np.zeros(2 ** (d + 1) - 1, np.int64)
    perm, size[0] = np.arange(n), n
    for t in range(2**d - 1):
        b, m = begin[t], size[t]
        idx, best, order = perm[b : b + m], np.inf, np.arange(m)
        for q in range(x.shape[1]):
            if np.ptp(x[idx, q]) > 0:
                o = np.argsort(x[idx, q], kind="stable")
                h = max(_diam(x[idx[o[: m // 2]]]), _diam(x[idx[o[m // 2 :]]]))
                if h < best:
                    best, order = h, o
        perm[b : b + m] = idx[order]
        begin[2 * t + 1 : 2 * t + 3] = b, b + m // 2
        size[2 * t + 1 : 2 * t + 3] = m // 2, m - m // 2
    xt = x[perm]
    lo = np.array([xt[b : b + m].min(axis=0) for b, m in zip(begin, size, strict=True)])
    hi = np.array([xt[b : b + m].max(axis=0) for b, m in zip(begin, size, strict=True)])
    return Tree(xt, perm, lo, hi, begin, size, d)


def partition(tree: Tree, eta: float) -> tuple[list[list[int]], list[list[int]]]:
    """Near and far lists, level by level: the children of the parent's near list split into the
    near list of t and its far list, the clusters s with dist > 0 and (h_t + h_s)/2 <= eta dist,
    h being box diameters."""
    h = np.linalg.norm(tree.hi - tree.lo, axis=1)
    near: list[list[int]] = [[0]]
    far: list[list[int]] = [[]]
    for t in range(1, len(h)):
        s = np.array([c for p in near[(t - 1) // 2] for c in (2 * p + 1, 2 * p + 2)])
        gap = np.maximum(0.0, np.maximum(tree.lo[t] - tree.hi[s], tree.lo[s] - tree.hi[t]))
        dist = np.linalg.norm(gap, axis=1)
        adm = (dist > 0) & (0.5 * (h[t] + h[s]) <= eta * dist)
        near.append(s[~adm].tolist())
        far.append(s[adm].tolist())
    return near, far


def colouring(near: list[list[int]], lvl: int) -> dict[int, int]:
    """Greedy colouring of level lvl in tree order; clusters within two near hops differ."""
    col: dict[int, int] = {}
    for t in nodes(lvl):
        used = {col.get(u) for s in near[t] for u in near[s]}
        col[t] = next(c for c in count() if c not in used)
    return col


def schedule(near: list[list[int]], col: dict[int, int]) -> tuple[list[int], list[tuple[int, int]]]:
    """Stage order (colour, then tree order) and the DAG: an edge from every stage to each
    later one within two near hops."""
    order = sorted(col, key=lambda t: (col[t], t))
    pos = {t: i for i, t in enumerate(order)}
    edges = sorted(
        {(pos[u], pos[t]) for t in order for s in near[t] for u in near[s] if pos[u] < pos[t]}
    )
    return order, edges


class Skeleton(NamedTuple):
    """Column ID M[:, R] ~ M[:, S] T; rows and cols apply the shear that zeroes far couplings."""

    S: I64
    R: I64
    T: Matrix

    def rows(self, X: Matrix) -> Matrix:
        Y: Matrix = X[self.R] - _mm(self.T, X[self.S], trans_a=1)
        return Y

    def cols(self, X: Matrix) -> Matrix:
        return self.rows(X.T).T


def triangular(X: Matrix) -> Matrix:
    """R factor of the thin QR of X; X itself when it has no more rows than columns."""
    if len(X) <= X.shape[1]:
        return X
    R: Matrix = qr(X, mode="r", check_finite=False)[0][: X.shape[1]]
    return R


def interpolative(M: Matrix, tol: float) -> tuple[Skeleton, float]:
    """Column ID by pivoted QR M P = Q [R11 R12; 0 R22]: k = #{j : |r_jj| > tol |r_11|},
    T = R11^{-1} R12, residual ||M[:, R] - M[:, S] T||_F = ||R22||_F."""
    n = M.shape[1]
    if not np.any(M):
        return Skeleton(np.zeros(0, np.int64), np.arange(n), np.zeros((0, n), M.dtype)), 0.0
    r, piv = qr(M, mode="r", pivoting=True, check_finite=False)
    diag = np.abs(np.diag(r))
    k = int(np.sum(diag > tol * diag[0]))
    T = solve_triangular(r[:k, :k], r[:k, k:], check_finite=False)
    sk = Skeleton(piv[:k].astype(np.int64), piv[k:].astype(np.int64), T)
    return sk, float(np.linalg.norm(r[k:, k:]))


@dataclass(frozen=True, slots=True)
class Operator:
    """A_ij = w G(|x_i - x_j|), G = exp(i kappa r)/(4 pi r); A_ii = integral of G over the square
    cell of side sqrt(w) centred at x_i, in polar form with 16-point Gauss-Legendre in angle."""

    x: F64
    w: float
    kappa: float
    dtype: type

    @property
    def diag(self) -> complex:
        u, c = GL16
        rho = np.sqrt(self.w) / (2.0 * np.cos(np.pi / 8.0 * (u + 1.0)))
        f = np.expm1(1j * self.kappa * rho) / (1j * self.kappa) if self.kappa else rho
        return complex(c @ f) / 4.0

    def __call__(self, I: I64, J: I64) -> Matrix:
        r = np.linalg.norm(self.x[I][:, None] - self.x[J][None], axis=-1)
        g = np.exp(1j * self.kappa * r) / (4.0 * np.pi * np.where(r > 0, r, 1.0)) * self.w
        if (z := r == 0).any():
            g[z] = self.diag
        return (g if self.kappa else g.real).astype(self.dtype)


class Stage(NamedTuple):
    S: I64
    R: I64
    T: Matrix
    lu: LU
    L21: Matrix
    U12: Matrix
    J: I64


class Factor(NamedTuple):
    stages: list[Stage]
    top: I64
    lu: LU

    def solve(self, g: Matrix) -> Matrix:
        """Forward sweep (shear, eliminate, pivot), dense top, backward sweep in reverse."""
        y = g.astype(np.result_type(g, self.lu[0])).reshape(len(g), -1)
        for s in self.stages:
            y[s.R] -= _mm(s.T, y[s.S], trans_a=1)
            y[s.J] -= _mm(s.L21, y[s.R])
            y[s.R] = _solve(s.lu, y[s.R])
        y[self.top] = _solve(self.lu, y[self.top])
        for s in reversed(self.stages):
            y[s.R] -= _mm(s.U12, y[s.J])
            y[s.S] -= _mm(s.T, y[s.R])
        return y.reshape(g.shape)


class Trace(NamedTuple):
    stage: list[list[int]]
    norm: list[list[float]]
    dof: list[I64]
    schur: list[list[int]]
    schur_norm: list[float]
    fill: list[list[int]]
    fill_norm: list[float]
    active: list[list[int]]
    dag: list[tuple[int, int]]


def factorise(
    A: Callable[[I64, I64], Matrix],
    tree: Tree,
    near: list[list[int]],
    far: list[list[int]],
    tol: float,
) -> tuple[Factor, Trace]:
    """Strong recursive skeletonisation: per level, in colour order, ID of the far field of each
    cluster, shear by T, zero the cross blocks, block LU of the redundant part against the
    retained neighbourhood; coarsen to the parents; dense LU of the top level."""
    d = tree.depth
    top = max(0, min((level(t) for t, f in enumerate(far) if f), default=d + 1) - 1)
    nset = [set(x) for x in near]
    act = {t: tree.idx(t) for t in nodes(d)}
    D = {(t, s): A(act[t], act[s]) for t in nodes(d) for s in near[t]}
    Phi: dict[tuple[int, int], Matrix] = {}
    tr = Trace([], [], [], [], [], [], [], [], [])
    stages: list[Stage] = []
    for lvl in range(d, top, -1):
        tr.active.append([lvl, sum(len(act[t]) for t in nodes(lvl))])
        for (a, b), blk in sorted(Phi.items()):
            tr.fill.append([lvl, a, b])
            tr.fill_norm.append(float(np.linalg.norm(blk)))
        col = colouring(near, lvl)
        order, edges = schedule(near, col)
        tr.dag.extend([(len(stages) + a, len(stages) + b) for a, b in edges])
        for t in order:
            B, nb = act[t], [s for s in near[t] if s != t]
            fc = [s for s in nodes(lvl) if s not in nset[t]]
            Dtt, z = D[t, t], np.zeros((len(B), 0), D[t, t].dtype)
            Kbf = np.hstack([z] + [A(B, act[s]) + Phi.get((t, s), 0) for s in fc])
            Kfb = np.vstack([z.T] + [A(act[s], B) + Phi.get((s, t), 0) for s in fc])
            Rbf, Rfb = triangular(Kbf.T), triangular(Kfb)
            sk, cross = interpolative(np.vstack([Rfb, Rbf]), tol)
            Si, Ri = sk.S, sk.R
            ARJ = np.hstack([sk.rows(Dtt[:, Si])] + [sk.rows(D[t, s]) for s in nb])
            AJR = np.vstack([sk.cols(Dtt[Si])] + [sk.cols(D[s, t]) for s in nb])
            lu = _lu(sk.rows(sk.cols(Dtt)))
            L21 = _solve(lu, AJR.T, trans=1).T
            J = np.concatenate([B[Si]] + [act[s] for s in nb])
            stages.append(Stage(B[Si], B[Ri], sk.T, lu, L21, _solve(lu, ARJ), J))
            k, r, j = len(Si), len(Ri), len(J)
            tr.stage.append([t, lvl, col[t], len(B), k, r, j])
            tr.norm.append([_norm2(Rbf), _norm2(Rfb), cross])
            tr.dof.append(np.concatenate([B[Si], B[Ri]]))
            for s in near[t]:
                D[t, s] = D[t, s][Si]
                D[s, t] = D[s, t][:, Si]
            for a, b in [x for x in Phi if t in x]:
                Phi[a, b] = Phi[a, b][Si] if a == t else Phi[a, b][:, Si]
            act[t] = B[Si]
            off = np.cumsum([0, k] + [len(act[s]) for s in nb])
            ids, SC = [t, *nb], _mm(L21, ARJ, -1.0)
            for i, a in enumerate(ids):
                for jj, b in enumerate(ids):
                    dK = SC[off[i] : off[i + 1], off[jj] : off[jj + 1]]
                    fill = b not in nset[a]
                    if fill:
                        Phi[a, b] = Phi.get((a, b), 0) + dK
                    else:
                        D[a, b] += dK
                    tr.schur.append([len(stages) - 1, a, b, int(fill)])
                    tr.schur_norm.append(float(np.linalg.norm(dK)))
        D, Phi = _coarsen(A, lvl, act, near, nset, D, Phi)
    idx = np.concatenate([act[t] for t in nodes(top)])
    K = np.block([[D[t, s] for s in nodes(top)] for t in nodes(top)])
    tr.active.append([top, len(idx)])
    return Factor(stages, idx, _lu(K)), tr


def _coarsen(
    A: Callable[[I64, I64], Matrix],
    lvl: int,
    act: dict[int, I64],
    near: list[list[int]],
    nset: list[set[int]],
    D: dict[tuple[int, int], Matrix],
    Phi: dict[tuple[int, int], Matrix],
) -> tuple[dict[tuple[int, int], Matrix], dict[tuple[int, int], Matrix]]:
    """Parents take their children's skeletons; near parent blocks are assembled from the child
    blocks, terminal far child pairs entering densely (with their fill); other fill moves up."""
    for p in nodes(lvl - 1):
        act[p] = np.concatenate([act[2 * p + 1], act[2 * p + 2]])

    def child(a: int, b: int) -> Matrix:
        return D[a, b] if b in nset[a] else A(act[a], act[b]) + Phi.pop((a, b), 0)

    D2 = {
        (p, q): np.block(
            [[child(a, b) for b in (2 * q + 1, 2 * q + 2)] for a in (2 * p + 1, 2 * p + 2)]
        )
        for p in nodes(lvl - 1)
        for q in near[p]
    }
    Phi2: dict[tuple[int, int], Matrix] = {}
    for (a, b), blk in Phi.items():
        p, q = (a - 1) // 2, (b - 1) // 2
        blk2 = Phi2.setdefault((p, q), np.zeros((len(act[p]), len(act[q])), blk.dtype))
        i0 = 0 if a % 2 else len(act[a - 1])
        j0 = 0 if b % 2 else len(act[b - 1])
        blk2[i0 : i0 + blk.shape[0], j0 : j0 + blk.shape[1]] += blk
    return D2, Phi2


def _mm(a: Matrix, b: Matrix, alpha: float = 1.0, trans_a: int = 0) -> Matrix:
    """alpha op(a) b through scipy's BLAS, the pool its LAPACK calls use."""
    C: Matrix = get_blas_funcs("gemm", (a, b))(alpha, a, b, trans_a=trans_a)
    return C


def _lu(M: Matrix) -> LU:
    if not M.size:
        return M, np.zeros(0, np.int32)
    lu, piv, info = get_lapack_funcs("getrf", (M,))(M)
    if info or not np.all(np.isfinite(lu)):
        raise np.linalg.LinAlgError("singular pivot block")
    return lu, piv


def _solve(lu: LU, b: Matrix, trans: Literal[0, 1] = 0) -> Matrix:
    return lu_solve(lu, b, trans=trans) if len(b) else b


def _norm2(X: Matrix) -> float:
    return float(max(svdvals(X), default=0.0))


def points(geometry: Literal["plate", "sphere"], n: int) -> tuple[F64, float]:
    """n points and their cell measure: a sqrt(n) x sqrt(n) grid on the unit square, or a
    Fibonacci lattice on the sphere of radius 1/2 centred in the unit cube."""
    if geometry == "plate":
        g = (np.arange(isqrt(n)) + 0.5) / isqrt(n)
        return np.stack(np.meshgrid(g, g), axis=-1).reshape(-1, 2), 1.0 / n
    i = np.arange(n) + 0.5
    z, phi = 1.0 - 2.0 * i / n, np.pi * (3.0 - np.sqrt(5.0)) * i
    rho = np.sqrt(1.0 - z**2)
    return 0.5 + 0.5 * np.stack((rho * np.cos(phi), rho * np.sin(phi), z), axis=-1), np.pi / n


def _csr(lists: Sequence[Sequence[int] | I64]) -> tuple[I64, I64]:
    ptr = np.cumsum([0, *map(len, lists)], dtype=np.int64)
    return ptr, np.fromiter((s for x in lists for s in x), np.int64, count=int(ptr[-1]))


def _maxby(key: I64, val: I64) -> dict[int, int]:
    return {int(k): int(val[key == k].max()) for k in np.unique(key)}


class RssLu(Kernel):
    """Strong recursive skeletonisation of A_ij = w exp(i kappa r_ij)/(4 pi r_ij): cluster tree,
    near and far lists, distance-2 colouring, stage DAG, elimination trace, solve error."""

    geometry: Literal["plate", "sphere"] = "plate"
    n: int = Field(4096, ge=16, le=4096)
    leaf: int = Field(64, ge=2, le=1024)
    eta: float = Field(2.5, gt=0, le=10)
    kappa: float = Field(2.0 * np.pi, ge=0, le=100)
    tol: float = Field(1e-5, ge=1e-12, lt=1)
    precision: Literal["single", "double"] = "single"
    seed: int = Field(0, ge=0)

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.geometry == "plate" and isqrt(self.n) ** 2 != self.n:
            raise ValueError("a plate needs n = m^2 points")
        eps = np.finfo(np.float32 if self.precision == "single" else np.float64).eps
        if self.tol < 10 * eps:
            raise ValueError(f"tol < 10 eps = {10 * eps:.1e} of {self.precision} precision")
        return self

    def run(self) -> Result:
        x, w = points(self.geometry, self.n)
        tree = cluster_tree(x, self.leaf)
        near, far = partition(tree, self.eta)
        dt = (np.complex128, np.complex64) if self.kappa else (np.float64, np.float32)
        A = Operator(tree.x, w, self.kappa, dt[self.precision == "single"])
        fac, tr = factorise(A, tree, near, far, self.tol)
        ref, ix = replace(A, dtype=np.complex128), np.arange(self.n)
        M = np.empty((self.n, self.n), np.complex128)
        for i in np.array_split(ix, -(-self.n // 512)):
            M[i] = ref(i, ix)
        rng = np.random.default_rng(self.seed)
        g = rng.standard_normal(self.n) + 1j * rng.standard_normal(self.n)
        y = solve(M, g, overwrite_a=True, check_finite=False)
        err = float(np.linalg.norm(fac.solve(g) - y) / np.linalg.norm(y))
        stage = np.array(tr.stage, np.int64).reshape(-1, 7)
        arrays = {
            "points": tree.x,
            "perm": tree.perm,
            "box": np.stack((tree.lo, tree.hi), axis=1),
            "range": np.stack((tree.begin, tree.begin + tree.size), axis=1),
            "stage": stage,
            "stage_norm": np.array(tr.norm, np.float64).reshape(-1, 3),
            "dag": np.array(tr.dag, np.int64).reshape(-1, 2),
            "schur": np.array(tr.schur, np.int64).reshape(-1, 4),
            "schur_norm": np.array(tr.schur_norm, np.float64),
            "fill": np.array(tr.fill, np.int64).reshape(-1, 3),
            "fill_norm": np.array(tr.fill_norm, np.float64),
            "active": np.array(tr.active, np.int64),
            "top": fac.top,
        }
        for name, lists in (("near", near), ("far", far), ("dof", tr.dof)):
            arrays[f"{name}_ptr"], arrays[name] = _csr(lists)
        return arrays, {
            "depth": tree.depth,
            "top_level": tr.active[-1][0],
            "top_size": tr.active[-1][1],
            "colours": {str(l): int(c) + 1 for l, c in _maxby(stage[:, 1], stage[:, 2]).items()},
            "stages": len(stage),
            "error": err,
        }
