"""Formula matching (Algorithm 12.3): normalized tokens, then SymPy equivalence."""

import re
from collections.abc import Sequence
from functools import cache

import sympy  # type: ignore[import-untyped]
from lark import Tree
from lark.exceptions import LarkError
from sympy.parsing.latex import parse_latex  # type: ignore[import-untyped]
from sympy.parsing.latex.errors import LaTeXParsingError  # type: ignore[import-untyped]

from animath.core.schemas import Scene

TOKEN = re.compile(r"\\[a-zA-Z]+|\\.|\S")
DROP = re.compile(
    r"(?<!\\)\\(?:[,;:!> ]|(?:q?quad|displaystyle|textstyle|left|right|[bB]igg?[lr]?)(?![a-zA-Z]))"
    r"|~|(?<!\\)&"
)
FONT = re.compile(r"\\(?:mathbf|mathrm|mathit|boldsymbol|bm|mathsf|mathcal)\s*")
LAYOUT = re.compile(r"\\(?:begin|end)\s*\{(?:gathered|aligned|split|gather|align)\*?\}")
MARK = re.compile(r"\{\{(.*?)\}\}")
DEPTH = {
    **dict.fromkeys(("{", "(", "[", r"\{", r"\langle", r"\begin"), 1),
    **dict.fromkeys(("}", ")", "]", r"\}", r"\rangle", r"\end"), -1),
}
SEP = {",", ";", r"\\"}


def normalize(tex: str) -> str:
    """Token sequence modulo spacing, sizing, alignment, braces around one token, trailing
    punctuation."""
    t = TOKEN.findall(DROP.sub(" ", tex))
    out: list[str] = []
    i = 0
    while i < len(t):
        if t[i] == "{" and t[i + 2 : i + 3] == ["}"] and t[i + 1] not in ("{", "}"):
            out.append(t[i + 1])
            i += 3
        else:
            out.append(t[i])
            i += 1
    while out and out[-1] in {".", ",", ";"}:
        out.pop()
    return " ".join(out)


@cache
def parse(tex: str) -> list[sympy.Basic]:
    """SymPy readings of `tex` (several if ambiguous); [] if unparseable."""
    try:
        e = parse_latex(FONT.sub("", DROP.sub(" ", tex)), backend="lark")
    except (LarkError, LaTeXParsingError, TypeError, ValueError):
        return []
    return list(e.children) if isinstance(e, Tree) else [e]


def _zero(e: sympy.Basic) -> bool:
    return bool(sympy.simplify(e) == 0)


def _same(a: sympy.Basic, b: sympy.Basic) -> bool:
    if isinstance(a, sympy.Equality) and isinstance(b, sympy.Equality):
        da, db = a.lhs - a.rhs, b.lhs - b.rhs
        return _zero(da - db) or _zero(da + db)
    if isinstance(a, sympy.Expr) and isinstance(b, sympy.Expr):
        return _zero(a - b)
    return bool(a == b)


@cache
def equivalent(a: str, b: str) -> bool | None:
    """True if some readings agree symbolically, False if all disagree, None if unparseable."""
    pa, pb = parse(a), parse(b)
    if not pa or not pb:
        return None
    return any(_same(x, y) for x in pa for y in pb)


def matches(f: str, refs: Sequence[str]) -> bool:
    n = normalize(f)
    return any(normalize(r) == n for r in refs) or any(equivalent(f, r) for r in refs)


def parts(tex: str) -> list[str]:
    """Items of a list or layout display: `tex` split at `,`, `;` and `\\` outside brackets and
    environments, layout environments (gathered, aligned, split) dropped; [] for one item."""
    bare = LAYOUT.sub(" ", tex)
    out: list[list[str]] = [[]]
    depth = 0
    for x in TOKEN.findall(DROP.sub(" ", bare)):
        depth += DEPTH.get(x, 0)
        if depth == 0 and x in SEP:
            out.append([])
        else:
            out[-1].append(x)
    return [" ".join(p) for p in out if p] if len(out) > 1 or bare != tex else []


def on_screen(s: Scene) -> list[list[str]]:
    """Formula chains of `s`: singletons from `math` and `equation`, step lists from `derive`."""
    out = [[m] for m in s.math]
    for v in s.visuals:
        if v.primitive == "equation" and isinstance(tex := v.args.get("latex"), str):
            out.append([tex])
        elif v.primitive == "derive" and isinstance(steps := v.args.get("steps"), list):
            out.append([MARK.sub(r"\1", str(x)) for x in steps])
    return out


def traced(f: str, prev: str | None, refs: Sequence[str]) -> bool:
    """`f` matches a reference, or is equivalent to its derive predecessor `prev`, or is a list
    whose items all match."""
    if matches(f, refs) or (prev is not None and equivalent(prev, f)):
        return True
    items = parts(f)
    return bool(items) and all(matches(p, refs) for p in items)


def untraced(s: Scene, refs: Sequence[str]) -> list[str]:
    """Formulas on screen in `s` not traced to `refs`."""
    return [
        f
        for chain in on_screen(s)
        for i, f in enumerate(chain)
        if not traced(f, chain[i - 1] if i else None, refs)
    ]
