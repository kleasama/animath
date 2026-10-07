import os
from typing import Any

import numpy as np
import pyvista as pv
from manim import RESAMPLING_ALGORITHMS, ImageMobject, Mobject
from matplotlib import colormaps
from numpy.typing import NDArray

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, ArrayRef, Context, Grid, Primitive


def colorize(z: NDArray[Any]) -> NDArray[np.uint8]:
    """Map a real array affinely onto [0, 1], then through viridis to RGB."""
    z = np.asarray(z, dtype=float)
    if z.size == 0 or not np.isfinite(z).all():
        raise AnimateError(f"field of shape {z.shape} is empty or non-finite")
    lo, hi = z.min(), z.max()
    u = (z - lo) / (hi - lo) if hi > lo else np.zeros_like(z)
    rgb: NDArray[np.uint8] = (colormaps["viridis"](u)[..., :3] * 255).round().astype(np.uint8)
    return rgb


def raster(rgb: NDArray[np.uint8], cell: Box, nearest: bool = True) -> ImageMobject:
    m = ImageMobject(rgb)
    if nearest:
        m.set_resampling_algorithm(RESAMPLING_ALGORITHMS["nearest"])
    return m.scale(min(cell.width / m.width, cell.height / m.height))


class FieldArgs(Args):
    values: Grid


class SurfaceArgs(Args):
    points: ArrayRef
    faces: ArrayRef
    scalars: ArrayRef
    azimuth: float = 30.0
    elevation: float = 20.0


class Field(Primitive[FieldArgs]):
    """Scalar field u[i, j] at (x_j, y_i), y upward."""

    name = "field"
    args = FieldArgs

    def build(self, a: FieldArgs, ctx: Context, cell: Box) -> Mobject:
        z = ctx.array(a.values)
        if z.ndim != 2:
            raise AnimateError(f"field needs a 2-D array, got shape {z.shape}")
        return raster(colorize(np.flipud(z)), cell)


class Surface(Primitive[SurfaceArgs]):
    """Triangle mesh with vertex or face scalars, rendered offscreen by PyVista."""

    name = "surface"
    args = SurfaceArgs

    def build(self, a: SurfaceArgs, ctx: Context, cell: Box) -> Mobject:
        p, f, s = ctx.array(a.points), ctx.array(a.faces), ctx.array(a.scalars)
        if p.ndim != 2 or p.shape[1] != 3 or f.ndim != 2 or f.shape[1] != 3:
            raise AnimateError(
                f"surface needs points (n, 3), faces (m, 3); got {p.shape}, {f.shape}"
            )
        if not np.issubdtype(f.dtype, np.integer) or f.min() < 0 or f.max() >= len(p):
            raise AnimateError("surface faces must index points")
        if s.shape not in {(len(p),), (len(f),)}:
            raise AnimateError(f"surface scalars of shape {s.shape} match neither points nor faces")
        mesh = pv.PolyData(p.astype(float), np.hstack([np.full((len(f), 1), 3), f]).ravel())
        size = [round(cell.width * ctx.px_per_unit), round(cell.height * ctx.px_per_unit)]
        os.environ.setdefault("VTK_DEFAULT_OPENGL_WINDOW", "vtkOSOpenGLRenderWindow")
        pl = pv.Plotter(off_screen=True, window_size=size)
        try:
            pl.background_color = pv.Color("black")
            pl.add_mesh(mesh, scalars=s, cmap="viridis", show_scalar_bar=False)
            pl.camera.azimuth, pl.camera.elevation = a.azimuth, a.elevation
            img = pl.screenshot(return_img=True)
        finally:
            pl.close()
        return raster(np.ascontiguousarray(img, dtype=np.uint8), cell, nearest=False)
