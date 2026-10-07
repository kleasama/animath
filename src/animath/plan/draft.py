import json
from collections.abc import Mapping

from pydantic import BaseModel, Field, JsonValue

from animath.core.schemas import KnowledgeGraph, Params
from animath.plan.select import Selection

SPEECH = 0.85
SECONDS_PER_SCENE = 40.0
Schemas = Mapping[str, dict[str, JsonValue]]

SYSTEM = """Plan an educational math video as a storyboard of scenes, in teaching order.
Rules:
1. Each scene: unique id, one-sentence goal, narration lines, at least one visual,
   the node ids it teaches.
2. Narration is spoken prose, one sentence or clause per line; inline math as $...$,
   timed as read aloud ($\\int_{-1}^{1} f(x)\\,dx$: "the integral from minus 1 to 1 of
   f of x d x"). Speech runs at `wpm` words per minute, with 0.4 s before a scene's first
   line, 0.35 s after each line that ends a sentence (. ! ?) or has a `pause`, and each
   line's `pause` after it; the estimated total must match `duration_s` within 10%.
3. Motion: something on screen changes at least every 7 s while the narration goes on.
   A line's `actions` change visuals of its scene as it is spoken: `visual` is the
   index, `do` a verb of the visual's catalog entry, `parts` part selectors listed
   there (empty: the whole visual), `word` a plain word of the line, not math, at
   which the action fires (else the line start), `color` for `mark`. Build formulas
   term by term (`show`), highlight what the line names (`indicate`, `mark`), dim what
   is done, and morph a formula into its next form by a visual with `replaces` that
   enters at the `until` of the visual it replaces.
4. Holds: a line on which a visual enters, and the last line, get at least 1 s of
   pause; give a longer `pause` where a motion must finish before the next sentence.
5. Repetition (levels, sweeps, iterations, colour classes): use the scene's `loop`.
   Its `lines` take the first item slowly, every step introduced and explained, with
   actions. Later items replay those actions, each pass `speedup` times shorter than
   the one before but at least 1 s per action, under `brief`: one short line per
   later item, or one line for all. `after` lines then show the result. `{}` in the
   loop's lines, per-item brief lines and action parts stands for the item.
6. Views: a visual with `view` in its args continues the last visual with the same
   `view` and primitive, in this or an earlier scene. It keeps that visual's args and
   state, and takes new actions, `until` and `replaces`. If that visual is on screen at
   the end of the previous scene and this one has no `at`, it carries on without
   re-entering; else it enters again with its state, e.g. by `replaces` from a zoom
   that held its region meanwhile.
7. A visual names a primitive of the catalog; `args` is a JSON object valid against
   its schema; actions come from lines. Prefer catalog primitives; use `code` for
   diagrams none of them draws.
8. `at` and `until` are bookmarks of lines of the same scene; `until` comes after
   `at`. Visuals whose lifetimes overlap occupy disjoint regions; `left` and `right`
   partition `main`.
9. Arrays are {"data": i, "array": name, "part": p}: scene data request i,
   p in {abs, real, imag}; `part` is required outside `matrix`.
10. A data request has a kind of the kernel catalog and `params` as a JSON object
   valid against its schema.
11. On-screen formulas (`math`, `equation`, `derive` steps) are formulas of the nodes in
   their notation, items of them, or lists of these; a `derive` step may instead be
   equivalent to the step before it. Values worked out for an example come from data
   requests, shown by data visuals such as `matrix`, never typed into a formula.
12. Cover every seed node. List symbols as LaTeX with their meaning.
When errors of a previous draft are given, return a corrected full draft."""


class DAction(BaseModel):
    visual: int = Field(description="index of a visual of the scene")
    do: str = Field(description="verb")
    parts: list[str] = []
    word: str | None = Field(None, description="plain word of the line firing the action")
    color: str | None = None


class DLine(BaseModel):
    text: str
    bookmark: str | None = None
    actions: list[DAction] = []
    pause: float = Field(0.0, description="seconds of silence after the line")


class DLoop(BaseModel):
    over: list[str] = Field(description="at least two items")
    lines: list[DLine] = Field(description="first pass, over the first item")
    brief: list[str] = Field(description="one line per later item, or one for all")
    speedup: float = 2.0


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
    loop: DLoop | None = None
    after: list[DLine] = []
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
        "wpm": p.wpm,
        "scenes_target": max(1, round(p.duration_s / SECONDS_PER_SCENE)),
        "words_target": round(p.wpm / 60 * SPEECH * p.duration_s),
        "seeds": sorted(sel.seeds),
        "nodes": [n.model_dump(exclude={"sources"}, exclude_none=True) for n in sel.nodes],
        "edges": [e.model_dump() for e in g.edges if e.src in ids and e.dst in ids],
        "catalog": dict(catalog),
        "kernels": dict(kernels),
    }
    return json.dumps(task, sort_keys=True, ensure_ascii=False)


def repair(base: str, d: Draft, errors: list[str]) -> str:
    return f"{base}\n\nPrevious draft:\n{d.model_dump_json()}\n\nErrors:\n" + "\n".join(errors)
