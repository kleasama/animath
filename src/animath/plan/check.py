import json
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import JsonValue, ValidationError

from animath.core.formula import parts, untraced
from animath.core.schemas import DataRequest, Line, NodeKind, Scene, Storyboard, Visual
from animath.plan.draft import DAction, DLine, Draft, DScene, Schemas
from animath.plan.select import Selection

TOKEN = re.compile(r"\\[A-Za-z]+|[^\W_]+")
MATH = re.compile(r"\$[^$]*\$")
SPOKEN = re.compile(r"\$[^$]*\$|\S+")
END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s*$")
TOLERANCE = 0.1
COVERAGE = 0.9
OVERLAPS = {frozenset({"main", "left"}), frozenset({"main", "right"})}
MATH_WEIGHT = 1.5
LEAD_S, GAP_S, HOLD_S, STEP_S, STATIC_S, PAUSE_MAX = 0.4, 0.35, 1.0, 1.0, 7.0, 30.0
Said = Callable[[Sequence[str]], Sequence[str]]


def words(text: str) -> float:
    """Spoken-length estimate: TeX control words and alphanumeric runs, MATH_WEIGHT each in
    inline math."""
    math = sum(len(TOKEN.findall(m)) for m in MATH.findall(text))
    return len(TOKEN.findall(MATH.sub(" ", text))) + MATH_WEIGHT * math


def spoken(d: Draft, wpm: int, said: Said | None) -> Callable[[str], float]:
    """Spoken words of each line: `said` verbalizes every line of the draft in one call; without
    it, the estimate `words`."""
    if said is None:
        return words
    texts = list(dict.fromkeys(b.text for ds in d.scenes for b in script(ds, wpm, [], words)))
    return dict(zip(texts, (len(s.split()) for s in said(texts)), strict=True)).__getitem__


def norm(word: str) -> str:
    return "".join(re.findall(r"[^\W_]+", word.casefold()))


def position(word: str | None, text: str) -> float | None:
    """Fraction of the line's spoken length, weighted as in `words`, before the first plain word
    `word`, ignoring case and punctuation."""
    if word is None:
        return 0.0
    w = norm(word)
    hit = [x.start() for x in SPOKEN.finditer(text) if w and "$" not in x[0] and norm(x[0]) == w]
    return words(text[: hit[0]]) / words(text) if hit else None


@dataclass(eq=False)
class Beat:
    """Line of the expanded script with its actions (visual, Action) and timing estimate."""

    text: str
    bookmark: str
    pause: float
    acts: list[tuple[int, dict[str, Any]]]
    where: str
    speech: float = 0.0
    onset: float = 0.0


def _act(a: DAction, at: str, item: str | None, **extra: Any) -> tuple[int, dict[str, Any]]:
    parts = [p.replace("{}", item) if item else p for p in a.parts]
    x = {"at": at, "do": a.do, "parts": parts, "word": a.word, "color": a.color} | extra
    return a.visual, {k: v for k, v in x.items() if v is not None}


