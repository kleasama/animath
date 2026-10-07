from functools import partial
from typing import Self

from manim import DOWN, LEFT, RIGHT, YELLOW, Animation, Mobject, Rectangle, Text, VGroup
from pydantic import Field, model_validator

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, Context, Cue, Primitive, enter, path

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
    """Pseudo-code listing; the cursor starts at line steps[0] and visits the other steps
    uniformly over the visual's life, unless `goto` actions move it. Parts: line:k (0-based),
    cursor. Verb: goto with one line part."""

    name = "trace"
    args = TraceArgs
    verbs = timed = ("goto",)

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
        if any(x.do == "goto" for x in a.actions):
            return [Cue(t0, 1.0, lambda: enter(m))]
        return [Cue(t0, 1.0, lambda: enter(m))] + [
            Cue(t0 + i * dt, 0.4, partial(goto, cursor, rows[k]))
            for i, k in enumerate(a.steps[1:], 1)
        ]

    def part(self, m: Mobject, a: TraceArgs, sel: str) -> Mobject:
        rows, cursor = m
        kind, _, k = sel.partition(":")
        if sel == "cursor":
            return cursor
        if kind == "line" and k.isdigit() and int(k) < len(rows):
            return rows[int(k)]
        return path(m, sel)

    def act(self, m: Mobject, a: TraceArgs, verb: str, parts: list[str]) -> Animation:
        if len(parts) != 1 or not parts[0].startswith("line:"):
            raise AnimateError("goto needs one part line:k")
        return goto(m[1], self.part(m, a, parts[0]))
