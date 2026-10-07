import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from animath.core.errors import IngestError
from animath.ingest import check
from animath.ingest.pdf import Transcript

TEX = pytest.mark.skipif(shutil.which("pdflatex") is None, reason="needs pdflatex")


def test_errors_attributes_first_error_per_equation() -> None:
    log = f"x\n{check.MARK}0\n{check.MARK}1\n! Undefined control sequence.\n! Again.\n{check.MARK}2"
    assert check.errors(log) == {1: "Undefined control sequence."}
    assert check.balanced(r"\{")
    assert not check.balanced("{")
    assert check.compile_errors(["}{"], {}) == {0: "unbalanced braces"}
    with pytest.raises(IngestError, match="preamble or macros fail: Bad"):
        check.errors("! Bad\n")


def test_compile_errors_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check.compile_errors([], {}) == {}
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(IngestError, match="pdflatex not found"):
        check.compile_errors(["x"], {})
    monkeypatch.setattr(shutil, "which", lambda _: "/bin/true")

    def slow(*a: Any, **k: Any) -> Any:
        raise subprocess.TimeoutExpired("pdflatex", 1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(IngestError, match="pdflatex failed"):
        check.compile_errors(["x"], {})


def test_compile_errors_reads_log(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(cmd: list[str], cwd: str, **k: Any) -> Any:
        src = (Path(cwd) / "eq.tex").read_text()
        assert "\\newcommand{\\R}" in src
        assert f"{check.MARK}0" not in src
        (Path(cwd) / "eq.log").write_text(f"{check.MARK}1\n! Missing $ inserted.\n")

    monkeypatch.setattr(shutil, "which", lambda _: "pdflatex")
    monkeypatch.setattr(subprocess, "run", fake)
    out = check.compile_errors(["{", "x"], {"\\R": "\\newcommand{\\R}{R}"})
    assert out == {0: "unbalanced braces", 1: "Missing $ inserted."}


@TEX
def test_compile_errors_real() -> None:
    eqs = [r"\R^n", r"\frac{a}{b", r"\begin{aligned}a&=b\\c&=d\end{aligned}", r"\nope"]
    out = check.compile_errors(eqs, {"\\R": r"\newcommand{\R}{\mathbb{R}}"})
    assert out[1] == "unbalanced braces"
    assert sorted(out) == [1, 3]
    assert out[3] == "Undefined control sequence."


@TEX
def test_golden_transcript_compiles(golden: Path) -> None:
    t = Transcript.model_validate_json((golden / "gauss" / "transcript.json").read_text())
    assert check.compile_errors([b.latex for b in t.blocks if b.latex], {}) == {}
