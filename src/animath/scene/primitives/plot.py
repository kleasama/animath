import math
from typing import Any

import numpy as np
from manim import (
    BLUE,
    DL,
    DOWN,
    GREEN,
    PURPLE,
    RED,
    RIGHT,
    UR,
    YELLOW,
    Axes,
    LogBase,
    Mobject,
    Tex,
    VGroup,
    VMobject,
)
from numpy.typing import NDArray
from pydantic import Field

from animath.core.errors import AnimateError
from animath.core.schemas import Model
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, Context, Primitive, Vector

COLORS = (BLUE, YELLOW, GREEN, RED, PURPLE)


class Series(Model):
    x: Vector
    y: Vector
    label: str | None = None


class PlotArgs(Args):
    series: list[Series] = Field(min_length=1, max_length=len(COLORS))
    xlabel: str = ""
    ylabel: str = ""
    logy: bool = False


def ticks(lo: float, hi: float) -> tuple[float, float, float]:
    """Range [a, b] ⊇ [lo, hi] with step h ∈ {1, 2, 5}·10^k and (b - a)/h ≤ 10."""
    if hi <= lo:
        lo, hi = lo - 0.5, hi + 0.5
    raw = (hi - lo) / 10
    k = 10.0 ** math.floor(math.log10(raw))
    h = next(m * k for m in (1, 2, 5, 10) if m * k >= raw)
    return math.floor(lo / h) * h, math.ceil(hi / h) * h, h


def places(h: float) -> int:
    return max(0, -math.floor(math.log10(h)))


class Plot(Primitive[PlotArgs]):
    """Line graphs y_k(x_k) on shared axes; logy gives a decade-scaled ordinate."""

    name = "plot"
    args = PlotArgs

    def build(self, a: PlotArgs, ctx: Context, cell: Box) -> Mobject:
        data: list[tuple[NDArray[Any], NDArray[Any]]] = []
        for s in a.series:
            x, y = ctx.array(s.x).astype(float), ctx.array(s.y).astype(float)
            if x.ndim != 1 or x.shape != y.shape or len(x) < 2:
                raise AnimateError(
                    f"plot series needs x, y of equal length >= 2: {x.shape}, {y.shape}"
                )
            if not (np.isfinite(x).all() and np.isfinite(y).all()) or (a.logy and y.min() <= 0):
                raise AnimateError("plot series must be finite, and positive when logy")
            data.append((x, y))
        xs, ys = np.concatenate([d[0] for d in data]), np.concatenate([d[1] for d in data])
        if a.logy:
            e0, e1 = math.floor(np.log10(ys.min())), math.ceil(np.log10(ys.max()))
            y_range: tuple[float, float, float] = (e0, max(e1, e0 + 1), 1)
            y_cfg: dict[str, Any] = {"scaling": LogBase(custom_labels=True)}
        else:
            y_range = ticks(float(ys.min()), float(ys.max()))
            y_cfg = {"decimal_number_config": {"num_decimal_places": places(y_range[2])}}
        x_range = ticks(float(xs.min()), float(xs.max()))
        ax = Axes(
            x_range=x_range,
            y_range=y_range,
            x_length=0.8 * cell.width,
            y_length=0.75 * cell.height,
            tips=False,
            axis_config={"include_numbers": True, "font_size": 24},
            x_axis_config={"decimal_number_config": {"num_decimal_places": places(x_range[2])}},
            y_axis_config=y_cfg,
        )
        parts: list[VMobject] = [ax]
        if a.xlabel or a.ylabel:
            parts.append(ax.get_axis_labels(Tex(a.xlabel or "~"), Tex(a.ylabel or "~")))
        for (x, y), c in zip(data, COLORS, strict=False):
            parts.append(ax.plot_line_graph(x, y, line_color=c, add_vertex_dots=False))
        keys = [
            Tex(s.label, color=c, font_size=28)
            for s, c in zip(a.series, COLORS, strict=False)
            if s.label
        ]
        if keys:
            legend = VGroup(*keys).arrange(DOWN, aligned_edge=RIGHT, buff=0.1)
            parts.append(legend.next_to(ax.get_corner(UR), DL, buff=0.1))
        return VGroup(*parts)
