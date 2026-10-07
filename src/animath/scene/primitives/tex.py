from functools import partial

from manim import ORIGIN, MathTex, Mobject, Tex, TransformMatchingTex, VGroup
from pydantic import Field

from animath.scene.layout import Box
from animath.scene.primitives.base import Args, Context, Cue, Primitive, enter


class TextArgs(Args):
    text: str = Field(min_length=1)


class EquationArgs(Args):
    latex: str = Field(min_length=1)


class DeriveArgs(Args):
    steps: list[str] = Field(min_length=2)


class Text(Primitive[TextArgs]):
    """LaTeX text mode; inline math in $...$."""

    name = "text"
    args = TextArgs

    def build(self, a: TextArgs, ctx: Context, cell: Box) -> Mobject:
        return Tex(a.text)


class Equation(Primitive[EquationArgs]):
    name = "equation"
    args = EquationArgs

    def build(self, a: EquationArgs, ctx: Context, cell: Box) -> Mobject:
        return MathTex(a.latex)


class Derive(Primitive[DeriveArgs]):
    """Chain of equalities; parts marked {{...}} are matched across steps."""

    name = "derive"
    args = DeriveArgs

    @staticmethod
    def times(n: int, t0: float, t1: float) -> list[float]:
        """Start of each of n steps sharing [t0, t1) equally."""
        return [t0 + k * (t1 - t0) / n for k in range(n)]

    def build(self, a: DeriveArgs, ctx: Context, cell: Box) -> Mobject:
        return VGroup(*(MathTex(s).move_to(ORIGIN) for s in a.steps))

    def cues(self, m: Mobject, a: DeriveArgs, t0: float, t1: float) -> list[Cue]:
        t = self.times(len(m), t0, t1)
        return [Cue(t[0], 1.0, partial(enter, m[0]))] + [
            Cue(t[k], 1.0, partial(TransformMatchingTex, m[k - 1], m[k])) for k in range(1, len(m))
        ]

    def last(self, m: Mobject) -> Mobject:
        return m[-1]
