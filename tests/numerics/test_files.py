import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from animath.core.errors import ComputeError
from animath.core.schemas import DataRequest
from animath.core.store import Store
from animath.numerics import VERSION, compute, load


def savez(**arrays: Any) -> bytes:
    b = io.BytesIO()
    np.savez(b, **arrays)
    return b.getvalue()


def pinned(tmp_path: Path, raw: bytes, name: str = "d.npz") -> DataRequest:
    p = tmp_path / name
    p.write_bytes(raw)
    return DataRequest(
        kind="data.npz", params={"path": str(p), "sha256": hashlib.sha256(raw).hexdigest()}
    )


def test_roundtrip_and_cache(store: Store, tmp_path: Path) -> None:
    x = np.arange(6, dtype=np.int64).reshape(2, 3)
    z = np.array([1 + 2j, -1j], dtype=np.complex64)
    meta = np.array(json.dumps({"depth": 6, "report": {"a": [1, 2]}}))
    req = pinned(tmp_path, savez(x=x, z=z, meta=meta))
    ds = compute(req, store)
    assert ds.meta == {"version": VERSION, "depth": 6, "report": {"a": [1, 2]}}
    arrays = load(ds, store)
    assert arrays.keys() == {"x", "z"}
    np.testing.assert_array_equal(arrays["x"], x)
    np.testing.assert_array_equal(arrays["z"], z)
    assert arrays["z"].dtype == np.complex64
    Path(str(req.params["path"])).unlink()
    assert compute(req, store) == ds


def npy() -> bytes:
    b = io.BytesIO()
    np.save(b, np.arange(3))
    return b.getvalue()


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (b"", "No data left"),
        (npy(), r"not an \.npz archive"),
        (savez(a=np.ones(3))[:50], "not a zip file"),
        (savez(o=np.array([{}], dtype=object)), "Object arrays cannot be loaded"),
        (savez(s=np.array(["a", "b"])), r"non-numeric arrays \['s'\]"),
        (savez(meta=np.array("[1, 2]")), "meta is not a JSON object"),
        (savez(meta=np.array(5)), "must be str"),
    ],
)
def test_rejects(store: Store, tmp_path: Path, raw: bytes, match: str) -> None:
    with pytest.raises(ComputeError, match=match):
        compute(pinned(tmp_path, raw), store)


def test_rejects_unpinned(store: Store, tmp_path: Path) -> None:
    req = pinned(tmp_path, savez(a=np.ones(2)))
    path, sha = str(req.params["path"]), str(req.params["sha256"])
    other = hashlib.sha256(b"other").hexdigest()
    with pytest.raises(ComputeError, match="sha256 mismatch"):
        compute(DataRequest(kind="data.npz", params={"path": path, "sha256": other}), store)
    with pytest.raises(ComputeError, match="No such file"):
        compute(DataRequest(kind="data.npz", params={"path": path + ".npz", "sha256": sha}), store)
    for bad in (
        {"path": "d.npz", "sha256": sha},
        {"path": path[:-1] + "y", "sha256": sha},
        {"path": path, "sha256": sha.upper()},
    ):
        with pytest.raises(ComputeError, match=r"invalid params for data\.npz"):
            compute(DataRequest(kind="data.npz", params=bad), store)
