from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any, ClassVar, Literal, cast

import manim
import numpy as np
from manim import (
    YELLOW,
    Animation,
    Circumscribe,
    FadeIn,
    Indicate,
    ManimColor,
    Mobject,
    VMobject,
    Write,
)
from numpy.typing import NDArray
from pydantic import Field
from pydantic.json_schema import SkipJsonSchema

from animath.core.errors import AnimateError, StoreError
from animath.core.schemas import DataSet, Model, Scene
from animath.core.store import Store
from animath.scene.layout import Box, Region

VERBS = ("show", "hide", "indicate", "mark", "dim", "unmark")
ENTER_S, VERB_S, MIN_S = 1.5, 1.0, 0.25
DIM = 0.2
COLOR = r"^(#[0-9A-Fa-f]{6}|[A-Z][A-Z_]*)$"


class ArrayRef(Model):
    """Array `array` of the DataSet answering `scene.data[data]`, optionally mapped by `part`."""

    data: int = Field(ge=0)
    array: str
    part: Literal["abs", "real", "imag"] | None = None


Vector = list[float] | ArrayRef
Grid = list[list[float]] | ArrayRef


class Action(Model):
    """Change of parts of a visual at a narration cue."""

    at: str | None = Field(None, description="bookmark; null: initial state, no animation")
    word: str | None = Field(None, description="fire when this plain word of the line is spoken")
    frac: float = Field(0.0, ge=0.0, lt=1.0, description="offset as a fraction of the line slot")
    rate: float = Field(1.0, ge=1.0, le=64.0, description="playback speed")
    do: str = Field(min_length=1, description="verb")
    parts: list[str] = Field([], description="part selectors; empty: the whole visual")
    color: str | None = Field(None, pattern=COLOR, description="#RRGGBB or a Manim colour name")


class Args(Model):
    region: Region = "main"
    until: str | None = Field(None, description="bookmark removing the visual")
    enter: Literal["auto", "fade", "none"] = Field(
        "auto", description="auto: write or fade in; none: on screen without entry"
    )
    replaces: int | None = Field(
        None, ge=0, description="earlier visual this one morphs out of; its until is this at"
    )
    view: str | None = Field(None, description="persistent view, continued by a later visual")
    resume: SkipJsonSchema[bool] = Field(False, description="initial own animations at build")
    persist: bool = Field(False, description="stays on screen into the next scene")
    actions: list[Action] = Field([], description="timed changes of parts of this visual")


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
    """Animation started at `t`; `mobject` is redrawn while it plays; `what` labels an action
    whose visible effect is checked."""

    t: float
    run_time: float
    play: Callable[[], Animation]
    mobject: Mobject | None = None
    what: str = ""


def enter(m: Mobject) -> Animation:
    return Write(m) if isinstance(m, VMobject) else FadeIn(m)


def instant(a: Animation) -> None:
    """Apply the end state of `a` without frames."""
    a.begin()
    a.finish()


def color(name: str | None, default: ManimColor = YELLOW) -> ManimColor:
    if name is None:
        return default
    if name.startswith("#"):
        return ManimColor(name)
    c = getattr(manim, name, None)
    if not isinstance(c, ManimColor):
        raise AnimateError(f"unknown colour {name!r}")
    return c


def path(m: Mobject, sel: str) -> Mobject:
    """Submobject at a dotted index path, e.g. `1.0`."""
    out = m
    for i in sel.split("."):
        if not (i.isdigit() and int(i) < len(out.submobjects)):
            raise AnimateError(f"no part {sel!r}")
        out = out.submobjects[int(i)]
    return out


def verb(do: str, p: Mobject, orig: Mobject, c: ManimColor) -> Animation:
    """Generic verb on part `p`; `orig` is its unchanged copy. `show` writes `p` in its visual,
    not as a new object of the scene, which would split the visual."""
    if do == "show" and isinstance(p, VMobject):
        p.match_style(cast(VMobject, orig))
        w = Write(p)
        w.introducer = False
        return w
    if do == "indicate":
        return Indicate(p, color=c) if isinstance(p, VMobject) else Circumscribe(p, color=c)
    if do in ("show", "hide", "dim"):
        return p.animate.set_opacity({"show": 1.0, "hide": 0.0, "dim": DIM}[do]).build()
    if not isinstance(p, VMobject):
        raise AnimateError(f"{do} needs a vector part")
    if do == "mark":
        return p.animate.set_color(c).build()
    return p.animate.match_style(cast(VMobject, orig)).build()


class Primitive[A: Args](ABC):
    name: ClassVar[str]
    args: type[A]
    verbs: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def build(self, a: A, ctx: Context, cell: Box) -> Mobject: ...

    def cues(self, m: Mobject, a: A, t0: float, t1: float) -> list[Cue]:
        """Entry at t0 first, then the primitive's own animations, ending by t1; `compose`
        takes these from a second call with t0 at the end of the entry."""
        return [Cue(t0, ENTER_S, lambda: enter(m))]

    def first(self, m: Mobject) -> Mobject:
        """Mobject shown at entry."""
        return m

    def last(self, m: Mobject) -> Mobject:
        """Mobject shown at exit."""
        return m

    def knows(self, m: Mobject, verb: str) -> bool:
        return verb in self.verbs

    def part(self, m: Mobject, a: A, sel: str) -> Mobject:
        return path(m, sel)

    def act(self, m: Mobject, a: A, verb: str, parts: list[str]) -> Animation:
        """Animation of a verb of `verbs`; must change `m` in place (no removers)."""
        raise AnimateError(f"verb {verb!r} not implemented")
