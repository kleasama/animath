import os
from pathlib import Path

import pytest

from animath.core.schemas import DocIR, SourceFormat, Usage
from animath.core.store import Store
from animath.ingest import run
from animath.ingest.pdf import Transcript
from animath.llm import Replay
from tests.ingest.conftest import Fake, bundle, tree

CASES = [
    ("efie", SourceFormat.MD, "efie.md"),
    ("gmres", SourceFormat.LATEX, "main.tex"),
    ("gauss", SourceFormat.PDF, "gauss.pdf"),
]


@pytest.mark.parametrize(("name", "fmt", "entry"), CASES)
def test_golden(store: Store, golden: Path, name: str, fmt: SourceFormat, entry: str) -> None:
    files = tree(golden / name)
    fixture = files.pop("transcript.json", None)
    fake = Fake(*([Transcript.model_validate_json(fixture)] if fixture else []))
    b = bundle(store, fmt, entry, files)
    doc, usage = run(b, store, Replay(store, fake, "test"))
    path = golden / name / "expected.json"
    if os.environ.get("ANIMATH_UPDATE_GOLDEN"):
        path.write_text(doc.model_dump_json(indent=1, exclude_defaults=True) + "\n")
    assert doc == DocIR.model_validate_json(path.read_text())
    assert usage == Usage(input_tokens=5 if fixture else 0)
    offline = Replay(store, None, "test")
    assert run(b, store, offline) == (doc, Usage())
    if fixture is None:
        fresh = Store(store.root.with_name("fresh"))
        assert run(bundle(fresh, fmt, entry, files), fresh, offline)[0] == doc


def test_pdf_replay_offline_after_recording(store: Store, golden: Path) -> None:
    files = tree(golden / "gauss")
    t = Transcript.model_validate_json(files.pop("transcript.json"))
    b = bundle(store, SourceFormat.PDF, "gauss.pdf", files)
    run(b, store, Replay(store, Fake(t), "test"))
    fresh = Store(store.root.with_name("other"))
    for d in (store.root / "index" / "llm").iterdir():
        fresh.set_ref("llm", d.name, fresh.put_blob(store.get_blob(d.read_text())))
    b2 = bundle(fresh, SourceFormat.PDF, "gauss.pdf", files)
    expected = DocIR.model_validate_json((golden / "gauss" / "expected.json").read_text())
    assert run(b2, fresh, Replay(fresh, None, "test")) == (expected, Usage())