def script(
    ds: DScene, wpm: int, errors: list[str], count: Callable[[str], float] = words
) -> list[Beat]:
    """Lines, loop passes and holds, with onsets estimated at `wpm` from `count`
    words per line; a word action also carries its estimated offset in the slot, the fallback
    without word times."""
    where = f"scene {ds.id}"
    out: list[Beat] = []

    def add(ln: DLine, w: str, item: str | None = None) -> Beat:
        text = ln.text.replace("{}", item) if item else ln.text
        if ln.bookmark and ln.bookmark.startswith("#"):
            errors.append(f"{w}: bookmark {ln.bookmark!r}: # is kept for unnamed lines")
        b = Beat(text, ln.bookmark or f"#{len(out)}", ln.pause, [], w)
        for j, a in enumerate(ln.actions):
            if position(a.word, text) is None:
                errors.append(f"{w}.actions[{j}]: word {a.word!r} is no plain word of the line")
            b.acts.append(_act(a, b.bookmark, item))
        out.append(b)
        return b

    for i, ln in enumerate(ds.narration):
        add(ln, f"{where}.narration[{i}]")
    lp, briefs = ds.loop, []
    if lp is not None:
        item = lp.over[0] if lp.over else None
        first = [add(ln, f"{where}.loop.lines[{i}]", item) for i, ln in enumerate(lp.lines)]
        if len(lp.over) < 2 or not first or lp.speedup < 1:
            errors.append(f"{where}.loop: needs two items, lines, and speedup >= 1")
        elif len(lp.brief) not in {1, len(lp.over) - 1}:
            errors.append(f"{where}.loop: brief needs one line per later item, or one for all")
        else:
            per = len(lp.brief) == len(lp.over) - 1
            if not per and "{}" in lp.brief[0]:
                errors.append(f"{where}.loop.brief[0]: {{}} needs one brief line per later item")
            briefs = [
                add(DLine(text=t), f"{where}.loop.brief[{i}]", lp.over[i + 1] if per else None)
                for i, t in enumerate(lp.brief)
            ]
    for i, ln in enumerate(ds.after):
        add(ln, f"{where}.after[{i}]")
    marks = {b.bookmark: i for i, b in enumerate(out)}
    for v in ds.visuals:
        b = out[marks[v.at]] if v.at in marks else out[0] if out and v.at is None else None
        if b is not None:
            b.pause = max(b.pause, HOLD_S)
    if out:
        out[-1].pause = max(out[-1].pause, HOLD_S)
    if briefs and lp is not None:
        replay(out, lp.lines, lp.over, briefs, lp.speedup, wpm, count)
    else:
        onsets(out, wpm, count)
    for i, b in enumerate(out):
        if not 0.0 <= b.pause <= PAUSE_MAX:
            errors.append(f"{b.where}: pause {b.pause:.2f} s outside [0, {PAUSE_MAX:.0f}] s")
        for _, a in b.acts:
            if "word" in a:
                at = b.speech * (position(a["word"], b.text) or 0.0) / slot(out, i)
                a["frac"] = round(min(0.99, at), 4)
    return out


def onsets(beats: list[Beat], wpm: int, count: Callable[[str], float]) -> None:
    t = LEAD_S
    for i, b in enumerate(beats):
        b.speech, b.onset = count(b.text) * 60 / wpm, t
        t += slot(beats, i)


def slot(beats: list[Beat], i: int) -> float:
    """Speech, pause, and the gap after an utterance end (. ! ? or a pause) before a line."""
    b = beats[i]
    ends = b.pause > 0 or END.search(b.text) is not None
    return b.speech + b.pause + GAP_S * (ends and i < len(beats) - 1)


def replay(
    beats: list[Beat],
    lines: list[DLine],
    over: list[str],
    briefs: list[Beat],
    s: float,
    wpm: int,
    count: Callable[[str], float],
) -> None:
    """Later passes replay the first pass's actions under the brief lines: pass q lasts
    D_q = max(D_1 / s^q, n STEP_S), at rate D_1 / D_q."""
    onsets(beats, wpm, count)
    i0 = beats.index(briefs[0]) - len(lines)
    d1 = sum(slot(beats, i) for i in range(i0, i0 + len(lines)))
    tau = [
        (a, b.onset - beats[i0].onset + b.speech * (position(a.word, b.text) or 0.0))
        for k, ln in enumerate(lines)
        for b in [beats[i0 + k]]
        for a in ln.actions
    ]
    dq = [max(d1 / s**q, len(tau) * STEP_S) for q in range(1, len(over))]
    groups = [[q] for q in range(len(dq))] if len(briefs) == len(dq) else [list(range(len(dq)))]
    for b, g in zip(briefs, groups, strict=True):
        i = beats.index(b)
        gap = GAP_S * (i < len(beats) - 1)
        b.pause = max(b.pause, sum(dq[q] for q in g) - b.speech - gap)
        onsets(beats, wpm, count)
        width, offset = slot(beats, i), 0.0
        for q in g:
            for a, t in tau:
                frac = round(min(0.99, (offset + t * dq[q] / d1) / width), 4)
                rate = round(min(64.0, d1 / dq[q]), 3)
                b.acts.append(_act(a, b.bookmark, over[q + 1], word=None, frac=frac, rate=rate))
            offset += dq[q]


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


def _schema(schema: dict[str, JsonValue], v: Any, where: str, errors: list[str]) -> None:
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


@dataclass
class Plan:
    """Scene being built: expanded script and visuals as (primitive, args, at)."""

    ds: DScene
    beats: list[Beat]
    visuals: list[tuple[str, dict[str, Any], str | None]]
    data: list[DataRequest]

    @property
    def length(self) -> float:
        return LEAD_S + sum(slot(self.beats, i) for i in range(len(self.beats)))


Views = dict[str, tuple[str, dict[str, Any], bool]]


