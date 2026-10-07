import shutil
import subprocess
from pathlib import Path

import pytest

from animath.core.errors import NarrateError
from animath.narrate.verbalize import SCRIPT, Verbalizer, split
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
    assert v.id == "sre:mathspeak"


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
    assert v.speak([r"x^2+\frac{1}{2}", r"\mathbf{Z}\mathbf{I}=\mathbf{V}"]) == [
        "x squared plus one half",
        "bold Z bold I equals bold V",
    ]
    with pytest.raises(NarrateError, match="frac"):
        v.speak([r"\frac{1}"])
