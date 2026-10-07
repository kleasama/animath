import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from animath.core.errors import StoreError
from animath.core.hashing import canonical, digest, digest_of
from animath.core.schemas import Artifact


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Store:
    """Content-addressed artifact store; safe under concurrent writers via atomic rename."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def key(*parts: str) -> str:
        return digest_of(list(parts))

    def _blob(self, d: str) -> Path:
        return self.root / "blobs" / d[:2] / d[2:]

    def _artifact(self, kind: str, d: str) -> Path:
        return self.root / "artifacts" / kind / f"{d}.json"

    def ref(self, ns: str, key: str) -> str | None:
        path = self.root / "index" / ns / key
        return path.read_text() if path.is_file() else None

    def set_ref(self, ns: str, key: str, d: str) -> None:
        _atomic_write(self.root / "index" / ns / key, d.encode())

    def put_blob(self, data: bytes) -> str:
        d = digest(data)
        path = self._blob(d)
        if not path.exists():
            _atomic_write(path, data)
        return d

    def blob_path(self, d: str) -> Path:
        path = self._blob(d)
        if not path.is_file():
            raise StoreError(f"missing blob {d}")
        return path

    def get_blob(self, d: str) -> bytes:
        data = self.blob_path(d).read_bytes()
        if digest(data) != d:
            raise StoreError(f"corrupt blob {d}")
        return data

    def put(self, art: Artifact, key: str | None = None) -> str:
        data = canonical(art)
        d = digest(data)
        path = self._artifact(art.kind, d)
        if not path.exists():
            _atomic_write(path, data)
        if key is not None:
            self.set_ref(art.kind, key, d)
        return d

    def get[A: Artifact](self, cls: type[A], d: str) -> A:
        path = self._artifact(cls.kind, d)
        try:
            data = path.read_bytes()
        except FileNotFoundError as e:
            raise StoreError(f"missing {cls.kind} {d}") from e
        if digest(data) != d:
            raise StoreError(f"corrupt {cls.kind} {d}")
        try:
            return cls.model_validate_json(data)
        except ValidationError as e:
            raise StoreError(f"invalid {cls.kind} {d}: {e}") from e

    def lookup[A: Artifact](self, cls: type[A], key: str) -> A | None:
        d = self.ref(cls.kind, key)
        return None if d is None else self.get(cls, d)
