import json
from collections.abc import Mapping

from pydantic import BaseModel, JsonValue

from animath.core.schemas import KnowledgeGraph, Params
from animath.plan.select import Selection

WORDS_PER_SECOND = 2.5
SECONDS_PER_SCENE = 30.0
Schemas = Mapping[str, dict[str, JsonValue]]

SYSTEM = """Plan an educational math video as a storyboard of scenes, in teaching order.
Rules:
1. Each scene: unique id, one-sentence goal, narration lines, at least one visual,
   the node ids it teaches.
2. Narration is spoken prose; inline math as $...$. Total spoken words (TeX commands
   and alphanumeric runs count one each) must match the word target within 10%.
3. A visual names a primitive of the catalog; `args` is a JSON object valid against
   its schema.
4. `at` and `until` are bookmarks of lines of the same scene; `until` comes after `at`.
   Visuals whose lifetimes overlap occupy disjoint regions; `left` and `right`
   partition `main`.
5. Arrays are {"data": i, "array": name, "part": p}: scene data request i,
   p in {abs, real, imag}; `part` is required outside `matrix`.
6. A data request has a kind of the kernel catalog and `params` as a JSON object
   valid against its schema.
7. On-screen formulas are those of the nodes or exact consequences; use the source
   notation.
8. Cover every seed node. List symbols as LaTeX with their meaning.
When errors of a previous draft are given, return a corrected full draft."""


class DLine(BaseModel):
    text: str
    bookmark: str | None = None


class DVisual(BaseModel):
    primitive: str
    args: str
    at: str | None = None


class DData(BaseModel):
    kind: str
    params: str = "{}"


class DScene(BaseModel):
    id: str
    goal: str
    narration: list[DLine]
    visuals: list[DVisual]
    math: list[str] = []
    data: list[DData] = []
    nodes: list[str] = []


class DSymbol(BaseModel):
    latex: str
    meaning: str


class Draft(BaseModel):
    title: str
    scenes: list[DScene]
    symbols: list[DSymbol] = []


def prompt(
    g: KnowledgeGraph,
    sel: Selection,
    p: Params,
    catalog: Schemas,
    kernels: Schemas,
) -> str:
    ids = sel.ids
    task = {
        "audience": p.audience.value,
        "language": p.language,
        "duration_s": p.duration_s,
        "scenes_target": max(1, round(p.duration_s / SECONDS_PER_SCENE)),
        "words_target": round(WORDS_PER_SECOND * p.duration_s),
        "seeds": sorted(sel.seeds),
        "nodes": [n.model_dump(exclude={"sources"}, exclude_none=True) for n in sel.nodes],
        "edges": [e.model_dump() for e in g.edges if e.src in ids and e.dst in ids],
        "catalog": dict(catalog),
        "kernels": dict(kernels),
    }
    return json.dumps(task, sort_keys=True, ensure_ascii=False)


def repair(base: str, d: Draft, errors: list[str]) -> str:
    return f"{base}\n\nPrevious draft:\n{d.model_dump_json()}\n\nErrors:\n" + "\n".join(errors)
