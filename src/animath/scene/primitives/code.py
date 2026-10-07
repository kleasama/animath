import ast
import builtins
import inspect
from collections.abc import Callable
from types import TracebackType
from typing import Any

import manim
import numpy as np
from manim import Animation, Mobject
from manim.animation.animation import prepare_animation
from pydantic import Field

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives.base import Args, ArrayRef, Context, Primitive, path

SNIPPET = "<snippet>"
ACT = "animath_act"
BUILD, ACT_SIG = ("build", ("array",)), ("act", ("m", "verb", "parts"))
API_PARAMS = 8
MOBJECTS = (  # noqa: SIM905
    "Annulus Arc Arrow Axes Brace BraceBetweenPoints Circle Cross DashedLine DecimalNumber Dot "
    "DoubleArrow Ellipse FunctionGraph Group Line MathTable MathTex NumberLine NumberPlane "
    "ParametricFunction Polygon Rectangle RoundedRectangle Square SurroundingRectangle Table "
    "Tex Text Triangle VGroup Vector"
).split()
ANIMATIONS = (  # noqa: SIM905
    "AnimationGroup Circumscribe Create FadeIn FadeOut GrowFromCenter Indicate LaggedStart "
    "ReplacementTransform Transform Write"
).split()
CONSTANTS = (  # noqa: SIM905
    "ORIGIN UP DOWN LEFT RIGHT UL UR DL DR PI TAU DEGREES "
    "WHITE BLACK GRAY BLUE RED GREEN YELLOW ORANGE PURPLE TEAL GOLD PINK MAROON"
).split()
NP = (  # noqa: SIM905
    "abs angle arange arctan2 array clip column_stack cos cumsum e exp hypot imag linspace log "
    "log10 max mean meshgrid min ones pi real sin sqrt stack sum tan zeros"
).split()
BUILTINS = "abs enumerate float int len list max min range round str sum tuple zip".split()  # noqa: SIM905
NAMES = frozenset(MOBJECTS + ANIMATIONS + CONSTANTS + BUILTINS + ["np"])
DENIED_ATTRS = frozenset({"dump", "dumps", "format", "format_map", "save", "save_image", "tofile"})
DENIED_PREFIXES = ("_", "ag_", "co_", "cr_", "f_", "gi_", "tb_")
FORBIDDEN = (
    ast.Import,
    ast.ImportFrom,
    ast.Global,
    ast.Nonlocal,
    ast.ClassDef,
    ast.AsyncFunctionDef,
    ast.While,
    ast.Try,
    ast.TryStar,
    ast.With,
    ast.Raise,
    ast.Delete,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
)


