import json
import re
from collections.abc import Sequence
from pathlib import Path

from animath.core.errors import NarrateError
from animath.core.hashing import digest_of
from animath.narrate.proc import run

MATH = re.compile(r"\$\$(.+?)\$\$|(?<!\\)\$(.+?)(?<!\\)\$|\\\((.+?)\\\)", re.S)
SCRIPT = Path(__file__).with_name("sre.cjs")
TEX = (
    (r"\\mathcal\s*\{?H\}?\s*\^\s*\{?2\}?", r"\\text{H two}"),
    (r"_\{(\d)(\d)\}", r"_{\1 \2}"),
    (r"\^\s*\{\\(?:mathrm|text|operatorname)\{([A-Za-z]{2,})\}\}", r"\\text{ \1}"),
)
SPEECH = (
    (r"(?: raised)? to the negative 1 power", " inverse"),
    (r"(?: raised)? to the negative (?:normal down tack|T) power", " inverse transpose"),
    (r"(?: raised)? to the (?:normal down tack|T|sans serif T) power", " transpose"),
    (r"(?: raised)? to the asterisk power", " star"),
    (r"(?: raised)? to the (?:H|sans serif H) power", " Hermitian"),
    (r" raised to the (.+?) power", r" to the \1"),
    (r" to the (\S+?)(?:-th)? power", r" to the \1"),
    (r"\bthe fraction with numerator (.+?) and denominator ", r"\1 over "),
    (r"\bdivided by\b", "over"),
    (r"\bthe metric of (.+?) sub (\w+)$", r"the \2 norm of \1"),
    (r"\bthe metric of\b", "the norm of"),
    (r"\bscript l\b", "ell"),
    (r"\b(?:script )?O of\b", "order"),
    (r"\b(?:script|bold|normal|double-struck|sans serif|fraktur|cap) ", ""),
    (r"\bopen paren |\bclose paren\b ?", ""),
    (r"\bcomma dot dot dot comma\b", "up to"),
    (r"\bdot dot dot\b", "and so on"),
    (r" comma\b", ","),
    (r"\bnegative\b", "minus"),
    (r"\bis a member of\b", "in"),
    (r"\bpartial differential\b", "partial"),
    (r"\blamda\b", "lambda"),
    (r"\b([a-z])-(?=\w)", r"\1 "),
    (r"\bsub ", ""),
)


def split(text: str) -> list[tuple[str, bool]]:
    """Segments of `text` as (content, is_math), in order."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in MATH.finditer(text):
        out += [(text[pos : m.start()], False), (next(g for g in m.groups() if g), True)]
        pos = m.end()
    out.append((text[pos:], False))
    return [(s, is_math) for s, is_math in out if s]


def rewrite(text: str, rules: Sequence[tuple[str, str]]) -> str:
    for pattern, repl in rules:
        text = re.sub(pattern, repl, text)
    return text


class Verbalizer:
    """Inline TeX to lecture-style English: MathJax and Speech Rule Engine (node), then SPEECH."""

    def __init__(self, domain: str = "clearspeak", cmd: Sequence[str] = ("node", str(SCRIPT))):
        self.domain, self.cmd = domain, list(cmd)
        self.id = f"sre:{domain}:{digest_of(TEX + SPEECH)[:8]}"

    def speak(self, latex: Sequence[str]) -> list[str]:
        if not latex:
            return []
        tex = [rewrite(t, TEX) for t in latex]
        raw = run(self.cmd, json.dumps({"domain": self.domain, "latex": tex}).encode())
        try:
            out = json.loads(raw)
        except json.JSONDecodeError as e:
            raise NarrateError(f"malformed verbalizer output: {raw[:200]!r}") from e
        if not isinstance(out, list) or len(out) != len(latex):
            raise NarrateError(f"verbalizer returned {out!r} for {len(latex)} formulas")
        return [" ".join(rewrite(str(s), SPEECH).split()) for s in out]

    def lines(self, texts: Sequence[str]) -> list[str]:
        """Spoken form of each text; one subprocess call for all formulas."""
        parts = [split(t) for t in texts]
        spoken = iter(self.speak([s for p in parts for s, m in p if m]))
        return [" ".join("".join(next(spoken) if m else s for s, m in p).split()) for p in parts]