def plan(
    ds: DScene,
    sel: Selection,
    catalog: Schemas,
    kernels: Schemas,
    wpm: int,
    views: Views,
    errors: list[str],
    count: Callable[[str], float] = words,
) -> Plan:
    """Scene part: script, catalog, data, action, cue, region and node checks;
    a visual naming a view continues its last visual, taking over its args and state."""
    where = f"scene {ds.id}"
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
    beats = script(ds, wpm, errors, count)
    marks = {b.bookmark: i for i, b in enumerate(beats)}
    acts: dict[int, list[tuple[int, dict[str, Any], str]]] = {}
    for i, b in enumerate(beats):
        for j, (k, a) in enumerate(b.acts):
            acts.setdefault(k, []).append((i, a, f"{b.where}.actions[{j}]"))
    if bad := sorted(set(acts) - set(range(len(ds.visuals)))):
        errors.append(f"{where}: actions on visuals {bad}; the scene has {len(ds.visuals)}")
    visuals: list[tuple[str, dict[str, Any], str | None]] = []
    lives: list[tuple[str, int, int, str]] = []
    parsed: dict[int, dict[str, Any]] = {}
    for k, v in enumerate(ds.visuals):
        w = f"{where}.visual[{k}]"
        if v.primitive not in catalog:
            errors.append(f"{w}: unknown primitive {v.primitive!r}; known: {sorted(catalog)}")
            continue
        if (args := _json(v.args, w, errors)) is None:
            continue
        if typo := [x for x in ("view", "until") if not isinstance(args.get(x, ""), str)]:
            errors.append(f"{w}: {typo[0]} must be a string")
            continue
        parsed[k] = args
        old = views.get(args["view"]) if "view" in args else None
        if old is not None and old[0] != v.primitive:
            errors.append(f"{w}: view {args['view']!r} continues a {old[0]}, not a {v.primitive}")
            continue
        if old is None:
            _schema(dict(catalog[v.primitive]), args, w, errors)
        else:
            own: dict[str, Any] = {x: args[x] for x in ("until", "replaces") if x in args}
            keep = ("view", *own)
            if diff := sorted(x for x in args if x not in keep and args[x] != old[1].get(x)):
                errors.append(f"{w}: a continued view keeps its args; drop {diff}")
            live = old[2] and v.at is None
            if live:
                old[1]["persist"] = True
            state = [
                {x: a[x] for x in ("do", "parts", "color") if x in a}
                for a in old[1]["actions"]
                if a["do"] != "indicate"
            ]
            drop = ("persist", "until", "replaces", "enter")
            base = {x: y for x, y in old[1].items() if x not in drop}
            fresh = {"enter": "none"} if live else {}
            args = base | fresh | {"resume": True, "actions": state} | own
        for ref in _refs(args):
            if not isinstance(ref["data"], int) or not 0 <= ref["data"] < len(ds.data):
                errors.append(f"{w}: array ref {ref} names no data request")
            if v.primitive != "matrix" and ref.get("part") is None:
                errors.append(f"{w}: array ref {ref} lacks part")
        t0 = marks.get(v.at, 0) if v.at else 0
        t1 = len(beats)
        if (until := args.get("until")) is not None:
            if until not in marks or marks[until] <= t0:
                errors.append(f"{w}: until {until!r} is no bookmark after at")
            else:
                t1 = marks[until]
        r = args.get("replaces")
        if r is not None and not (
            isinstance(r, int) and 0 <= r < k and v.at and parsed.get(r, {}).get("until") == v.at
        ):
            errors.append(f"{w}: replaces {r!r} names no earlier visual whose until is this at")
        schema = dict(catalog[v.primitive])
        action = {"$defs": schema.get("$defs", {}), "$ref": "#/$defs/Action"}
        for i, a, wa in acts.get(k, []):
            _schema(action, a, wa, errors)
            if not t0 <= i < t1:
                errors.append(f"{wa}: visual {k} is not on screen during this line")
        args["actions"] = [*args.get("actions", []), *(a for _, a, _ in acts.get(k, []))]
        lives.append((str(args.get("region", "main")), t0, t1, w))
        visuals.append((v.primitive, args, v.at))
        if "view" in args:
            views[args["view"]] = (v.primitive, args, False)
    for i, (r, a0, a1, wa) in enumerate(lives):
        for s, b0, b1, wb in lives[i + 1 :]:
            if (r == s or frozenset({r, s}) in OVERLAPS) and a0 < b1 and b0 < a1:
                errors.append(f"{wa} and {wb}: regions {r}, {s} overlap in time")
    if not ds.visuals:
        errors.append(f"{where}: no visuals")
    if loose := sorted(set(ds.nodes) - sel.ids):
        errors.append(f"{where}: nodes outside the selection {loose}")
    return Plan(ds, beats, visuals, data)


