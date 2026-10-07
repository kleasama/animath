from typing import Self

import numpy as np
from manim import Matrix as MatrixMob
from manim import Mobject
from pydantic import model_validator

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, ArrayRef, Context, Primitive
from animath.scene.primitives.field import colorize, raster

DENSE_MAX = 8


class MatrixArgs(Args):
    entries: list[list[str]] | ArrayRef

    @model_validator(mode="after")
    def _rect(self) -> Self:
        e = self.entries
        if isinstance(e, list) and (not e or not e[0] or len({len(r) for r in e}) != 1):
            raise ValueError("entries must be a non-empty rectangular array")
        return self


class Matrix(Primitive[MatrixArgs]):
    """Entries for n <= DENSE_MAX; otherwise the pattern log10|a_ij| as a heatmap."""

    name = "matrix"
    args = MatrixArgs

    def build(self, a: MatrixArgs, ctx: Context, cell: Box) -> Mobject:
        if isinstance(a.entries, list):
            return MatrixMob(a.entries)
        z = ctx.array(a.entries)
        if z.ndim != 2 or not z.size:
            raise AnimateError(f"matrix needs a non-empty 2-D array, got shape {z.shape}")
        if max(z.shape) <= DENSE_MAX:
            return MatrixMob([[f"{x:.3g}" for x in row] for row in z])
        mag = np.abs(z)
        floor = mag[mag > 0].min() if (mag > 0).any() else 1.0
        return raster(colorize(np.log10(np.maximum(mag, floor))), cell)
