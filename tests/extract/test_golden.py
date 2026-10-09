from pathlib import Path

import pytest

from animath.core.schemas import DocIR, NodeKind, Relation, Usage
from animath.core.store import Store
from animath.extract import run
from animath.extract.draft import Draft
from animath.llm import Replay
from tests.fake import Fake

HERE = Path(__file__).parent
KEYS = {
    "efie": {"efie", "mom", "uniqueness"},
    "gmres": {"gmres", "arnoldi", "arnoldi-relation", "ls"},
    "gauss": {"rule", "exactness", "golub-welsch"},
}


@pytest.mark.parametrize("name", sorted(KEYS))
def test_golden(store: Store, name: str) -> None:
    doc = DocIR.model_validate_json((HERE.parent / "golden" / name / "expected.json").read_text())
    d = Draft.model_validate_json((HERE / "golden" / f"{name}.json").read_text())
    kg, usage = run(doc, store, Replay(store, Fake(d), "test"))
    assert usage == Usage(input_tokens=1)
    assert [n.id for n in kg.nodes] == [n.id for n in d.nodes]
    assert {n.id for n in kg.nodes if n.key} == KEYS[name]
    blocks = {b.id: b for b in doc.blocks}
    for n in kg.nodes:
        assert set(n.sources) <= blocks.keys()
        if n.kind is NodeKind.EQUATION:
            assert n.latex == blocks[n.sources[0]].latex
    assert sum(e.rel is Relation.DEPENDS_ON for e in kg.edges) >= len(KEYS[name])
    fresh = Store(store.root.with_name("fresh"))
    for p in (store.root / "index" / "llm").iterdir():
        fresh.set_ref("llm", p.name, fresh.put_blob(store.get_blob(p.read_text())))
    assert run(doc, fresh, Replay(fresh, None, "test")) == (kg, Usage())
