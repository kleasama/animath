import re
import shutil
import subprocess
from pathlib import Path

import pytest

from animath.core.errors import NarrateError
from animath.narrate.verbalize import SCRIPT, SPEECH, TEX, Verbalizer, rewrite, split
from tests.narrate.conftest import Script

ECHO = 'r = json.load(sys.stdin); print(json.dumps([f"<{t}|{r[\'domain\']}>" for t in r["latex"]]))'


@pytest.mark.parametrize(
    ("text", "parts"),
    [
        ("plain", [("plain", False)]),
        ("solve $Ax=b$.", [("solve ", False), ("Ax=b", True), (".", False)]),
        ("$$\\int f$$ and \\(g\\)", [("\\int f", True), (" and ", False), ("g", True)]),
        ("costs \\$5, $x$", [("costs \\$5, ", False), ("x", True)]),
        ("$a$ $b$", [("a", True), (" ", False), ("b", True)]),
    ],
)
def test_split(text: str, parts: list[tuple[str, bool]]) -> None:
    assert split(text) == parts


def test_lines_substitutes_in_order_with_one_call(script: Script, tmp_path: Path) -> None:
    log = tmp_path / "calls"
    body = f"open({str(log)!r}, 'a').write('x')\n{ECHO}"
    v = Verbalizer("mathspeak", cmd=[script(body)])
    out = v.lines(["Let $x$ be.", "No math here.", "$y$-axis and  $z$"])
    assert out == ["Let <x|mathspeak> be.", "No math here.", "<y|mathspeak>-axis and <z|mathspeak>"]
    assert log.read_text() == "x"
    assert re.fullmatch(r"sre:mathspeak:[0-9a-f]{8}", v.id)


@pytest.mark.parametrize(
    ("tex", "out"),
    [
        (r"\mathcal{H}^2", r"\text{H two}"),
        (r"\mathcal H^{2}", r"\text{H two}"),
        (r"L_{21} + a_{ij}", r"L_{2 1} + a_{ij}"),
        (r"U_t^{\mathrm{aug}}", r"U_t\text{ aug}"),
        (r"x^{\mathrm{T}} e^{x}", r"x^{\mathrm{T}} e^{x}"),
    ],
)
def test_tex_rewrites(tex: str, out: str) -> None:
    assert rewrite(tex, TEX) == out


@pytest.mark.parametrize(
    ("sre", "out"),
    [
        ("A to the negative 1 power", "A inverse"),
        ("A raised to the negative normal down tack power", "A inverse transpose"),
        ("x raised to the normal down tack power A x", "x transpose A x"),
        ("Q sub t raised to the asterisk power", "Q t star"),
        ("Q sub t raised to the sans serif H power", "Q t Hermitian"),
        (
            "e raised to the negative j k R power divided by 4 pi R",
            "e to the minus j k R over 4 pi R",
        ),
        ("x to the n-th power plus 10 to the sixth power", "x to the n plus 10 to the sixth"),
        ("the fraction with numerator chi and denominator 1 minus chi", "chi over 1 minus chi"),
        ("the metric of x minus x sub k sub 2", "the 2 norm of x minus x k"),
        ("the metric of e sub k plus 1", "the norm of e k plus 1"),
        ("script O of open paren N log N close paren", "order N log N"),
        ("G of open paren bold r comma bold r prime close paren", "G of r, r prime"),
        ("the set 1 comma dot dot dot comma n", "the set 1 up to n"),
        ("a dot dot dot", "a and so on"),
        ("t is a member of script T sub script l", "t in T ell"),
        ("partial differential sub n u", "partial n u"),
        ("lamda sub max", "lambda max"),
        ("bold r is a member of r-three", "r in r three"),
        ("cap H two", "H two"),
    ],
)
def test_speech_rewrites(sre: str, out: str) -> None:
    assert " ".join(rewrite(sre, SPEECH).split()) == out


def test_prose_only_spawns_nothing() -> None:
    assert Verbalizer(cmd=["/nonexistent"]).lines(["a  b", "c"]) == ["a b", "c"]


@pytest.mark.parametrize(
    ("body", "msg"),
    [
        ("sys.stderr.write('bad tex'); sys.exit(1)", "bad tex"),
        ("print('not json')", "malformed"),
        ("print(json.dumps(['one', 'two']))", "for 1 formulas"),
        ("print(json.dumps({'a': 1}))", "for 1 formulas"),
    ],
)
def test_failures_raise(script: Script, body: str, msg: str) -> None:
    with pytest.raises(NarrateError, match=msg):
        Verbalizer(cmd=[script(body)]).lines(["$x$"])


def test_missing_program() -> None:
    with pytest.raises(NarrateError, match="cannot run"):
        Verbalizer(cmd=["/nonexistent/node"]).speak(["x"])


def _sre_available() -> bool:
    if shutil.which("node") is None:
        return False
    probe = "require('speech-rule-engine'); require('mathjax-full/js/mathjax.js')"
    return subprocess.run(["node", "-e", probe], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not _sre_available(), reason="node with speech-rule-engine, mathjax-full")
def test_sre_clearspeak() -> None:
    assert SCRIPT.is_file()
    v = Verbalizer()
    tex = [
        r"x^2+\frac{1}{2}",
        r"\mathbf{Z}\mathbf{I}=\mathbf{V}",
        r"L_{21}",
        r"D_{RR}",
        r"\mathcal N(t)",
        r"\epsilon_L/u",
        r"\chi/(1-\chi)",
        r"\mathcal H^2",
        r"\|A^{-1}\|_2",
    ]
    assert v.speak(tex) == [
        "x squared plus one half",
        "Z I equals V",
        "L 2 1",
        "D R R",
        "N of t",
        "epsilon L over u",
        "chi over 1 minus chi",
        "H two",
        "the 2 norm of A inverse",
    ]
    with pytest.raises(NarrateError, match="frac"):
        v.speak([r"\frac{1}"])
