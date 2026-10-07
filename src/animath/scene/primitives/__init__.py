from typing import Any

from pydantic import JsonValue

from animath.scene.primitives.base import Args, ArrayRef, Context, Cue, Primitive
from animath.scene.primitives.field import Field, Surface
from animath.scene.primitives.hierarchy import Hierarchy
from animath.scene.primitives.matrix import Matrix
from animath.scene.primitives.plot import Plot
from animath.scene.primitives.tex import Derive, Equation, Text
from animath.scene.primitives.trace import Trace

PRIMITIVES: dict[str, Primitive[Any]] = {
    p.name: p
    for p in (
        Text(),
        Equation(),
        Derive(),
        Matrix(),
        Plot(),
        Field(),
        Surface(),
        Trace(),
        Hierarchy(),
    )
}


def catalog() -> dict[str, dict[str, JsonValue]]:
    """JSON schema of the arguments of every primitive, for storyboard planning."""
    return {n: p.args.model_json_schema() for n, p in PRIMITIVES.items()}


__all__ = ["PRIMITIVES", "Args", "ArrayRef", "Context", "Cue", "Primitive", "catalog"]
