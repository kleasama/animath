import inspect
from typing import Any

from pydantic import JsonValue

from animath.scene.primitives.base import VERBS, Args, ArrayRef, Context, Cue, Primitive
from animath.scene.primitives.code import Code
from animath.scene.primitives.field import Field, Surface
from animath.scene.primitives.matrix import Matrix
from animath.scene.primitives.plot import Plot
from animath.scene.primitives.tex import Derive, Equation, Text
from animath.scene.primitives.trace import Trace

PRIMITIVES: dict[str, Primitive[Any]] = {
    p.name: p
    for p in (Text(), Equation(), Derive(), Matrix(), Plot(), Field(), Surface(), Trace(), Code())
}


def catalog() -> dict[str, dict[str, JsonValue]]:
    """JSON schema of the arguments of every primitive, described by its docstring; the verbs
    of an action are listed unless the visual defines them (`code`)."""
    out: dict[str, dict[str, JsonValue]] = {}
    for n, p in PRIMITIVES.items():
        s = p.args.model_json_schema()
        s["description"] = inspect.getdoc(p) or n
        if not isinstance(p, Code):
            s["$defs"]["Action"]["properties"]["do"]["enum"] = [*VERBS, *p.verbs]
        out[n] = s
    return out


__all__ = ["PRIMITIVES", "Args", "ArrayRef", "Context", "Cue", "Primitive", "catalog"]
