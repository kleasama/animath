import subprocess
from typing import Any

import pytest

from animath.core.errors import IngestError
from animath.core.schemas import BlockType
from animath.ingest import blocks

MD = r"""Intro with *emph*, `code`, [link](http://x), ![alt](f.png), "quoted", 'single', a note^[See
$y$.] and \cite{k} \ref{eq:b} \eqref{eq:b} \cref{eq:a,eq:b} \foo.

\begin{align}
a &= b \label{eq:a} \\
c &= d \label{eq:b}
\end{align}

\begin{gather*}
e
\end{gather*}

> Quoted $$q=1$$ tail.

1. first
2. second
   - nested $$n$$

| x | y |
|---|---|
| 1 | 2 |

```python
print(1)
```

Line\
break

---

::: proof
Done.
:::

::: unknown
Inside <b>html</b>.
:::

::: theorem
> cited

    verbatim

```{=latex}
\vspace{1em}
```

::: inner
deep
:::
:::

\begin{equation}
f \nonumber
\end{equation}
"""


def doc(text: str, fmt: str = "markdown", **kw: Any) -> list[tuple[str, str, Any]]:
    d = blocks.document(text, fmt, "stem", {}, {"k": "K"}, **kw)
    return [(b.type.value, b.text or b.latex or "", b.label or b.refs or None) for b in d.blocks]


def test_markdown_structure_and_aliases() -> None:
    assert doc(MD) == [
        (
            "paragraph",
            "Intro with emph, code, link, alt, \"quoted\", 'single', a note (See $y$.) and [k]"
            " eq:b (eq:b) eq:a, eq:b .",
            ("k", "eq:a"),
        ),
        ("equation", "\\begin{aligned}\na &= b \\\\\nc &= d\n\\end{aligned}", "eq:a"),
        ("equation", "\\begin{gathered}\ne\n\\end{gathered}", None),
        ("paragraph", "Quoted", None),
        ("equation", "q=1", None),
        ("paragraph", "tail.", None),
        ("list", "1. first\n2. second\n- nested $$n$$", None),
        ("equation", "n", None),
        ("paragraph", "x y 1 2", None),
        ("code", "print(1)", None),
        ("paragraph", "Line\nbreak", None),
        ("proof", "Done.", None),
        ("paragraph", "Inside html.", None),
        ("theorem", "cited\nverbatim\ndeep", None),
        ("equation", "f", None),
    ]


def test_titles() -> None:
    assert blocks.document("---\ntitle: T *x*\n---\n\nA", "markdown", "s", {}, {}).title == "T x"
    assert blocks.document("# H\n\nA", "markdown", "s", {}, {}).title == "H"
    assert blocks.document("A", "markdown", "s", {}, {}).title == "s"
    assert blocks.document("A", "markdown", "s", {}, {}).blocks[0].type is BlockType.PARAGRAPH


def test_latex_theorem_heads_and_algorithm_token() -> None:
    src = (
        "\\newtheorem{obs}{Observation}\\begin{document}\\begin{obs}\\label{o}"
        "Plain $x$ \\[ y \\label{eq:y} \\]\\end{obs}\n\nANIMATHALG0\n\n"
        "\\begin{figure}\\caption{Mesh $h$}\\label{fig:m}\\end{figure}\\end{document}"
    )
    algs = [("\\begin{algorithmic}\\end{algorithmic}", "steps", "alg:1")]
    assert doc(src, "latex", theorems={"obs"}, algorithms=algs) == [
        ("theorem", "Plain $x$ $$y$$", "o"),
        ("equation", "y", "eq:y"),
        ("algorithm", "steps", "alg:1"),
        ("figure", "Mesh $h$", "fig:m"),
    ]


def test_raw_blocks_and_rules() -> None:
    assert doc("```{=latex}\n\\begin{equation}z\\end{equation}\n```\n\n```{=latex}\n\\x\n```") == [
        ("equation", "z", None)
    ]


def test_ast_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(IngestError, match="pandoc:"):
        blocks.ast("x", "nonsense")

    def slow(*a: Any, **k: Any) -> Any:
        raise subprocess.TimeoutExpired("pandoc", 1)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(IngestError, match="timed out"):
        blocks.ast("x", "markdown")


def test_invalid_document() -> None:
    with pytest.raises(IngestError, match="unresolved refs"):
        blocks.document("See \\ref{nowhere}.", "markdown", "s", {}, {})


def test_div_id_labels_first_block() -> None:
    src = "::: {#d .unknown}\nInside.\n:::\n\n::: {#e}\n:::\n\nSee \\ref{d}."
    assert doc(src) == [("paragraph", "Inside.", "d"), ("paragraph", "See d.", ("d",))]
