from typing import Self

import numpy as np
from manim import ORIGIN, MathTex, Mobject, MobjectMatrix
from pydantic import model_validator

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, ArrayRef, Context, Primitive
from animath.scene.primitives.field import colorize, raster

DENSE_MAX = 8
PITCH = (0.8, 1.3)
GAP = 0.4


class MatrixArgs(Args):
    entries: list[list[str]] | ArrayRef

    @model_validator(mode="after")
    def _rect(self) -> Self:
        e = self.entries
        if isinstance(e, list) and (not e or not e[0] or len({len(r) for r in e}) != 1):
            raise ValueError("entries must be a non-empty rectangular array")
        return self


def grid(entries: list[list[str]]) -> Mobject:
    """Entries centred on a grid whose pitch clears the largest entry by GAP."""
    rows = [[MathTex(e) for e in r] for r in entries]
    cells = [m for r in rows for m in r]
    return MobjectMatrix(
        rows,
        v_buff=max(PITCH[0], max(m.height for m in cells) + GAP),
        h_buff=max(PITCH[1], max(m.width for m in cells) + GAP),
        element_alignment_corner=ORIGIN,
    )


class Matrix(Primitive[MatrixArgs]):
    """Entries for n <= DENSE_MAX; otherwise the pattern log10|a_ij| as a heatmap."""

    name = "matrix"
    args = MatrixArgs

    def build(self, a: MatrixArgs, ctx: Context, cell: Box) -> Mobject:
        if isinstance(a.entries, list):
            return grid(a.entries)
        z = ctx.array(a.entries)
        if z.ndim != 2 or not z.size:
            raise AnimateError(f"matrix needs a non-empty 2-D array, got shape {z.shape}")
        if max(z.shape) <= DENSE_MAX:
            return grid([[f"{x:.3g}" for x in row] for row in z])
        mag = np.abs(z)
        floor = mag[mag > 0].min() if (mag > 0).any() else 1.0
        return raster(colorize(np.log10(np.maximum(mag, floor))), cell)
