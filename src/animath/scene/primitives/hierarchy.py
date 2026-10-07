# ruff: noqa: N806
import re
from dataclasses import dataclass, field, replace
from functools import lru_cache, partial
from typing import Any, ClassVar, Literal, NamedTuple, get_args

import numpy as np
from manim import (
    BLACK,
    BLUE,
    BLUE_A,
    BLUE_E,
    GREY,
    ORANGE,
    ORIGIN,
    RED,
    WHITE,
    YELLOW,
    Animation,
    AnimationGroup,
    DashedVMobject,
    FadeIn,
    ManimColor,
    Mobject,
    Rectangle,
    Text,
    Transform,
    VGroup,
    VMobject,
    Wait,
    interpolate_color,
    smooth,
    there_and_back,
)
from matplotlib import colormaps
from numpy.typing import NDArray
from pydantic import Field

from animath.core.errors import AnimateError
from animath.core.schemas import Model
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, ArrayRef, Context, Cue, Primitive

Action = Literal[
    "select",
    "footprint",
    "ring",
    "clear",
    "colour",
    "rotate",
    "split",
    "zero",
    "eliminate",
    "schur",
    "fill",
    "drop",
    "wave",
    "coarsen",
    "top",
]
View = Literal["plate", "operator"]
Key = tuple[Any, ...]
PHASE = {"rotate": 1, "split": 2, "zero": 3, "eliminate": 4, "schur": 5, "fill": 6}
SPLIT, ZERO, ELIM, FILL = 2, 3, 4, 6
SIDE, GAP, CAP, RUN, MIN_DT = 4.0, 0.8, 0.6, 1.0, 0.1
AMBER = "#FFBF00"
PALETTE = tuple(ManimColor.from_rgb(c[:3]).to_hex() for c in colormaps["tab20"](np.arange(20)))
ARRAYS = ("box", "range", "near_ptr", "near", "far_ptr", "far", "stage", "schur", "fill", "active")
PART = re.compile(r"(?:([ts])|cluster:(\d+)|colour:(\d+)|block:(\d+),(\d+))?")
TAKES = dict(colour=("cluster", "colour"), wave=("colour",), drop=("block",), coarsen=(), top=())


def nodes(lvl: int) -> range:
    return range(2**lvl - 1, 2 ** (lvl + 1) - 1)


def below(t: int, lvl: int) -> tuple[int, int]:
    """First and last descendant at level lvl of a cluster at level ell(t) <= lvl."""
    d = lvl - ((t + 1).bit_length() - 1)
    return (t + 1) * 2**d - 1, (t + 2) * 2**d - 2


class Part(Model):
    cluster: int | Literal["t", "s"] | None = Field(
        None,
        description='BFS cluster id of the current level; "t" interior, "s" its later neighbour',
    )
    colour: int | None = Field(None, ge=0)
    block: tuple[int, int] | None = None


class Step(Model):
    do: Action = Field(description="verb, as in the primitive's description")
    part: Part = Part()


def parse(sel: str) -> Part:
    """Part named by a selector t, s, cluster:k, colour:c or block:a,b; empty: none."""
    g = PART.fullmatch(sel)
    if g is None:
        raise AnimateError(
            f"hierarchy: no part {sel!r}; parts: t, s, cluster:k, colour:c, block:a,b"
        )
    ts, k, c, a, b = g.groups()
    return Part.model_validate({"cluster": ts or k, "colour": c, "block": a and (a, b)})


class HierarchyArgs(Args):
    data: int = Field(0, ge=0, description="index of the h2.rss request in scene.data")
    level: int | None = Field(None, ge=0, description="start level; default the leaves")
    done: int = Field(0, ge=0, description="stages of the start level already eliminated")
    coloured: bool = False
    views: tuple[View, ...] = Field(("plate", "operator"), min_length=1, max_length=2)
    steps: tuple[Step, ...] = ()


