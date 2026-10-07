import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import manim
import numpy as np
import pytest

from animath.core.schemas import DataRequest, DataSet, Line, Scene, Visual
from animath.core.store import Store
from animath.scene.layout import cell, frame
from animath.scene.primitives import Context

F = frame(16.0, 9.0)
MAIN = cell("main", F)
REQ = DataRequest(kind="test")


@pytest.fixture(autouse=True)
def _media(tmp_path: Path) -> Iterator[None]:
    with manim.tempconfig({"media_dir": str(tmp_path / "media"), "verbosity": "ERROR"}):
        yield


def npy(store: Store, a: Any) -> str:
    b = io.BytesIO()
    np.save(b, np.asarray(a))
    return store.put_blob(b.getvalue())


def scene(*visuals: Visual, marks: tuple[str, ...] = ("a", "b"), duration: float = 4.0) -> Scene:
    return Scene(
        id="s",
        goal="g",
        narration=tuple(Line(text=m, bookmark=m) for m in marks),
        visuals=visuals,
        data=(REQ,),
        duration_s=duration,
    )


def context(store: Store, **arrays: Any) -> Context:
    ds = DataSet(request=REQ, arrays={k: npy(store, v) for k, v in arrays.items()})
    return Context(scene(), store, {REQ.digest: ds}, 30.0)


def ref(name: str) -> dict[str, Any]:
    return {"data": 0, "array": name}
