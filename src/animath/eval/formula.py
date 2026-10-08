"""Formula fidelity (Q2) and traceability (N1) of artifacts by `core.formula`."""

import re

from animath.core import formula
from animath.core.schemas import BlockType, DocIR, Storyboard

INLINE = re.compile(r"(?<!\\)\$([^$]+)\$")


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
        if have is None or formula.normalize(have) != formula.normalize(tex):
            eq = None if have is None else formula.equivalent(tex, have)
            bad.append({"equation": k, "expected": tex, "actual": have, "equivalent": eq})
    return (1.0 - len(bad) / len(want) if want else 1.0), bad


def references(doc: DocIR) -> list[str]:
    """Equations of D, inline math of its text, and their items."""
    tex = [t for _, t in equations(doc)] + [m for b in doc.blocks for m in INLINE.findall(b.text)]
    return [p for t in tex for p in (t, *formula.parts(t))]


def untraced(board: Storyboard, doc: DocIR) -> tuple[int, list[str]]:
    """N1: formulas on screen not traced to D. Returns (number shown, untraced)."""
    refs = references(doc)
    shown = sum(len(c) for s in board.scenes for c in formula.on_screen(s))
    return shown, [f for s in board.scenes for f in formula.untraced(s, refs)]
