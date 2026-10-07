from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from animath.core.errors import ComputeError
from animath.core.schemas import DataRequest, DataSet
from animath.core.store import Store
from animath.numerics import KINDS, VERSION, compute, load, parse
from animath.numerics.base import Kernel, Result
from animath.numerics.quadrature import Rule

RULE = DataRequest(kind="quadrature.rule", params={"n": 4})


class Bad(Kernel):
    error: bool = False

    def run(self) -> Result:
        if self.error:
            raise np.linalg.LinAlgError("singular")
        return {"x": np.array([1.0, np.inf])}, {}


def test_compute_roundtrip(store: Store) -> None:
    ds = compute(RULE, store)
    assert ds.request == RULE
    assert ds.meta == {"version": VERSION, "degree": 7}
    arrays = load(ds, store)
    np.testing.assert_allclose(arrays["nodes"], np.polynomial.legendre.leggauss(4)[0], atol=1e-15)
    assert arrays["weights"].dtype == np.float64


def test_cache_keys_on_normalized_params(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    ds = compute(RULE, store)

    def boom(self: Rule) -> Result:
        raise AssertionError("cache miss")

    monkeypatch.setattr(Rule, "run", boom)
    alias = DataRequest(kind="quadrature.rule", params={"n": 4, "a": -1.0, "b": 1})
    assert compute(alias, store).arrays == ds.arrays


def test_deterministic_across_stores(tmp_path: Path) -> None:
    req = DataRequest(
        kind="krylov.gmres", params={"operator": {"name": "efie", "ka": 1.0, "n": 20}}
    )
    a, b = (compute(req, Store(tmp_path / s)) for s in "ab")
    assert a == b


def test_concurrent_requests_share_one_artifact(store: Store) -> None:
    reqs = [DataRequest(kind="bem.dlp_ellipse", params={"n_max": 32})] * 8
    with ThreadPoolExecutor(4) as pool:
        out = list(pool.map(lambda r: compute(r, store), reqs))
    assert all(ds == out[0] for ds in out)
    assert len(list((store.root / "artifacts" / DataSet.kind).iterdir())) == 1


def test_every_kind_runs_on_defaults(store: Store) -> None:
    minimal = {
        "quadrature.rule": {"n": 2},
        "quadrature.convergence": {"integrand": "runge", "n_max": 5},
        "mom.efie_cylinder": {"ka": 1.0, "n": 16},
        "bem.dlp_ellipse": {"n_max": 8},
        "krylov.gmres": {"operator": {"name": "poisson1d", "n": 4}},
        "krylov.cg": {"operator": {"name": "convdiff", "n": 4, "peclet": 0.0}},
    }
    assert minimal.keys() == KINDS.keys()
    for kind, params in minimal.items():
        assert compute(DataRequest(kind=kind, params=params), store).arrays


def test_errors_are_typed(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ComputeError, match="unknown data kind 'fft'"):
        parse(DataRequest(kind="fft"))
    with pytest.raises(ComputeError, match=r"invalid params for quadrature\.rule"):
        compute(DataRequest(kind="quadrature.rule", params={"n": -1}), store)
    with pytest.raises(ComputeError, match="Hermitian"):
        compute(DataRequest(kind="krylov.cg", params={"operator": {"name": "dlp"}}), store)
    monkeypatch.setitem(KINDS, "bad", Bad)
    with pytest.raises(ComputeError, match=r"non-finite arrays \['x'\]"):
        compute(DataRequest(kind="bad"), store)
    with pytest.raises(ComputeError, match="bad: singular"):
        compute(DataRequest(kind="bad", params={"error": True}), store)
