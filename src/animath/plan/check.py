import json
import re
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import JsonValue, ValidationError

from animath.core.schemas import DataRequest, Line, NodeKind, Scene, Storyboard, Visual
from animath.plan.draft import WORDS_PER_SECOND, Draft, DScene, Schemas
from animath.plan.select import Selection

TOKEN = re.compile(r"\\[A-Za-z]+|[^\W_]+")
TOLERANCE = 0.1
COVERAGE = 0.9
OVERLAPS = {frozenset({"main", "left"}), frozenset({"main", "right"})}


def words(text: str) -> int:
    """Spoken-length estimate: TeX control words and alphanumeric runs."""
    return len(TOKEN.findall(text))


def _json(raw: str, where: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        errors.append(f"{where}: invalid JSON: {e.msg}")
        return None
    if not isinstance(v, dict):
        errors.append(f"{where}: not a JSON object")
        return None
    return v


def _schema(schema: dict[str, JsonValue], v: dict[str, Any], where: str, errors: list[str]) -> None:
    for e in sorted(Draft202012Validator(schema).iter_errors(v), key=lambda e: e.json_path):
        errors.append(f"{where}: {e.json_path}: {e.message}")


def _refs(v: Any) -> Iterator[dict[str, Any]]:
    if isinstance(v, dict):
        if "data" in v and "array" in v:
            yield v
        else:
            for x in v.values():
                yield from _refs(x)
    elif isinstance(v, list):
        for x in v:
            yield from _refs(x)


def scene(
    ds: DScene,
    duration: float,
    sel: Selection,
    catalog: Schemas,
    kernels: Schemas,
    errors: list[str],
) -> Scene | None:
    """Algorithm 7.2, scene part: catalog, data, cue, region and node checks."""
    where, n0 = f"scene {ds.id}", len(errors)
    data: list[DataRequest] = []
    for i, d in enumerate(ds.data):
        w = f"{where}.data[{i}]"
        if (params := _json(d.params, w, errors)) is None:
            continue
        if kernels and d.kind not in kernels:
            errors.append(f"{w}: unknown kind {d.kind!r}; known: {sorted(kernels)}")
        elif kernels:
            _schema(kernels[d.kind], params, w, errors)
        data.append(DataRequest(kind=d.kind, params=params))
    marks = {ln.bookmark: i for i, ln in enumerate(ds.narration) if ln.bookmark}
    visuals: list[Visual] = []
    lives: list[tuple[str, int, int, str]] = []
    for k, v in enumerate(ds.visuals):
        w = f"{where}.visual[{k}]"
        if v.primitive not in catalog:
            errors.append(f"{w}: unknown primitive {v.primitive!r}; known: {sorted(catalog)}")
            continue
        if (args := _json(v.args, w, errors)) is None:
            continue
        _schema(catalog[v.primitive], args, w, errors)
        for ref in _refs(args):
            if not isinstance(ref["data"], int) or not 0 <= ref["data"] < len(ds.data):
                errors.append(f"{w}: array ref {ref} names no data request")
            if v.primitive != "matrix" and ref.get("part") is None:
                errors.append(f"{w}: array ref {ref} lacks part")
        t0 = marks.get(v.at, 0) if v.at else 0
        t1 = len(ds.narration)
        if (until := args.get("until")) is not None:
            if until not in marks or marks[until] <= t0:
                errors.append(f"{w}: until {until!r} is no bookmark after at")
            else:
                t1 = marks[until]
        lives.append((str(args.get("region", "main")), t0, t1, w))
        visuals.append(Visual(primitive=v.primitive, args=args, at=v.at))
    for i, (r, a0, a1, wa) in enumerate(lives):
        for s, b0, b1, wb in lives[i + 1 :]:
            if (r == s or frozenset({r, s}) in OVERLAPS) and a0 < b1 and b0 < a1:
                errors.append(f"{wa} and {wb}: regions {r}, {s} overlap in time")
    if not ds.visuals:
        errors.append(f"{where}: no visuals")
    if loose := sorted(set(ds.nodes) - sel.ids):
        errors.append(f"{where}: nodes outside the selection {loose}")
    try:
        sc = Scene(
            id=ds.id,
            goal=ds.goal,
            narration=tuple(Line(text=ln.text, bookmark=ln.bookmark) for ln in ds.narration),
            visuals=tuple(visuals),
            math=tuple(ds.math),
            data=tuple(data),
            nodes=tuple(ds.nodes),
            duration_s=duration,
        )
    except ValidationError as e:
        errors.extend(f"{where}: {x['msg']}" for x in e.errors())
        return None
    return sc if len(errors) == n0 else None


def build(
    d: Draft,
    sel: Selection,
    duration_s: float,
    catalog: Schemas,
    kernels: Schemas,
) -> tuple[Storyboard | None, list[str]]:
    """Algorithm 7.2: validated Storyboard with word-proportional durations, or the errors."""
    if not d.scenes:
        return None, ["no scenes"]
    errors: list[str] = []
    w = [max(1, sum(words(ln.text) for ln in s.narration)) for s in d.scenes]
    total = sum(w)
    if abs(total / WORDS_PER_SECOND - duration_s) > TOLERANCE * duration_s:
        target = round(WORDS_PER_SECOND * duration_s)
        errors.append(f"spoken words {total}, target {target} within {TOLERANCE:.0%}")
    scenes = [
        scene(s, round(duration_s * wi / total, 3), sel, catalog, kernels, errors)
        for s, wi in zip(d.scenes, w, strict=True)
    ]
    covered = sel.seeds & {i for s in d.scenes for i in s.nodes}
    if sel.seeds and len(covered) < COVERAGE * len(sel.seeds):
        errors.append(f"seed nodes not covered: {sorted(sel.seeds - covered)}")
    symbols = {s.latex: s.meaning for s in d.symbols} | {
        n.latex: n.meaning or n.name for n in sel.nodes if n.kind is NodeKind.SYMBOL and n.latex
    }
    if errors:
        return None, errors
    try:
        board = Storyboard(title=d.title, scenes=tuple(s for s in scenes if s), symbols=symbols)
    except ValidationError as e:
        return None, [x["msg"] for x in e.errors()]
    return board, []
