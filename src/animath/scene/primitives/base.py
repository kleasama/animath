from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any, ClassVar, Literal

import numpy as np
from manim import Animation, FadeIn, Mobject, VMobject, Write
from numpy.typing import NDArray
from pydantic import Field

from animath.core.errors import AnimateError, StoreError
from animath.core.schemas import DataSet, Model, Scene
from animath.core.store import Store
from animath.scene.layout import Box, Region


class ArrayRef(Model):
    """Array `array` of the DataSet answering `scene.data[data]`, optionally mapped by `part`."""

    data: int = Field(ge=0)
    array: str
    part: Literal["abs", "real", "imag"] | None = None


Vector = list[float] | ArrayRef
Grid = list[list[float]] | ArrayRef


class Args(Model):
    region: Region = "main"
    until: str | None = None


@dataclass(frozen=True)
class Context:
    scene: Scene
    store: Store
    datasets: Mapping[str, DataSet]
    px_per_unit: float

    def array(self, v: Vector | Grid | ArrayRef) -> NDArray[Any]:
        if not isinstance(v, ArrayRef):
            return np.asarray(v, dtype=float)
        where = f"scene {self.scene.id}: data[{v.data}].{v.array}"
        if v.data >= len(self.scene.data):
            raise AnimateError(f"{where}: no such request")
        ds = self.datasets.get(self.scene.data[v.data].digest)
        if ds is None or v.array not in ds.arrays:
            raise AnimateError(f"{where}: missing")
        try:
            out = np.load(BytesIO(self.store.get_blob(ds.arrays[v.array])), allow_pickle=False)
        except (StoreError, ValueError, OSError) as e:
            raise AnimateError(f"{where}: unreadable: {e}") from e
        if not isinstance(out, np.ndarray):
            raise AnimateError(f"{where}: not a .npy array")
        return getattr(np, v.part)(out) if v.part else out

    def real(self, v: Vector | Grid | ArrayRef) -> NDArray[np.float64]:
        """Real float array; complex data must select `part`."""
        out = self.array(v)
        if np.iscomplexobj(out):
            raise AnimateError(f"scene {self.scene.id}: complex array {v}; set part")
        return out.astype(float)


@dataclass(frozen=True)
class Cue:
    t: float
    run_time: float
    play: Callable[[], Animation]


def enter(m: Mobject) -> Animation:
    return Write(m) if isinstance(m, VMobject) else FadeIn(m)


class Primitive[A: Args](ABC):
    name: ClassVar[str]
    args: type[A]

    @abstractmethod
    def build(self, a: A, ctx: Context, cell: Box) -> Mobject: ...

    def cues(self, m: Mobject, a: A, t0: float, t1: float) -> list[Cue]:
        return [Cue(t0, 1.0, lambda: enter(m))]

    def last(self, m: Mobject) -> Mobject:
        return m
