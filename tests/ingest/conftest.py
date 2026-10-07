from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from animath.core.schemas import SourceBundle, SourceFile, SourceFormat, Usage
from animath.core.store import Store

GOLDEN = Path(__file__).parents[1] / "golden"


class Fake:
    """LLM returning queued outputs in order."""

    def __init__(self, *outs: BaseModel) -> None:
        self.outs = list(outs)
        self.calls: list[tuple[str, int]] = []

    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]:
        self.calls.append((prompt, len(images)))
        return schema.model_validate(self.outs.pop(0).model_dump()), Usage(input_tokens=5)


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
