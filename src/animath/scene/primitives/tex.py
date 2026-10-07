import re
from functools import partial

from manim import ORIGIN, Animation, MathTex, Mobject, Tex, TransformMatchingTex, VGroup
from pydantic import Field

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives.base import ENTER_S, Args, Context, Cue, Primitive, enter, path

CONTROL = re.compile(r"\\[A-Za-z]+")
SHOWN = "animath_shown"


def whole(tex: str, a: int, b: int) -> bool:
    """[a, b) cuts no control word of `tex`."""
    return not any(x < a < y or x < b < y for x, y in (m.span() for m in CONTROL.finditer(tex)))


class Isolate:
    """MathTex isolating substrings only where they cut no control word (`t` not in `\\to`)."""

    def _locate_first_match(self, subs: list[str], text: str) -> re.Match[str] | None:
        hits = [
            (m.start(), -len(s), s)
            for s in subs
            for m in re.finditer(re.escape(s), text)
            if s and whole(text, *m.span())
        ]
        if not hits:
            return None
        i, _, s = min(hits)
        return re.match(rf"(.{{{i}}})({re.escape(s)})(.*)", text, flags=re.DOTALL)


class IsoMathTex(Isolate, MathTex):  # type: ignore[misc]
    pass


class IsoTex(Isolate, Tex):  # type: ignore[misc]
    pass


def selectors(a: Args) -> list[str]:
    return sorted({s for x in a.actions for s in x.parts})


def tex_part(m: Mobject, sel: str) -> Mobject:
    """All occurrences of the TeX `sel` isolated at build, else a dotted index path."""
    groups = getattr(m, "id_to_vgroup_dict", {})
    hit = [groups[i] for t, i in getattr(m, "matched_strings_and_ids", []) if t == sel]
    return VGroup(*hit) if hit else path(m, sel)


class TextArgs(Args):
    text: str = Field(min_length=1)


class EquationArgs(Args):
    latex: str = Field(min_length=1)


class DeriveArgs(Args):
    steps: list[str] = Field(min_length=2)


class Text(Primitive[TextArgs]):
    """LaTeX text mode; inline math in $...$. Parts: TeX substrings."""

    name = "text"
    args = TextArgs

    def build(self, a: TextArgs, ctx: Context, cell: Box) -> Mobject:
        return IsoTex(a.text, substrings_to_isolate=selectors(a))

    def part(self, m: Mobject, a: TextArgs, sel: str) -> Mobject:
        return tex_part(m, sel)


class Equation(Primitive[EquationArgs]):
    """Display formula. Parts: TeX substrings, e.g. `L_{21}`; `show` writes one term."""

    name = "equation"
    args = EquationArgs

    def build(self, a: EquationArgs, ctx: Context, cell: Box) -> Mobject:
        return IsoMathTex(a.latex, substrings_to_isolate=selectors(a))

    def part(self, m: Mobject, a: EquationArgs, sel: str) -> Mobject:
        return tex_part(m, sel)


class Derive(Primitive[DeriveArgs]):
    """Chain of equalities; parts marked {{...}} are matched across steps. Steps share the
    time between entry and exit equally, unless `next` actions advance them. Verb: next."""

    name = "derive"
    args = DeriveArgs
    verbs = timed = ("next",)

    @staticmethod
    def times(n: int, t0: float, t1: float) -> list[float]:
        """Start of each of n steps sharing [t0, t1) equally."""
        return [t0 + k * (t1 - t0) / n for k in range(n)]

    def build(self, a: DeriveArgs, ctx: Context, cell: Box) -> Mobject:
        m = VGroup(*(MathTex(s).move_to(ORIGIN) for s in a.steps))
        setattr(m, SHOWN, 0)
        return m

    def cues(self, m: Mobject, a: DeriveArgs, t0: float, t1: float) -> list[Cue]:
        first = Cue(t0, ENTER_S, partial(enter, m[0]))
        n = sum(x.do == "next" for x in a.actions)
        if n >= len(m):
            raise AnimateError(f"{n} next actions for {len(m)} steps")
        if n:
            return [first]
        t, r = self.times(len(m), t0, t1), min(1.0, 0.8 * (t1 - t0) / len(m))
        step = partial(self.act, m, a, "next", [])
        return [first] + [Cue(t[k], r, step) for k in range(1, len(m))]

    def act(self, m: Mobject, a: DeriveArgs, verb: str, parts: list[str]) -> Animation:
        k = getattr(m, SHOWN) + 1
        setattr(m, SHOWN, k)
        return TransformMatchingTex(m[k - 1], m[k])

    def first(self, m: Mobject) -> Mobject:
        return m[0]

    def last(self, m: Mobject) -> Mobject:
        return m[getattr(m, SHOWN)]
