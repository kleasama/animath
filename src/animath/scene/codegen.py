import ast
import builtins
import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Any

import manim
import numpy as np
from manim import Mobject
from pydantic import Field

from animath.core.errors import AnimateError
from animath.scene.layout import Box
from animath.scene.primitives import PRIMITIVES, Args, ArrayRef, Context, Primitive

SNIPPET = "<snippet>"
API_PARAMS = 8
MOBJECTS = (  # noqa: SIM905
    "Annulus Arc Arrow Axes Brace BraceBetweenPoints Circle Cross DashedLine DecimalNumber Dot "
    "DoubleArrow Ellipse FunctionGraph Group Line MathTable MathTex NumberLine NumberPlane "
    "ParametricFunction Polygon Rectangle RoundedRectangle Square SurroundingRectangle Table "
    "Tex Text Triangle VGroup Vector"
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
NAMES = frozenset(MOBJECTS + CONSTANTS + BUILTINS + ["np"])
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
    """Static gate: one `def build(array)`; names, attributes and statements whitelisted."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"line {e.lineno}: syntax error: {e.msg}"]
    out = []
    b = tree.body
    if not (
        len(b) == 1
        and isinstance(b[0], ast.FunctionDef)
        and b[0].name == "build"
        and [x.arg for x in b[0].args.args] == ["array"]
    ):
        out.append("module must consist of exactly `def build(array): ...`")
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


def run(code: str, array: Callable[..., Any]) -> Mobject:
    """Gate, execute in a whitelisted namespace, and call `build(array)`."""
    bad = gate(code)
    if bad:
        raise ValueError("; ".join(bad))
    ns: dict[str, Any] = {
        "__builtins__": {n: getattr(builtins, n) for n in BUILTINS},
        "np": np,
        **{n: getattr(manim, n) for n in MOBJECTS + CONSTANTS},
    }
    try:
        exec(compile(code, SNIPPET, "exec"), ns)
        m = ns["build"](array)
    except AnimateError:
        raise
    except Exception as e:
        raise RuntimeError(f"line {_line(e.__traceback__)}: {type(e).__name__}: {e}") from e
    if not isinstance(m, Mobject):
        raise TypeError(f"build returned {type(m).__name__}, not a Mobject")
    return m


class CodeArgs(Args):
    code: str = Field(min_length=1)


class Code(Primitive[CodeArgs]):
    """Generated `def build(array) -> Mobject`; `array(data, name, part=None)` reads a DataSet."""

    name = "code"
    args = CodeArgs

    def build(self, a: CodeArgs, ctx: Context, cell: Box) -> Mobject:
        def array(data: int, name: str, part: str | None = None) -> Any:
            return ctx.real(ArrayRef.model_validate({"data": data, "array": name, "part": part}))

        return run(a.code, array)


CODE = Code()


@contextmanager
def registered() -> Iterator[None]:
    """Expose `code` to the renderer; process-local, like the renderer itself."""
    PRIMITIVES[CODE.name] = CODE
    try:
        yield
    finally:
        del PRIMITIVES[CODE.name]


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
        [f"{n}({sig(n)})" for n in MOBJECTS]
        + [
            f"constants: {' '.join(CONSTANTS)}",
            f"np: {' '.join(NP)}",
            f"builtins: {' '.join(BUILTINS)}",
        ]
    )
