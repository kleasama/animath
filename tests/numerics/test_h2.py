# ruff: noqa: E741, N802, N803, N806
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from pydantic import ValidationError
from scipy.integrate import dblquad
from scipy.linalg import solve

from animath.core.schemas import DataRequest
from animath.core.store import Store
from animath.numerics import compute, load
from animath.numerics.h2 import (
    Operator,
    RssLu,
    Tree,
    cluster_tree,
    colouring,
    factorise,
    interpolative,
    level,
    nodes,
    partition,
    points,
    schedule,
    triangular,
)

I64 = NDArray[np.int64]
Lists = list[list[int]]
Entries = Callable[[I64, I64], NDArray[Any]]


def plate(m: int, leaf: int, eta: float = 2.5) -> tuple[Tree, Lists, Lists]:
    tree = cluster_tree(points("plate", m * m)[0], leaf)
    return tree, *partition(tree, eta)


def helmholtz(tree: Tree, dtype: type = np.complex128) -> Operator:
    return Operator(tree.x, 1.0 / len(tree.x), 2 * np.pi, dtype)


def error(A: Entries, tree: Tree, near: Lists, far: Lists, tol: float) -> float:
    ix = np.arange(len(tree.x))
    g = np.random.default_rng(0).standard_normal(len(ix)) + 1j
    y = solve(A(ix, ix).astype(np.complex128), g)
    x = factorise(A, tree, near, far, tol)[0].solve(g)
    return float(np.linalg.norm(x - y) / np.linalg.norm(y))


def diam(p: NDArray[np.float64]) -> float:
    return float(np.linalg.norm(np.ptp(p, axis=0)))


@pytest.fixture(scope="module")
def instance() -> tuple[Tree, Lists, Lists]:
    return plate(64, 64)


