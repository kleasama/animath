from pathlib import Path
from typing import Any

import pytest

from animath.core.schemas import SourceBundle, SourceFile, SourceFormat
from animath.core.store import Store

GOLDEN = Path(__file__).parents[1] / "golden"


def bundle(
    store: Store, fmt: SourceFormat, entry: str, files: dict[str, bytes], **kw: Any
) -> SourceBundle:
    sf = tuple(SourceFile(path=p, blob=store.put_blob(b)) for p, b in sorted(files.items()))
    return SourceBundle(format=fmt, entry=entry, files=sf, **kw)


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != "expected.json"
    }


@pytest.fixture
def golden() -> Path:
    return GOLDEN
