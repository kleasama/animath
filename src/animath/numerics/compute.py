import io

import numpy as np
from pydantic import ValidationError

from animath.core.errors import ComputeError
from animath.core.hashing import digest_of
from animath.core.schemas import DataRequest, DataSet
from animath.core.store import Store
from animath.numerics.base import Kernel
from animath.numerics.kernels import DlpEllipse, EfieCylinder
from animath.numerics.krylov import Cg, Gmres
from animath.numerics.quadrature import Convergence, Rule

VERSION = "0.1"
KINDS: dict[str, type[Kernel]] = {
    "quadrature.rule": Rule,
    "quadrature.convergence": Convergence,
    "mom.efie_cylinder": EfieCylinder,
    "bem.dlp_ellipse": DlpEllipse,
    "krylov.gmres": Gmres,
    "krylov.cg": Cg,
}


def parse(request: DataRequest) -> Kernel:
    if request.kind not in KINDS:
        raise ComputeError(f"unknown data kind {request.kind!r}; known: {sorted(KINDS)}")
    try:
        return KINDS[request.kind].model_validate(request.params)
    except ValidationError as e:
        raise ComputeError(f"invalid params for {request.kind}: {e}") from e


def compute(request: DataRequest, store: Store) -> DataSet:
    """Phi_4: DataSet for `request`, cached under H(numerics, VERSION, kind, normalized params)."""
    kernel = parse(request)
    key = Store.key("numerics", VERSION, request.kind, digest_of(kernel))
    if (hit := store.lookup(DataSet, key)) is not None:
        return hit
    try:
        arrays, meta = kernel.run()
    except (np.linalg.LinAlgError, FloatingPointError) as e:
        raise ComputeError(f"{request.kind}: {e}") from e
    bad = sorted(k for k, a in arrays.items() if not np.all(np.isfinite(a)))
    if bad:
        raise ComputeError(f"{request.kind}: non-finite arrays {bad}")
    ds = DataSet(
        request=request,
        arrays={k: store.put_blob(_encode(a)) for k, a in arrays.items()},
        meta={"version": VERSION, **meta},
    )
    store.put(ds, key=key)
    return ds


def load(ds: DataSet, store: Store) -> dict[str, np.ndarray]:
    return {
        k: np.load(io.BytesIO(store.get_blob(d)), allow_pickle=False) for k, d in ds.arrays.items()
    }


def _encode(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, np.ascontiguousarray(a), allow_pickle=False)
    return buf.getvalue()