def test_tree_is_balanced_with_median_cuts_and_tight_boxes() -> None:
    x = np.random.default_rng(1).random((1000, 3)) * [4.0, 2.0, 1.0]
    tree = cluster_tree(x, 50)
    assert tree.depth == 5
    assert np.array_equal(np.sort(tree.perm), np.arange(1000))
    np.testing.assert_array_equal(tree.x, x[tree.perm])
    for t in range(2**tree.depth - 1):
        a, b, m = 2 * t + 1, 2 * t + 2, tree.size[t]
        assert (tree.size[a], tree.size[b]) == (m // 2, m - m // 2)
        assert (tree.begin[a], tree.begin[b]) == (tree.begin[t], tree.begin[t] + m // 2)
        p = tree.x[tree.idx(t)]
        halves = [p[np.argsort(p[:, q])] for q in range(3)]
        h = [max(diam(o[: m // 2]), diam(o[m // 2 :])) for o in halves]
        left = halves[int(np.argmin(h))][: m // 2]
        np.testing.assert_array_equal(np.sort(tree.x[tree.idx(a)], 0), np.sort(left, 0))
    for t in range(len(tree.size)):
        p = tree.x[tree.idx(t)]
        np.testing.assert_array_equal(np.stack((tree.lo[t], tree.hi[t])), [p.min(0), p.max(0)])
    assert {int(tree.size[t]) for t in nodes(5)} == {31, 32}


def test_tree_on_degenerate_sets() -> None:
    line = cluster_tree(np.stack((np.linspace(0.0, 1.0, 40), np.zeros(40)), axis=-1), 4)
    assert line.depth == 4
    assert not np.any(line.hi[:, 1])
    assert all(line.hi[2 * t + 1, 0] < line.lo[2 * t + 2, 0] for t in range(15))
    same = cluster_tree(np.ones((9, 2)), 2)
    assert same.depth == 3
    assert np.array_equal(same.perm, np.arange(9))
    assert same.size[nodes(3)].tolist() == [1, 1, 1, 1, 1, 1, 1, 2]
    wide = cluster_tree(points("plate", 64)[0] * [2.0, 1.0], 32)
    assert wide.hi[1, 0] < wide.lo[2, 0]


def test_partition_covers_every_pair_once_with_admissible_far_pairs() -> None:
    tree = cluster_tree(points("sphere", 512)[0], 16)
    near, far = partition(tree, 2.5)
    count = np.zeros((512, 512), np.int64)
    for t in range(len(near)):
        for s in far[t] + (near[t] if level(t) == tree.depth else []):
            count[np.ix_(tree.idx(t), tree.idx(s))] += 1
    assert np.all(count == 1)
    assert {level(t) for t, f in enumerate(far) if f} == {4, 5}
    h = np.linalg.norm(tree.hi - tree.lo, axis=1)

    def dist(t: int, s: int) -> float:
        gap = np.maximum(0.0, np.maximum(tree.lo[t] - tree.hi[s], tree.lo[s] - tree.hi[t]))
        return float(np.linalg.norm(gap))

    for t in range(len(near)):
        assert t in near[t]
        for s in near[t]:
            assert t in near[s]
            assert dist(t, s) == 0 or (h[t] + h[s]) / 2 > 2.5 * dist(t, s)
        for s in far[t]:
            assert t in far[s]
            assert 0 < (h[t] + h[s]) / 2 <= 2.5 * dist(t, s)


def test_plate_near_graph_is_the_kings_graph(instance: tuple[Tree, Lists, Lists]) -> None:
    tree, near, far = instance
    assert tree.depth == 6
    for lvl in range(1, 7):
        T = np.array(nodes(lvl))
        c, r = (np.unique(tree.lo[T, q], return_inverse=True)[1] for q in (0, 1))
        for i, t in enumerate(T):
            assert sorted(near[t]) == T[(abs(c - c[i]) <= 1) & (abs(r - r[i]) <= 1)].tolist()
            assert bool(far[t]) == (lvl >= 3)


def test_colouring_is_greedy_distance_two(instance: tuple[Tree, Lists, Lists]) -> None:
    _, near, _ = instance
    counts = {}
    for lvl in range(3, 7):
        col = colouring(near, lvl)
        for t in nodes(lvl):
            two = {u for s in near[t] for u in near[s]} - {t}
            assert col[t] not in {col[u] for u in two}
            assert set(range(col[t])) <= {col[u] for u in two if u < t}
            same = [u for u in nodes(lvl) if u != t and col[u] == col[t]]
            assert all(set(near[t]).isdisjoint(near[u]) for u in same)
        counts[lvl] = max(col.values()) + 1
    assert counts == {3: 6, 4: 9, 5: 10, 6: 12}


def test_schedule_of_a_chain() -> None:
    near = [[0], [1, 2], [1, 2], [3, 4], [3, 4, 5], [4, 5, 6], [5, 6]]
    col = colouring(near, 2)
    assert col == {3: 0, 4: 1, 5: 2, 6: 0}
    assert schedule(near, col) == ([3, 6, 4, 5], [(0, 2), (0, 3), (1, 2), (1, 3), (2, 3)])


def test_interpolative_decomposition() -> None:
    rng = np.random.default_rng(2)
    M = (rng.standard_normal((40, 5)) + 1j) @ rng.standard_normal((5, 30))
    sk, _ = interpolative(M, 1e-12)
    assert len(sk.S) == 5
    assert np.array_equal(np.sort(np.r_[sk.S, sk.R]), np.arange(30))
    assert np.linalg.norm(sk.cols(M)) <= 1e-12 * np.linalg.norm(M)
    y, z = np.linspace(0, 1, 50), np.linspace(3, 4, 30)
    K = 1.0 / (1.0 + abs(y[:, None] - z[None]))
    ks = []
    for tol in (1e-2, 1e-5, 1e-8):
        sk, res = interpolative(K, tol)
        E = sk.cols(K)
        assert res == pytest.approx(np.linalg.norm(E), rel=1e-4)
        assert np.linalg.norm(E, 2) <= np.sqrt(len(sk.R)) * tol * np.linalg.norm(K, 2)
        ks.append(len(sk.S))
    assert ks[0] < ks[1] < ks[2] < 30
    for Z in (np.zeros((3, 4)), np.zeros((0, 4))):
        sk, res = interpolative(Z, 1e-6)
        assert (len(sk.S), sk.T.shape, res) == (0, (0, 4), 0.0)
        assert np.array_equal(sk.R, np.arange(4))


def test_triangular_keeps_the_gram_matrix() -> None:
    X = np.random.default_rng(3).standard_normal((50, 6)) * (1 + 1j)
    R = triangular(X)
    assert R.shape == (6, 6)
    assert not np.any(np.tril(R, -1))
    np.testing.assert_allclose(R.conj().T @ R, X.conj().T @ X, atol=1e-12)
    assert np.array_equal(triangular(X[:4]), X[:4])


def test_operator_entries_and_cell_integrated_self_term() -> None:
    x = np.array([[0.0, 0.0], [0.3, 0.4]])
    A = Operator(x, 0.01, 2.0, np.complex128)
    assert A(np.array([0]), np.array([1]))[0, 0] == pytest.approx(0.01 * np.exp(1j) / (2 * np.pi))
    assert A(np.array([1]), np.array([1]))[0, 0] == A.diag
    L = Operator(x, 0.01, 0.0, np.float32)(np.array([0, 1]), np.array([0, 1]))
    assert L.dtype == np.float32
    assert L[0, 1] == pytest.approx(0.01 / (2 * np.pi))
    a = 0.3
    static = Operator(x, a * a, 0.0, np.float64).diag
    assert static == pytest.approx(a * np.log1p(np.sqrt(2.0)) / np.pi, rel=1e-15)
    for kappa in (2 * np.pi, 20.0):

        def regular(
            y: float, x: float, part: Callable[[complex], float], k: float = kappa
        ) -> float:
            return part(np.expm1(1j * k * np.hypot(x, y)) / (4 * np.pi * np.hypot(x, y)))

        re, im = (
            4 * dblquad(regular, 0, a / 2, 0, a / 2, (p,), epsabs=1e-15, epsrel=1e-13)[0]
            for p in (np.real, np.imag)
        )
        diag = Operator(x, a * a, kappa, np.complex128).diag
        assert diag == pytest.approx(static + re + 1j * im, rel=1e-11)


def test_solve_error_tracks_the_tolerance() -> None:
    tree, near, far = plate(32, 64)
    A, tols = helmholtz(tree), (1e-2, 1e-4, 1e-6, 1e-8)
    errs = [error(A, tree, near, far, tol) for tol in tols]
    assert all(e <= tol for e, tol in zip(errs, tols, strict=True))
    assert errs == sorted(errs, reverse=True)
    assert error(A, tree, near, far, 0.0) < 1e-12


def test_nonsymmetric_and_single_precision_operators() -> None:
    tree, near, far = plate(32, 64)
    A, c, ix = helmholtz(tree), 1.0 + tree.x[:, 0], np.arange(1024)

    def B(I: I64, J: I64) -> NDArray[Any]:
        return c[I, None] * A(I, J)

    assert not np.allclose(B(ix, ix), B(ix, ix).T, rtol=1e-3)
    assert error(B, tree, near, far, 1e-9) < 1e-8
    A32 = helmholtz(tree, np.complex64)
    fac, _ = factorise(A32, tree, near, far, 1e-5)
    assert {fac.lu[0].dtype, fac.stages[0].L21.dtype, fac.stages[-1].T.dtype} == {
        np.dtype(np.complex64)
    }
    assert error(A32, tree, near, far, 1e-5) < 1e-5


def test_trace_bookkeeping() -> None:
    tree, near, far = plate(32, 64)
    fac, tr = factorise(helmholtz(tree), tree, near, far, 1e-6)
    stage = np.array(tr.stage)
    assert stage[:, 1].tolist() == [4] * 16 + [3] * 8
    assert np.array_equal(stage[:, 3], stage[:, 4] + stage[:, 5])
    active = {4: np.arange(1024)}
    for lvl, base in ((4, 0), (3, 16)):
        order, edges = schedule(near, col := colouring(near, lvl))
        rows = stage[base : base + len(order)]
        assert rows[:, 0].tolist() == order
        assert rows[:, 2].tolist() == [col[t] for t in order]
        dofs = tr.dof[base : base + len(order)]
        assert np.array_equal(np.sort(np.concatenate(dofs)), active[lvl])
        active[lvl - 1] = np.sort(
            np.concatenate([d[:k] for d, k in zip(dofs, rows[:, 4], strict=True)])
        )
        assert [(a - base, b - base) for a, b in tr.dag if base <= a < base + len(order)] == edges
    np.testing.assert_array_equal(np.sort(fac.top), active[2])
    assert tr.active == [[4, 1024], [3, len(active[3])], [2, len(active[2])]]
    for i, s in enumerate(fac.stages):
        assert len(s.J) == stage[i, 6]
        assert set(s.J).isdisjoint(s.R)
        assert set(s.S) <= set(s.J)
    for i, a, b, f in tr.schur:
        assert {a, b} <= set(near[stage[i, 0]])
        assert f == (b not in near[a])
    assert any(f for *_, f in tr.schur)
    assert all(level(a) == level(b) == lvl and b not in near[a] for lvl, a, b in tr.fill)
    assert len(tr.fill) == len(tr.fill_norm) > 0
    assert min(tr.fill_norm) > 0


def test_degenerate_trees_reduce_to_dense_lu() -> None:
    for tree, near, far in (plate(4, 16), plate(16, 16, eta=1e-3)):
        fac, tr = factorise(helmholtz(tree), tree, near, far, 1e-6)
        assert not fac.stages
        assert tr.active == [[tree.depth, len(tree.x)]]
        assert error(helmholtz(tree), tree, near, far, 1e-6) < 1e-13
    tree, near, far = plate(16, 16)
    with pytest.raises(np.linalg.LinAlgError, match="singular pivot block"):
        factorise(lambda I, J: np.zeros((len(I), len(J))), tree, near, far, 1e-6)


def test_kernel_validation() -> None:
    for bad in ({"n": 200}, {"kappa": -1.0}, {"precision": "half"}, {"tol": float("nan")}):
        with pytest.raises(ValidationError):
            RssLu.model_validate(bad)
    assert RssLu(geometry="sphere", n=200).n == 200


def test_kernel_arrays_are_consistent() -> None:
    arrays, meta = RssLu(geometry="sphere", n=512, leaf=16, tol=1e-5).run()
    x, S, norms = arrays["points"], arrays["stage"], arrays["stage_norm"]
    np.testing.assert_allclose(np.linalg.norm(x - 0.5, axis=1), 0.5)
    np.testing.assert_array_equal(x, points("sphere", 512)[0][arrays["perm"]])
    assert arrays["box"].shape == (63, 2, 3)
    assert arrays["range"][0].tolist() == [0, 512]
    assert meta["depth"] == 5
    assert meta["stages"] == len(S) == len(norms) == 32 + 16
    assert meta["top_size"] == len(arrays["top"]) == arrays["active"][-1, 1]
    assert meta["colours"] == {str(v): int(S[S[:, 1] == v, 2].max()) + 1 for v in set(S[:, 1])}
    assert np.array_equal(np.diff(arrays["dof_ptr"]), S[:, 3])
    for name in ("near", "far"):
        assert len(arrays[f"{name}_ptr"]) == 64
        assert arrays[f"{name}_ptr"][-1] == len(arrays[name])
    a, b = arrays["dag"].T
    assert np.all(a < b)
    assert np.array_equal(S[a, 1], S[b, 1])
    assert np.all(S[a, 2] != S[b, 2])
    assert len(arrays["schur"]) == len(arrays["schur_norm"])
    assert arrays["schur"][:, 0].max() == len(S) - 1
    assert np.all(norms[:, 2] <= 1e-5 * np.sqrt(2 * S[:, 3]) * norms[:, :2].max(1))
    assert isinstance(meta["error"], float)
    assert meta["error"] < 1e-5
    laplace = RssLu(n=256, leaf=16, kappa=0.0, precision="double", tol=1e-8).run()[1]
    assert isinstance(laplace["error"], float)
    assert laplace["error"] < 1e-8


def test_dataset_roundtrip_is_deterministic(store: Store) -> None:
    ds = compute(DataRequest(kind="h2.rss", params={"n": 256, "leaf": 16}), store)
    arrays, meta = RssLu(n=256, leaf=16).run()
    loaded = load(ds, store)
    assert loaded.keys() == arrays.keys()
    assert all(np.array_equal(loaded[k], arrays[k]) for k in arrays)
    assert ds.meta == {"version": ds.meta["version"], **meta}
