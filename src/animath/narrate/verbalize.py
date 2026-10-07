import json
import re
from collections.abc import Sequence
from pathlib import Path

from animath.core.errors import NarrateError
from animath.narrate.proc import run

MATH = re.compile(r"\$\$(.+?)\$\$|(?<!\\)\$(.+?)(?<!\\)\$|\\\((.+?)\\\)", re.S)
SCRIPT = Path(__file__).with_name("sre.cjs")


def split(text: str) -> list[tuple[str, bool]]:
    """Segments of `text` as (content, is_math), in order."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in MATH.finditer(text):
        out += [(text[pos : m.start()], False), (next(g for g in m.groups() if g), True)]
        pos = m.end()
    out.append((text[pos:], False))
    return [(s, is_math) for s, is_math in out if s]


class Verbalizer:
    """Inline TeX to spoken English via MathJax and Speech Rule Engine (node subprocess)."""

    def __init__(self, domain: str = "clearspeak", cmd: Sequence[str] = ("node", str(SCRIPT))):
        self.domain, self.cmd = domain, list(cmd)
        self.id = f"sre:{domain}"

    def speak(self, latex: Sequence[str]) -> list[str]:
        if not latex:
            return []
        raw = run(self.cmd, json.dumps({"domain": self.domain, "latex": list(latex)}).encode())
        try:
            out = json.loads(raw)
        except json.JSONDecodeError as e:
            raise NarrateError(f"malformed verbalizer output: {raw[:200]!r}") from e
        if not isinstance(out, list) or len(out) != len(latex):
            raise NarrateError(f"verbalizer returned {out!r} for {len(latex)} formulas")
        return [str(s) for s in out]

    def lines(self, texts: Sequence[str]) -> list[str]:
        """Spoken form of each text; one subprocess call for all formulas."""
        parts = [split(t) for t in texts]
        spoken = iter(self.speak([s for p in parts for s, m in p if m]))
        return [" ".join("".join(next(spoken) if m else s for s, m in p).split()) for p in parts]
