import pytest

from animath.core.errors import IngestError
from animath.ingest import latex


def test_flatten_resolves_inputs_relative_to_root_and_strips_comments() -> None:
    files = {
        "doc/main.tex": "A % hidden\n\\input{ch/one}\\include ch/two.tex 50\\% \\\\% gone",
        "doc/ch/one.tex": "B\\input{ch/two}",
        "doc/ch/two.tex": "C",
    }
    assert latex.flatten(files, "doc/main.tex") == "A \nBCC 50\\% \\\\"


@pytest.mark.parametrize(
    ("files", "msg"),
    [
        ({"a.tex": "\\input{b}", "b.tex": "\\input{a}"}, "cycle: a.tex -> b.tex -> a.tex"),
        ({"a.tex": "\\input{nope}"}, "missing input 'nope'"),
    ],
)
def test_flatten_errors(files: dict[str, str], msg: str) -> None:
    with pytest.raises(IngestError, match=msg):
        latex.flatten(files, "a.tex")


def test_macros_keep_full_declarations() -> None:
    src = (
        r"\newcommand{\R}{\mathbb{R}}\renewcommand\v[2][x]{#1_{#2}}"
        r"\providecommand*{\e}{\mathrm{e}}\DeclareMathOperator*{\argmin}{arg\,min}"
        r"\def\abs#1{\lvert#1\rvert}\newcommand{\set}[1]{\{#1\}}"
    )
    m = latex.macros(src)
    assert m == {
        "\\R": r"\newcommand{\R}{\mathbb{R}}",
        "\\v": r"\renewcommand\v[2][x]{#1_{#2}}",
        "\\e": r"\providecommand*{\e}{\mathrm{e}}",
        "\\argmin": r"\DeclareMathOperator*{\argmin}{arg\,min}",
        "\\abs": r"\def\abs#1{\lvert#1\rvert}",
        "\\set": r"\newcommand{\set}[1]{\{#1\}}",
    }


def test_group_and_unbalanced() -> None:
    assert latex.group("{a{b}\\}c}d", 0) == 9
    with pytest.raises(IngestError, match="unbalanced"):
        latex.group("{a{b}", 0)


def test_bibliographies() -> None:
    items = latex.bibitems(
        "\\begin{thebibliography}{9}\\bibitem[S86]{s} Y.~Saad, \\emph{GMRES}, 1986."
        "\n\\bibitem{t}  L. N. Trefethen \\& D. Bau.\\end{thebibliography}"
    )
    assert items == {"s": "Y. Saad, GMRES, 1986.", "t": "L. N. Trefethen & D. Bau."}
    bib = latex.bibtex(
        '@comment{x}@string{j = "J"}@Book{tb, title = {Numerical {L}inear Algebra},'
        ' author = "Trefethen, L. N.", year = 1997}@misc{m, note={n}}'
    )
    assert bib == {"tb": "Trefethen, L. N., Numerical Linear Algebra, 1997", "m": ""}


def test_steps_algpseudocode() -> None:
    src = r"""\begin{algorithmic}
\Function{CG}{$A, b$}\Comment{conjugate gradients}
\While{$\|r\| > \epsilon$}
\If{$k=0$} \State $p \gets r$ \ElsIf{$k>5$} \State stop \Else \State $p \gets r + \beta p$
\EndIf
\Repeat \State relax \Until{done}
\Loop \State spin \EndLoop
\ForAll{$i$} \Statex skip \EndFor
\EndWhile
\State \Return $x$
\EndFunction
\Procedure{P}{} \EndProcedure
\Ensure $x$
\end{algorithmic}"""
    assert latex.steps(src).split("\n") == [
        "function CG($A, b$) ▷ conjugate gradients",
        "  while $\\|r\\| > \\epsilon$ do",
        "    if $k=0$ then",
        "      $p \\gets r$",
        "    else if $k>5$ then",
        "      stop",
        "    else",
        "      $p \\gets r + \\beta p$",
        "    end if",
        "    repeat",
        "      relax",
        "    until done",
        "    loop",
        "      spin",
        "    end loop",
        "    for all $i$ do",
        "      skip",
        "    end for",
        "  end while",
        "  return $x$",
        "end function",
        "procedure P()",
        "end procedure",
        "Ensure: $x$",
    ]


def test_steps_legacy_algorithmic() -> None:
    src = r"\begin{algorithmic}\REQUIRE $n$ \FOR{$i=1$ to $n$} \STATE $s \gets s+i$ \ENDFOR"
    assert latex.steps(src) == "Require: $n$\nfor $i=1$ to $n$ do\n  $s \\gets s+i$\nend for"
    assert latex.steps(r"\Comment{c} \State x") == "▷ c\nx"


def test_algorithms_tokenised() -> None:
    src = "a\\begin{algorithmic}\\State x\\end{algorithmic}b"
    out, found = latex.algorithms(src)
    assert out == "a\n\nANIMATHALG0\n\nb"
    assert found == [("\\begin{algorithmic}\\State x\\end{algorithmic}", "x", None)]


def test_parse_prefers_bbl_and_decodes_latin1() -> None:
    main = (
        "\\documentclass{article}\\begin{document}Caf\xe9 \\cite{k}\\bibliography{r}\\end{document}"
    )
    bbl = "\\begin{thebibliography}{1}\\bibitem{k} K.\\end{thebibliography}"
    doc = latex.parse({"m.tex": main.encode("latin-1"), "m.bbl": bbl.encode()}, "m.tex")
    assert doc.blocks[0].text == "Café [k]"
    assert doc.bib == {"k": "K."}
    assert doc.title == "m"


def test_parse_bib_files_and_missing_bib() -> None:
    main = b"\\begin{document}\\cite{k}\\bibliography{r, s.bib}\\end{document}"
    files = {"m.tex": main, "r.bib": b"@book{k, title={T}}", "s.bib": b""}
    assert latex.parse(files, "m.tex").bib == {"k": "T"}
    with pytest.raises(IngestError, match=r"missing bibliography 'r\.bib'"):
        latex.parse({"m.tex": main}, "m.tex")