def static(p: Plan) -> list[str]:
    """Stretches longer than STATIC_S between estimated changes: entries, exits, actions."""
    if not p.visuals:
        return []
    bs, n = p.beats, len(p.beats)
    marks = {b.bookmark: b for b in bs}
    at = [marks[v[2]].onset if v[2] in marks else 0.0 for v in p.visuals]
    until = [marks[a["until"]].onset for _, a, _ in p.visuals if a.get("until") in marks]
    acts = [
        b.onset
        + (
            a["frac"] * slot(bs, i)
            if "frac" in a
            else b.speech * (position(a.get("word"), b.text) or 0.0)
        )
        for i, b in enumerate(bs)
        for _, a in b.acts
    ]
    out = []
    for t0, t1 in pairwise(sorted([0.0, *at, *until, *acts, p.length])):
        if t1 - t0 > STATIC_S:
            w = bs[max((k for k in range(n) if bs[k].onset <= t0 + 1e-9), default=0)].where
            out.append(
                f"scene {p.ds.id}: nothing changes for {t1 - t0:.0f} s from {w}; add actions"
            )
    return out


def build(
    d: Draft,
    sel: Selection,
    duration_s: float,
    catalog: Schemas,
    kernels: Schemas,
    wpm: int = 135,
    said: Said | None = None,
) -> tuple[Storyboard | None, list[str]]:
    """Validated Storyboard with durations in proportion to the estimated
    speech, gaps and pauses, or the errors; `said` gives the spoken form of lines."""
    if not d.scenes:
        return None, ["no scenes"]
    count = spoken(d, wpm, said)
    errors: list[str] = []
    plans: list[Plan] = []
    views: Views = {}
    for ds in d.scenes:
        p = plan(ds, sel, catalog, kernels, wpm, views, errors, count)
        plans.append(p)
        views = {k: (v, a, False) for k, (v, a, _) in views.items()}
        views |= {a["view"]: (v, a, "until" not in a) for v, a, _ in p.visuals if "view" in a}
    for p in plans:
        errors += static(p)
    total = sum(p.length for p in plans)
    if abs(total - duration_s) > TOLERANCE * duration_s:
        n = round((duration_s - total) * wpm / 60)
        errors.append(
            f"estimated length {total:.0f} s at {wpm} words per minute with gaps and pauses, "
            f"target {duration_s:.0f} s within {TOLERANCE:.0%}: {'add' if n > 0 else 'cut'} "
            f"about {abs(n)} words"
        )
    covered = sel.seeds & {i for s in d.scenes for i in s.nodes}
    if sel.seeds and len(covered) < COVERAGE * len(sel.seeds):
        errors.append(f"seed nodes not covered: {sorted(sel.seeds - covered)}")
    symbols = {s.latex: s.meaning for s in d.symbols} | {
        n.latex: n.meaning or n.name for n in sel.nodes if n.kind is NodeKind.SYMBOL and n.latex
    }
    scenes: list[Scene] = []
    for p in plans:
        try:
            scenes.append(
                Scene(
                    id=p.ds.id,
                    goal=p.ds.goal,
                    narration=tuple(
                        Line(text=b.text, bookmark=b.bookmark, pause_s=round(b.pause, 3))
                        for b in p.beats
                    ),
                    visuals=tuple(Visual(primitive=v, args=a, at=at) for v, a, at in p.visuals),
                    math=tuple(p.ds.math),
                    data=tuple(p.data),
                    nodes=tuple(p.ds.nodes),
                    duration_s=round(duration_s * p.length / total, 3) if total else 1.0,
                )
            )
        except ValidationError as e:
            errors.extend(f"scene {p.ds.id}: {x['msg']}" for x in e.errors())
    refs = [x for n in (*sel.nodes, *sel.context) if n.latex for x in (n.latex, *parts(n.latex))]
    errors += [
        f"scene {s.id}: ${f}$ is not a node formula, a list of them, or a derive step "
        "equivalent to the one before"
        for s in scenes
        for f in untraced(s, refs)
    ]
    if errors:
        return None, errors
    try:
        board = Storyboard(title=d.title, scenes=tuple(scenes), symbols=symbols)
    except ValidationError as e:
        return None, [x["msg"] for x in e.errors()]
    return board, []
