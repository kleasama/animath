import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from animath.core.errors import IngestError

Check = Callable[[Sequence[str], Mapping[str, str]], dict[int, str]]
PREAMBLE = r"\documentclass{article}\usepackage{amsmath,amssymb,bm}"
MARK = "@@animath-eq-"


def balanced(tex: str) -> bool:
    depth = 0
    for m in re.finditer(r"\\.|[{}]", tex):
        depth += {"{": 1, "}": -1}.get(m[0], 0)
        if depth < 0:
            return False
    return depth == 0


def errors(log: str) -> dict[int, str]:
    """First TeX error per equation index, from a log of `compile_errors`."""
    out: dict[int, str] = {}
    cur: int | None = None
    for ln in log.splitlines():
        if ln.startswith(MARK):
            cur = int(ln[len(MARK) :])
        elif ln.startswith("! "):
            if cur is None:
                raise IngestError(f"preamble or macros fail: {ln[2:]}")
            out.setdefault(cur, ln[2:])
    return out


def compile_errors(
    equations: Sequence[str], macros: Mapping[str, str], timeout: float = 120
) -> dict[int, str]:
    """Typeset each equation in display mode with pdflatex; index -> first error."""
    bad = {i: "unbalanced braces" for i, e in enumerate(equations) if not balanced(e)}
    todo = [(i, e) for i, e in enumerate(equations) if i not in bad]
    if not todo:
        return bad
    exe = shutil.which("pdflatex")
    if exe is None:
        raise IngestError("pdflatex not found")
    body = "\n".join(f"\\typeout{{{MARK}{i}}}\n\\[{e}\\]" for i, e in todo)
    macro_lines = "\n".join(macros.values())
    src = f"{PREAMBLE}\n{macro_lines}\n\\begin{{document}}\n{body}\n\\end{{document}}\n"
    with tempfile.TemporaryDirectory(prefix="animath-eq-") as d:
        (Path(d) / "eq.tex").write_text(src)
        cmd = [exe, "-interaction=nonstopmode", "-draftmode", "-no-shell-escape", "eq.tex"]
        try:
            subprocess.run(cmd, cwd=d, capture_output=True, timeout=timeout, check=False)
            log = (Path(d) / "eq.log").read_text(errors="replace")
        except (subprocess.TimeoutExpired, OSError) as e:
            raise IngestError(f"pdflatex failed: {e}") from e
    return bad | errors(log)
