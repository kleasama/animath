import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from animath.core.errors import StoreError
from animath.core.hashing import digest
from animath.core.schemas import DocIR, KnowledgeGraph
from animath.core.store import Store


def test_artifact_roundtrip_and_idempotence(store: Store, doc: DocIR) -> None:
    d = store.put(doc)
    assert store.put(doc) == d
    assert store.get(DocIR, d) == doc
    assert len(list((store.root / "artifacts" / "doc").iterdir())) == 1


def test_lookup_by_input_key(store: Store, doc: DocIR, graph: KnowledgeGraph) -> None:
    k = Store.key("extract", "v1", store.put(doc))
    assert store.lookup(KnowledgeGraph, k) is None
    store.put(graph, key=k)
    assert store.lookup(KnowledgeGraph, k) == graph
    assert Store.key("extract", "v2") != Store.key("extract", "v1")


def test_get_detects_missing_corrupt_and_invalid(store: Store, doc: DocIR) -> None:
    with pytest.raises(StoreError, match="missing doc"):
        store.get(DocIR, "f" * 64)
    d = store.put(doc)
    path = store.root / "artifacts" / "doc" / f"{d}.json"
    path.write_bytes(path.read_bytes().replace(b"EFIE", b"MFIE"))
    with pytest.raises(StoreError, match="corrupt doc"):
        store.get(DocIR, d)
    bad = b'{"title": "t", "blocks": []}'
    (path.parent / f"{digest(bad)}.json").write_bytes(bad)
    with pytest.raises(StoreError, match="invalid doc"):
        store.get(DocIR, digest(bad))


def test_blobs(store: Store) -> None:
    d = store.put_blob(b"\x00\x01")
    assert store.put_blob(b"\x00\x01") == d
    assert store.get_blob(d) == b"\x00\x01"
    store.blob_path(d).write_bytes(b"\x00\x02")
    with pytest.raises(StoreError, match="corrupt blob"):
        store.get_blob(d)
    with pytest.raises(StoreError, match="missing blob"):
        store.blob_path("a" * 64)


def _leftovers(root: Path) -> list[Path]:
    return list(root.rglob(".tmp-*"))


def test_concurrent_threads(store: Store) -> None:
    payloads = [bytes([i % 7]) * 4096 for i in range(256)]
    with ThreadPoolExecutor(32) as ex:
        ds = list(ex.map(store.put_blob, payloads))
        list(ex.map(lambda i: store.set_ref("ns", "k", ds[i]), range(256)))
    assert [store.get_blob(d) for d in ds] == payloads
    assert store.ref("ns", "k") in set(ds)
    assert not _leftovers(store.root)


def _write(args: tuple[str, int]) -> str:
    root, i = args
    return Store(Path(root)).put_blob(str(i % 3).encode() * 100_000)


def test_concurrent_processes(store: Store) -> None:
    with ProcessPoolExecutor(4) as ex:
        ds = list(ex.map(_write, [(str(store.root), i) for i in range(24)]))
    assert len(set(ds)) == 3
    assert {store.get_blob(d)[:1] for d in ds} == {b"0", b"1", b"2"}
    assert not _leftovers(store.root)


def test_failed_write_leaves_no_temporaries(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.put_blob(b"x")
    assert not _leftovers(store.root)
    assert store.ref("ns", "absent") is None