class Spec(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float
    fill: str
    fo: float
    stroke: str = WHITE.to_hex()
    sw: float = 0.0
    z: int = 0
    dashed: bool = False
    text: str = ""


@dataclass(frozen=True)
class State:
    level: int
    phase: dict[int, int] = field(default_factory=dict)
    coloured: frozenset[int] = frozenset()
    marks: frozenset[tuple[int, str]] = frozenset()
    dropped: frozenset[tuple[int, int]] = frozenset()
    current: int | None = None
    top: bool = False


class Walk:
    """The h2.rss DataSet as levels, near graph, stage rows and fill pairs."""

    def __init__(self, a: dict[str, NDArray[Any]]) -> None:
        box, self.stage = a["box"], a["stage"].astype(int)
        self.lo, self.hi, self.size = box[:, 0], box[:, 1], np.diff(a["range"], axis=1)[:, 0]
        self.near = [
            a["near"][i:j].tolist()
            for i, j in zip(a["near_ptr"][:-1], a["near_ptr"][1:], strict=True)
        ]
        self.far = [
            a["far"][i:j].tolist() for i, j in zip(a["far_ptr"][:-1], a["far_ptr"][1:], strict=True)
        ]
        self.depth, self.top = (len(box) + 1).bit_length() - 2, int(a["active"][-1, 0])
        self.row = {int(t): i for i, t in enumerate(self.stage[:, 0])}
        self.carried: dict[int, set[tuple[int, int]]] = {}
        for lvl, s, u in a["fill"].astype(int).tolist():
            self.carried.setdefault(lvl, set()).add((s, u))
        self.made: dict[int, list[tuple[int, int]]] = {}
        for i, s, u, f in a["schur"].astype(int).tolist():
            if f:
                self.made.setdefault(i, []).append((s, u))

    @classmethod
    def load(cls, ctx: Context, data: int) -> "Walk":
        return cls({k: ctx.array(ArrayRef(data=data, array=k)) for k in ARRAYS})

    def rows(self, lvl: int) -> list[int]:
        return [i for i, r in enumerate(self.stage) if r[1] == lvl]

    def n0(self, t: int) -> int:
        """Active size of t at the start of its level."""
        if t in self.row:
            return int(self.stage[self.row[t], 3])
        if 2 * t + 1 >= len(self.size):
            return int(self.size[t])
        return self.k(2 * t + 1) + self.k(2 * t + 2)

    def k(self, t: int) -> int:
        return int(self.stage[self.row[t], 4]) if t in self.row else self.n0(t)

    def colour(self, t: int) -> int:
        return int(self.stage[self.row[t], 2]) if t in self.row else 0

    def ring(self, t: int) -> list[int]:
        return sorted({u for s in self.near[t] for u in self.near[s]} - set(self.near[t]))

    def pick(self, lvl: int) -> tuple[int, int]:
        """t: first stage of the level with a largest near list; s: next stage in N(t)."""
        rows = self.rows(lvl)
        if not rows:
            raise AnimateError(f"hierarchy: level {lvl} has no stages")
        i = max(rows, key=lambda j: (len(self.near[self.stage[j, 0]]), -j))
        t = int(self.stage[i, 0])
        later = [int(self.stage[j, 0]) for j in rows if j > i and self.stage[j, 0] in self.near[t]]
        return t, (later or [s for s in self.near[t] if s != t] or [t])[0]

    def start(self, a: HierarchyArgs) -> State:
        lvl = self.depth if a.level is None else a.level
        if not self.top <= lvl <= self.depth:
            raise AnimateError(f"hierarchy: level {lvl} outside [{self.top}, {self.depth}]")
        rows = self.rows(lvl)
        if a.done > len(rows):
            raise AnimateError(f"hierarchy: level {lvl} has {len(rows)} stages, done={a.done}")
        return State(
            lvl,
            {int(self.stage[i, 0]): FILL for i in rows[: a.done]},
            frozenset(nodes(lvl)) if a.coloured else frozenset(),
        )


Flash = tuple[tuple[str, *tuple[int, ...]], ...]


def advance(w: Walk, st: State, s: Step) -> tuple[State, Flash]:
    """Next state after step s, and the transient flashes it shows."""
    lvl, T, p = st.level, nodes(st.level), s.part
    if bad := sorted(p.model_dump(exclude_none=True).keys() - {*TAKES.get(s.do, ("cluster",))}):
        raise AnimateError(f"hierarchy: {s.do} takes no {bad[0]} part")

    def cluster() -> int:
        ref = p.cluster if p.cluster is not None else st.current
        t = w.pick(lvl)[ref == "s"] if ref is None or isinstance(ref, str) else ref
        if t not in T:
            raise AnimateError(f"hierarchy: {s.do}: cluster {t} is not on level {lvl}")
        return t

    if s.do in ("select", "footprint", "ring"):
        t = cluster()
        keep = {m for m in st.marks if s.do != "select" or m[1] != "select"}
        return replace(st, marks=frozenset(keep | {(t, s.do)}), current=t), ()
    if s.do == "clear":
        gone = {cluster()} if p.cluster is not None else {m[0] for m in st.marks}
        return replace(st, marks=frozenset(m for m in st.marks if m[0] not in gone)), ()
    if s.do == "colour":
        cls = {t for t in T if p.colour in (None, w.colour(t))}
        more = cls if p.cluster is None else {cluster()}
        if not more:
            raise AnimateError(f"hierarchy: colour: no cluster of colour {p.colour} on level {lvl}")
        return replace(st, coloured=st.coloured | more), ()
    if s.do in PHASE:
        t = cluster()
        if t not in w.row:
            raise AnimateError(f"hierarchy: {s.do}: cluster {t} has no stage")
        phase = {**st.phase, t: max(st.phase.get(t, 0), PHASE[s.do])}
        return replace(st, phase=phase, current=t), ((s.do, t),)
    if s.do == "drop":
        if p.block is None or p.block not in shown(w, st):
            raise AnimateError(f"hierarchy: drop: {p.block} is not a fill block on view")
        return replace(st, dropped=st.dropped | {p.block}), (("drop", *p.block),)
    if s.do == "wave":
        rows = [i for i in w.rows(lvl) if st.phase.get(int(w.stage[i, 0]), 0) < FILL]
        c = p.colour if p.colour is not None else min((int(w.stage[i, 2]) for i in rows), default=0)
        ts = [int(w.stage[i, 0]) for i in rows if w.stage[i, 2] == c]
        if not ts:
            raise AnimateError(f"hierarchy: wave: no pending stage of colour {c} on level {lvl}")
        return replace(st, phase={**st.phase, **dict.fromkeys(ts, FILL)}), (("class", c),)
    if s.do == "coarsen":
        if lvl <= w.top:
            raise AnimateError(f"hierarchy: coarsen: level {lvl} is the top")
        return State(lvl - 1), ()
    if lvl != w.top or st.top:
        raise AnimateError(f"hierarchy: top: level {lvl} is not the undone top {w.top}")
    return replace(st, top=True, marks=frozenset()), ()


def shown(w: Walk, st: State) -> set[tuple[int, int]]:
    made = (u for t, ph in st.phase.items() if ph >= FILL for u in w.made.get(w.row[t], []))
    return (w.carried.get(st.level, set()) | set(made)) - st.dropped


def shade(lvl: int, depth: int) -> str:
    return interpolate_color(BLUE_E, BLUE_A, lvl / max(depth, 1)).to_hex()


def draw(
    w: Walk, st: State, views: tuple[View, ...], flashes: Flash = ()
) -> tuple[dict[Key, Spec], dict[Key, Spec]]:
    """Specs of every item in state st, and of the transient flashes."""
    T = nodes(st.level)
    x0 = -(len(views) * SIDE + (len(views) - 1) * GAP) / 2
    corner = {v: (x0 + i * (SIDE + GAP), SIDE / 2) for i, v in enumerate(views)}
    out: dict[Key, Spec] = {
        ("frame",): Spec(x0, -SIDE / 2 - CAP, -x0, SIDE / 2, BLACK.to_hex(), 0.0, z=-1)
    }
    fl: dict[Key, Spec] = {}
    hi, lo = YELLOW.to_hex(), WHITE.to_hex()
    if "plate" in corner:
        X, Y = corner["plate"]
        a, ext = w.lo[0], w.hi[0] - w.lo[0]
        sc = SIDE / ext.max()
        off = (SIDE - ext * sc) / 2

        def box(t: int) -> tuple[float, float, float, float]:
            p, q = off + (w.lo[t] - a) * sc, off + (w.hi[t] - a) * sc
            return X + p[0], Y - SIDE + p[1], X + q[0], Y - SIDE + q[1]

        for t in T:
            c = PALETTE[w.colour(t) % len(PALETTE)] if t in st.coloured else GREY.to_hex()
            out["box", t] = Spec(
                *box(t), c, 0.3 if st.phase.get(t, 0) >= ELIM else 0.85, lo, 1.0, 1
            )
            if SPLIT <= st.phase.get(t, 0) < ELIM:
                bl, bb, br, bt = box(t)
                xm, ym = bl + (br - bl) * w.k(t) / w.n0(t), bb + (bt - bb) / 4
                rc = (RED if st.phase[t] < ZERO else WHITE).to_hex()
                out["psplit", t, 0] = Spec(bl, bb, xm, ym, BLUE.to_hex(), 1.0, z=2)
                out["psplit", t, 1] = Spec(xm, bb, br, ym, rc, 1.0, z=2)
        for t, f in sorted(st.marks):
            if f == "select":
                out["psel", t] = Spec(*box(t), lo, 0.0, hi, 6.0, 4)
            for s in w.near[t] if f == "footprint" else []:
                out["pnear", t, s] = Spec(*box(s), lo, 0.2, lo, 3.0, 3)
            for u in w.ring(t) if f == "ring" else []:
                out["pring", t, u] = Spec(*box(u), lo, 0.0, lo, 3.0, 3, True)
        for kind, *x in flashes:
            for t in [u for u in T if w.colour(u) == x[0]] if kind == "class" else []:
                fl["pwave", t] = Spec(*box(t), hi, 0.5, hi, 4.0, 7)
            for t in x if kind == "drop" else []:
                fl["pdrop", t] = Spec(*box(t), AMBER, 0.5, AMBER, 4.0, 7)
        ncol = len({w.colour(t) for t in T if t in w.row})
        text = "dense top" if st.top else f"{ncol} colours" if ncol else "top level"
        out["pcap",] = Spec(
            X,
            Y - SIDE - CAP,
            X + SIDE,
            Y - SIDE - 0.1,
            lo,
            1.0,
            lo,
            z=8,
            text=f"level {st.level}: {len(T)} clusters, {text}",
        )
    if "operator" in corner:
        X, Y = corner["operator"]
        n0 = {t: w.n0(t) for t in T}
        wd = {t: w.k(t) if st.phase.get(t, 0) >= ELIM else n0[t] for t in T}
        o = dict(zip(T, np.cumsum([0, *wd.values()])[:-1].tolist(), strict=True))
        sg, N = SIDE / sum(n0.values()), sum(wd.values())

        def rect(r0: float, r1: float, c0: float, c1: float) -> tuple[float, float, float, float]:
            return X + c0 * sg, Y - r1 * sg, X + c1 * sg, Y - r0 * sg

        def span(t: int) -> tuple[float, float]:
            a, b = below(t, st.level)
            return o[a], o[b] + wd[b]

        out["bg",] = Spec(*rect(0, N, 0, N), shade(st.level, w.depth), 1.0)
        if st.top:
            out["top",] = Spec(*rect(0, N, 0, N), ORANGE.to_hex(), 1.0, BLACK.to_hex(), 2.0, 4)
        for lam in range(st.level):
            for A in nodes(lam):
                for B in w.far[A]:
                    out["far", A, B] = Spec(
                        *rect(*span(A), *span(B)), shade(lam, w.depth), 1.0, z=1
                    )
        for a, b in shown(w, st) if not st.top else []:
            out["fill", a, b] = Spec(*rect(*span(a), *span(b)), AMBER, 1.0, z=2)
        for t in T:
            ph, (r0, r1), r = st.phase.get(t, 0), span(t), o[t] + w.k(t)
            if ZERO <= ph < ELIM:
                out["zero", t, 0] = Spec(*rect(r, r1, 0, N), lo, 1.0, z=3)
                out["zero", t, 1] = Spec(*rect(0, N, r, r1), lo, 1.0, z=3)
            for j, (u0, u1, col) in enumerate(
                ((r0, r, BLUE.to_hex()), (r, r1, RED.to_hex())) if SPLIT <= ph < ELIM else ()
            ):
                out["split", t, j, 0] = Spec(*rect(u0, u1, 0, N), col, 0.45, col, 2.0, 5)
                out["split", t, j, 1] = Spec(*rect(0, N, u0, u1), col, 0.45, col, 2.0, 5)
            for s in w.near[t] if not st.top else []:
                out["near", t, s] = Spec(
                    *rect(*span(t), *span(s)), ORANGE.to_hex(), 1.0, BLACK.to_hex(), 0.5, 4
                )
        for t, f in sorted(st.marks):
            if f == "select":
                out["osel", t, 0] = Spec(*rect(*span(t), 0, N), lo, 0.0, hi, 4.0, 6)
                out["osel", t, 1] = Spec(*rect(0, N, *span(t)), lo, 0.0, hi, 4.0, 6)
            for s in w.near[t] if f == "footprint" else []:
                out["onear", t, s, 0] = Spec(*rect(*span(s), 0, N), lo, 0.12, z=5)
                out["onear", t, s, 1] = Spec(*rect(0, N, *span(s)), lo, 0.12, z=5)
        for kind, *x in flashes:
            t = x[0]
            if kind == "drop":
                bl, bb, br, bt = rect(*span(t), *span(x[1]))
                h, cx, cy = max(br - bl, bt - bb, 0.3) / 2, (bl + br) / 2, (bb + bt) / 2
                fl["odrop", *x] = Spec(cx - h, cy - h, cx + h, cy + h, AMBER, 0.0, AMBER, 4.0, 7)
            if kind == "rotate":
                fl["rot", t, 0] = Spec(*rect(*span(t), 0, N), lo, 0.6, z=7)
                fl["rot", t, 1] = Spec(*rect(0, N, *span(t)), lo, 0.6, z=7)
            for a in w.near[t] if kind == "schur" else []:
                for b in w.near[t]:
                    fl["schur", a, b] = Spec(*rect(*span(a), *span(b)), hi, 0.7, z=7)
        out["ocap",] = Spec(
            X,
            Y - SIDE - CAP,
            X + SIDE,
            Y - SIDE - 0.1,
            lo,
            1.0,
            lo,
            z=8,
            text=f"{'dense top, ' if st.top else ''}N = {N}",
        )
    return out, fl


def up(key: Key, new: dict[Key, Spec]) -> Spec | None:
    """Where a vanishing item goes: into its parent's block or box, or the dense top."""
    if key[0] in ("near", "fill", "box"):
        p = tuple((i - 1) // 2 for i in key[1:])
        for k in (key[0], *p), ("near", *p), ("top",):
            if k in new and (k[0] == key[0] or key[0] != "box"):
                return new[k]
    return None


@lru_cache(maxsize=4096)
def mobject(sp: Spec) -> VMobject:
    if sp.text:
        m: VMobject = Text(sp.text, font_size=28, color=sp.stroke)
        m.scale(min(1.0, 0.9 * (sp.x1 - sp.x0) / m.width))
    else:
        m = Rectangle(width=max(sp.x1 - sp.x0, 1e-4), height=max(sp.y1 - sp.y0, 1e-4))
        m.set_fill(sp.fill, sp.fo).set_stroke(sp.stroke, sp.sw, 1.0 if sp.sw else 0.0)
        if sp.dashed:
            m = DashedVMobject(m, num_dashes=24)
    return m.move_to(((sp.x0 + sp.x1) / 2, (sp.y0 + sp.y1) / 2, 0.0)).set_z_index(sp.z)


def named(w: Walk, st: State, views: tuple[View, ...], p: Part) -> list[Key]:
    """Keys of the items a part names in state st: boxes of its clusters on the plate, else their
    diagonal blocks; an operator block."""
    if p.block is not None:
        return [(k, *p.block) for k in ("near", "far", "fill")]
    lvl = st.level
    if p.colour is not None:
        ts = [t for t in nodes(lvl) if t in w.row and w.colour(t) == p.colour]
    elif isinstance(p.cluster, str):
        ts = [w.pick(lvl)[p.cluster == "s"]] if w.rows(lvl) else []
    else:
        ts = [] if p.cluster is None else [p.cluster]
    return [("box", t) if "plate" in views else ("near", t, t) for t in ts]


class Board(VGroup):
    """The visual in its current state: items keyed by role, morphed by per-item Transforms in
    one AnimationGroup over the board; named parts are groups of the current items."""

    def __init__(self, w: Walk, st: State, views: tuple[View, ...]) -> None:
        self.w, self.st, self.views, self.cur = w, st, views, draw(w, st, views)[0]
        self.items = {k: mobject(sp).copy() for k, sp in self.cur.items()}
        super().__init__(*self.items.values())
        self.anchor, self.dead, self.parts = self.cur["frame",], list[Key](), dict[str, VGroup]()

    def make(self, sp: Spec) -> VMobject:
        a, f = self.items["frame",], self.anchor
        k = a.width / (f.x1 - f.x0)
        c = np.array(((f.x0 + f.x1) / 2, (f.y0 + f.y1) / 2, 0.0))
        return mobject(sp).copy().scale(k, about_point=ORIGIN).shift(a.get_center() - k * c)

    def move(self, key: Key, to: Spec | None, mode: str) -> Animation:
        x = self.items.get(key)
        if x is None:
            assert to is not None
            x = self.items[key] = self.make(to).set_opacity(0.0)
            self.add(x)
        if mode != "keep":
            self.dead.append(key)
        y = self.make(to) if to is not None else x.copy().set_opacity(0.0)
        return Transform(x, y, rate_func=there_and_back if mode == "flash" else smooth)

    def go(self, steps: list[Step]) -> Animation:
        """Morph into the state after `steps`; items gone from the last state are removed."""
        self.remove(*(self.items.pop(k) for k in self.dead))
        self.dead.clear()
        st, fl = self.st, Flash()
        for s in steps:
            st, f = advance(self.w, st, s)
            fl += f
        new, flash = draw(self.w, st, self.views, fl)
        moves: list[tuple[Key, Spec | None, str]] = [
            (k, new[k], "keep") for k in new if self.cur.get(k) != new[k]
        ]
        moves += [(k, up(k, new), "drop") for k in self.cur if k not in new]
        moves += [(("flash", *k), sp, "flash") for k, sp in flash.items()]
        anims = [self.move(*x) for x in moves]
        self.st, self.cur = st, new
        self.sync()
        return AnimationGroup(*anims, group=self) if anims else Wait()

    def part(self, sel: str) -> VGroup:
        """Group of the items `sel` names, refilled on every state change."""
        if sel not in self.parts:
            parse(sel)
            self.parts[sel] = VGroup()
            self.add(self.parts[sel])
            self.sync()
        return self.parts[sel]

    def sync(self) -> None:
        for sel, g in self.parts.items():
            keys = named(self.w, self.st, self.views, parse(sel))
            g.remove(*g.submobjects).add(*(self.items[k] for k in keys if k in self.cur))


class Hierarchy(Primitive[HierarchyArgs]):
    """Plate and block-operator views of an h2.rss DataSet. Verbs walk its factorisation on the
    current level: select, footprint (N(t)), ring (two hops), clear, and the stage phases rotate,
    split, zero, eliminate, schur, fill take a cluster part (default the current one); colour a
    cluster or colour class (default all); wave a colour class (default the next); drop a fill
    block; coarsen and top none. Parts: t (a stage with most near neighbours), s (its next
    neighbour), cluster:k, colour:c, block:a,b. `steps` share the visual's life equally; for
    word timing and views use actions instead."""

    name = "hierarchy"
    args = HierarchyArgs
    verbs: ClassVar[tuple[str, ...]] = get_args(Action)

    def build(self, a: HierarchyArgs, ctx: Context, cell: Box) -> Mobject:
        w = Walk.load(ctx, a.data)
        if "plate" in a.views and w.lo.shape[1] != 2:
            raise AnimateError(f"hierarchy: the plate view needs 2-D points, got {w.lo.shape[1]}-D")
        st = w.start(a)
        for s in a.steps:
            st = advance(w, st, s)[0]
        return Board(w, w.start(a), a.views)

    def cues(self, m: Mobject, a: HierarchyArgs, t0: float, t1: float) -> list[Cue]:
        assert isinstance(m, Board)
        dt = (t1 - t0) / (len(a.steps) + 1)
        if a.steps and dt < MIN_DT:
            raise AnimateError(f"hierarchy: {len(a.steps)} steps in {t1 - t0:.2f} s")
        return [Cue(t0, RUN, partial(FadeIn, m))] + [
            Cue(t0 + (i + 1) * dt, min(RUN, 0.8 * dt), partial(m.go, [s]))
            for i, s in enumerate(a.steps)
        ]

    def part(self, m: Mobject, a: HierarchyArgs, sel: str) -> Mobject:
        assert isinstance(m, Board)
        return m.part(sel)

    def act(self, m: Mobject, a: HierarchyArgs, verb: str, parts: list[str]) -> Animation:
        assert isinstance(m, Board)
        return m.go([Step.model_validate({"do": verb, "part": parse(s)}) for s in parts or [""]])