def gate(code: str) -> list[str]:
    """Static gate: `def build(array)`, optionally `def act(m, verb, parts)`; names, attributes
    and statements whitelisted."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"line {e.lineno}: syntax error: {e.msg}"]
    out = []
    sig = {
        (f.name, tuple(x.arg for x in f.args.args))
        for f in tree.body
        if isinstance(f, ast.FunctionDef)
    }
    if len(sig) != len(tree.body) or not {BUILD} <= sig <= {BUILD, ACT_SIG}:
        out.append("module must be `def build(array)`, optionally with `def act(m, verb, parts)`")
    nodes = list(ast.walk(tree))
    bound = {n.id for n in nodes if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    bound |= {n.arg for n in nodes if isinstance(n, ast.arg)}
    np_ok = {id(n.value) for n in nodes if isinstance(n, ast.Attribute) and n.attr in NP}
    for n in nodes:
        line = f"line {getattr(n, 'lineno', 0)}"
        if isinstance(n, FORBIDDEN):
            out.append(f"{line}: {type(n).__name__} not allowed")
        elif isinstance(n, ast.Name) and n.id == "np" and id(n) not in np_ok:
            out.append(f"{line}: np only as np.<name> with <name> in the API")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in NAMES | bound:
            out.append(f"{line}: name {n.id!r} not allowed")
        elif isinstance(n, ast.Attribute) and (
            n.attr.startswith(DENIED_PREFIXES) or n.attr in DENIED_ATTRS
        ):
            out.append(f"{line}: attribute {n.attr!r} not allowed")
    return out


def _line(tb: TracebackType | None) -> int:
    n = 0
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == SNIPPET:
            n = tb.tb_lineno
        tb = tb.tb_next
    return n


def call(f: Callable[..., Any], *args: Any) -> Any:
    """`f(*args)` with errors located by snippet line."""
    try:
        return f(*args)
    except AnimateError:
        raise
    except Exception as e:
        raise AnimateError(f"line {_line(e.__traceback__)}: {type(e).__name__}: {e}") from e


def run(code: str, array: Callable[..., Any]) -> Mobject:
    """Gate, execute in a whitelisted namespace, and call `build(array)`; a defined `act` is
    kept on the result."""
    bad = gate(code)
    if bad:
        raise AnimateError("; ".join(bad))
    ns: dict[str, Any] = {
        "__builtins__": {n: getattr(builtins, n) for n in BUILTINS},
        "np": np,
        **{n: getattr(manim, n) for n in MOBJECTS + ANIMATIONS + CONSTANTS},
    }
    call(exec, compile(code, SNIPPET, "exec"), ns)
    m = call(ns["build"], array)
    if not isinstance(m, Mobject):
        raise AnimateError(f"build returned {type(m).__name__}, not a Mobject")
    setattr(m, ACT, ns.get("act"))
    return m


def api() -> str:
    """Pinned API offered to code generation: constructor parameters of whitelisted symbols."""

    def sig(n: str) -> str:
        ps = inspect.signature(getattr(manim, n)).parameters.values()
        names = [
            f"*{p.name}" if p.kind is p.VAR_POSITIONAL else p.name
            for p in ps
            if p.kind is not p.VAR_KEYWORD
        ]
        return ", ".join(names[:API_PARAMS])

    return "\n".join(
        [f"{n}({sig(n)})" for n in MOBJECTS + ANIMATIONS]
        + [
            f"constants: {' '.join(CONSTANTS)}",
            f"np: {' '.join(NP)}",
            f"builtins: {' '.join(BUILTINS)}",
        ]
    )


class CodeArgs(Args):
    code: str = Field(
        min_length=1,
        description="Python source of `def build(array)` returning one Mobject, and optionally "
        "`def act(m, verb, parts)` returning an Animation for actions with other than the "
        "generic verbs; `parts` are the selected submobjects of `m`. act changes m in place: "
        "`p.animate...`, Transform(p, q) (p takes the shape of q), Indicate, or Create, Write, "
        "FadeIn, GrowFromCenter of new objects, which join the visual. Parts are dotted index "
        "paths, e.g. `1.0`. No imports, while, try, with, raise, or names beginning with `_`. "
        "`array(data, name, part=None)` returns the real NumPy array `name` of data request "
        "`data`; complex arrays need `part` in abs, real, imag. API:\n" + api(),
    )


class Code(Primitive[CodeArgs]):
    """Generated visual: whitelisted Python building a Mobject, with its own verbs if it defines
    `act`. Use only where no other primitive shows the visual."""

    name = "code"
    args = CodeArgs

    def build(self, a: CodeArgs, ctx: Context, cell: Box) -> Mobject:
        def array(data: int, name: str, part: str | None = None) -> Any:
            return ctx.real(ArrayRef.model_validate({"data": data, "array": name, "part": part}))

        return run(a.code, array)

    def knows(self, m: Mobject, verb: str) -> bool:
        return getattr(m, ACT, None) is not None

    def act(self, m: Mobject, a: CodeArgs, verb: str, parts: list[str]) -> Animation:
        out = call(getattr(m, ACT), m, verb, [path(m, s) for s in parts])
        try:
            return prepare_animation(out)
        except TypeError as e:
            raise AnimateError(
                f"act({verb!r}) returned {type(out).__name__}, not an Animation"
            ) from e
