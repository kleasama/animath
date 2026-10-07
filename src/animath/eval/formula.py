"""Formula fidelity (Q2) and traceability (N1): normalized match, then SymPy equivalence."""

import re
from collections.abc import Iterable
from functools import cache

import sympy  # type: ignore[import-untyped]
from lark import Tree
from lark.exceptions import LarkError
from sympy.parsing.latex import parse_latex  # type: ignore[import-untyped]
from sympy.parsing.latex.errors import LaTeXParsingError  # type: ignore[import-untyped]

from animath.core.schemas import BlockType, DocIR, Storyboard

TOKEN = re.compile(r"\\[a-zA-Z]+|\\.|\S")
DROP = re.compile(
    r"\\(?:[,;:!> ]|q?quad|displaystyle|textstyle|left|right|[bB]igg?[lr]?)(?![a-zA-Z])|~|(?<!\\)&"
)
FONT = re.compile(r"\\(?:mathbf|mathrm|mathit|boldsymbol|bm|mathsf|mathcal)\s*")
MARK = re.compile(r"\{\{(.*?)\}\}")
INLINE = re.compile(r"(?<!\\)\$([^$]+)\$")
DEPTH = {
    **dict.fromkeys(("{", "(", "[", r"\{", r"\langle"), 1),
    **dict.fromkeys(("}", ")", "]", r"\}", r"\rangle"), -1),
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


def equivalent(a: str, b: str) -> bool | None:
    """True if some readings agree symbolically, False if all disagree, None if unparseable."""
    pa, pb = parse(a), parse(b)
    if not pa or not pb:
        return None
    return any(_same(x, y) for x in pa for y in pb)


def matches(f: str, refs: Iterable[str]) -> bool:
    refs = list(refs)
    n = normalize(f)
    return any(normalize(r) == n for r in refs) or any(equivalent(f, r) for r in refs)


def equations(doc: DocIR) -> list[tuple[str, str]]:
    """(label or position, latex) of the equation blocks of `doc`."""
    eqs = [b for b in doc.blocks if b.type is BlockType.EQUATION]
    return [(b.label or f"#{i}", b.latex or "") for i, b in enumerate(eqs)]


def fidelity(expected: DocIR, actual: DocIR) -> tuple[float, list[dict[str, str | bool | None]]]:
    """Q2: fraction of expected equations matched exactly (normalized) by label or position;
    mismatches carry the SymPy verdict."""
    want, got = equations(expected), dict(equations(actual))
    bad: list[dict[str, str | bool | None]] = []
    for k, tex in want:
        have = got.get(k)
        if have is None or normalize(have) != normalize(tex):
            eq = None if have is None else equivalent(tex, have)
            bad.append({"equation": k, "expected": tex, "actual": have, "equivalent": eq})
    return (1.0 - len(bad) / len(want) if want else 1.0), bad


def on_screen(board: Storyboard) -> list[list[str]]:
    """Formula chains shown: singletons from `math` and `equation`, step lists from `derive`."""
    out: list[list[str]] = []
    for s in board.scenes:
        out += [[m] for m in s.math]
        for v in s.visuals:
            if v.primitive == "equation" and isinstance(tex := v.args.get("latex"), str):
                out.append([tex])
            elif v.primitive == "derive" and isinstance(steps := v.args.get("steps"), list):
                out.append([MARK.sub(r"\1", str(x)) for x in steps])
    return out


def parts(tex: str) -> list[str]:
    """`tex` and, if it is a list, its parts split at top-level `,`, `;` and `\\`."""
    out: list[list[str]] = [[]]
    depth = 0
    for x in TOKEN.findall(DROP.sub(" ", tex)):
        depth += DEPTH.get(x, 0)
        if depth == 0 and x in SEP:
            out.append([])
        else:
            out[-1].append(x)
    return [tex, *(" ".join(p) for p in out if p)] if len(out) > 1 else [tex]


def references(doc: DocIR) -> list[str]:
    """Equations of D, inline math of its text, and their top-level parts."""
    tex = [t for _, t in equations(doc)] + [m for b in doc.blocks for m in INLINE.findall(b.text)]
    return [p for t in tex for p in parts(t)]


def untraced(board: Storyboard, doc: DocIR) -> tuple[int, list[str]]:
    """N1: formulas on screen neither in D (normalized or SymPy-equivalent) nor derived from
    their predecessor by SymPy equivalence. Returns (number shown, untraced)."""
    refs = references(doc)
    shown, bad = 0, []
    for chain in on_screen(board):
        for i, f in enumerate(chain):
            shown += 1
            if not (matches(f, refs) or (i > 0 and equivalent(chain[i - 1], f))):
                bad.append(f)
    return shown, bad
