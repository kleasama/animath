from functools import partial
from typing import Self

from manim import DOWN, LEFT, RIGHT, YELLOW, Animation, Mobject, Rectangle, Text, VGroup
from pydantic import Field, model_validator

from animath.scene.layout import Box
from animath.scene.primitives.base import Args, Context, Cue, Primitive, enter

FONT = "DejaVu Sans Mono"


def goto(cursor: Mobject, row: Mobject) -> Animation:
    return cursor.animate.set_y(row.get_y()).build()


class TraceArgs(Args):
    lines: list[str] = Field(
        min_length=1, description="plain monospace text, not TeX; leading spaces indent"
    )
    steps: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _steps(self) -> Self:
        bad = [k for k in self.steps if not 0 <= k < len(self.lines)]
        if bad:
            raise ValueError(f"steps outside lines: {bad}")
        return self


class Trace(Primitive[TraceArgs]):
    """Pseudo-code listing; a cursor visits lines `steps` uniformly over the cue interval."""

    name = "trace"
    args = TraceArgs

    def build(self, a: TraceArgs, ctx: Context, cell: Box) -> Mobject:
        probe = Text("Mg", font=FONT, font_size=24)
        em = probe.width / 2
        rows = VGroup(*(Text(s.strip() or ".", font=FONT, font_size=24) for s in a.lines)).arrange(
            DOWN, aligned_edge=LEFT, buff=0.2
        )
        for row, s in zip(rows, a.lines, strict=True):
            row.shift(RIGHT * em * (len(s) - len(s.lstrip())))
            row.set_opacity(1.0 if s.strip() else 0.0)
        cursor = Rectangle(
            width=rows.width + 0.3, height=probe.height + 0.15, color=YELLOW
        ).set_fill(YELLOW, 0.15)
        cursor.move_to(rows).set_y(rows[a.steps[0]].get_y())
        return VGroup(rows, cursor)

    def cues(self, m: Mobject, a: TraceArgs, t0: float, t1: float) -> list[Cue]:
        rows, cursor = m
        dt = (t1 - t0) / len(a.steps)
        return [Cue(t0, 1.0, lambda: enter(m))] + [
            Cue(t0 + i * dt, 0.4, partial(goto, cursor, rows[k]))
            for i, k in enumerate(a.steps[1:], 1)
        ]
