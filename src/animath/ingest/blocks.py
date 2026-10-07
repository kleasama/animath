import json
import re
import subprocess
from collections.abc import Iterable, Sequence
from typing import Any

import pypandoc  # type: ignore[import-untyped]
from pydantic import ValidationError

from animath.core.errors import IngestError
from animath.core.schemas import Block, BlockType, DocIR

Node = dict[str, Any]
TOKEN = "ANIMATHALG"
THEOREMS = frozenset(
    [
        "theorem",
        "lemma",
        "proposition",
        "corollary",
        "definition",
        "remark",
        "example",
        "conjecture",
        "claim",
        "assumption",
        "hypothesis",
        "exercise",
        "problem",
        "notation",
    ]
)
_LABEL = re.compile(r"\\label\{([^}]*)\}")
_NONUM = re.compile(r"\\(?:nonumber|notag)(?![A-Za-z])")
_TEXREF = re.compile(r"\\(eqref|[cC]ref|ref|autoref|cite[tp]?)\*?\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}")
_MATHENV = re.compile(
    r"\s*\\begin\{(equation|displaymath|align|eqnarray|gather|multline)(\*?)\}(.*)"
    r"\\end\{\1\2\}\s*",
    re.S,
)
_INNER = {"align": "aligned", "eqnarray": "aligned", "gather": "gathered", "multline": "gathered"}
_STYLE = {"Emph", "Strong", "Underline", "Strikeout", "Superscript", "Subscript", "SmallCaps"}
_QED = " \u00a0\u25fb\u220e"


def ast(text: str, fmt: str) -> Node:
    cmd = [pypandoc.get_pandoc_path(), "-f", f"{fmt}-auto_identifiers", "-t", "json"]
    try:
        r = subprocess.run(cmd, input=text.encode(), capture_output=True, timeout=300, check=False)
    except subprocess.TimeoutExpired as e:
        raise IngestError("pandoc timed out") from e
    if r.returncode:
        raise IngestError(f"pandoc: {r.stderr.decode().strip()}")
    tree: Node = json.loads(r.stdout)
    return tree


def ir(title: str, blocks: Sequence[Block], macros: dict[str, str], bib: dict[str, str]) -> DocIR:
    try:
        return DocIR(title=title, blocks=tuple(blocks), macros=macros, bib=bib)
    except ValidationError as e:
        raise IngestError(f"invalid document: {e}") from e


def _raw_math(raw: str) -> str | None:
    if (m := _MATHENV.fullmatch(raw)) is None:
        return None
    inner = _INNER.get(m[1])
    return f"\\begin{{{inner}}}{m[3]}\\end{{{inner}}}" if inner else m[3]


def _display(x: Node) -> str | None:
    if x["t"] == "Math" and x["c"][0]["t"] == "DisplayMath":
        tex = str(x["c"][1])
        env = _raw_math(tex)
        return tex if env is None else env
    if x["t"] == "RawInline" and x["c"][0] in ("latex", "tex"):
        return _raw_math(x["c"][1])
    return None


def _clean(tex: str) -> str:
    tex = re.sub(r" {2,}", " ", _NONUM.sub("", _LABEL.sub("", tex)))
    return "\n".join(ln.rstrip() for ln in tex.split("\n")).strip()


def _norm(s: str) -> str:
    return "\n".join(" ".join(ln.split()) for ln in s.replace("\u00a0", " ").split("\n")).strip()


def _cite(keys: list[str], refs: list[str]) -> str:
    refs += keys
    return f"[{'; '.join(keys)}]"


class Builder:
    """Pandoc AST -> DocIR blocks."""

    def __init__(
        self,
        theorems: Iterable[str],
        algorithms: Sequence[tuple[str, str, str | None]],
        numbered: bool,
    ) -> None:
        self.theorems, self.algorithms, self.numbered = frozenset(theorems), algorithms, numbered
        self.out: list[Block] = []
        self.alias: dict[str, str] = {}

    def add(self, type: BlockType, **kw: Any) -> None:
        self.out.append(Block(id=f"b{len(self.out)}", type=type, **kw))

    def equation(self, tex: str) -> None:
        labels = _LABEL.findall(tex)
        self.alias |= dict.fromkeys(labels[1:], labels[0]) if labels else {}
        self.add(BlockType.EQUATION, latex=_clean(tex), label=labels[0] if labels else None)

    def inline(self, xs: Iterable[Node], refs: list[str], eqs: list[str]) -> str:
        parts: list[str] = []
        for x in xs:
            t: str = x["t"]
            c: Any = x.get("c")
            if t == "Str":
                parts.append(c)
            elif t in ("Space", "SoftBreak"):
                parts.append(" ")
            elif t == "LineBreak":
                parts.append("\n")
            elif t in _STYLE:
                parts.append(self.inline(c, refs, eqs))
            elif t == "Quoted":
                q = '"' if c[0]["t"] == "DoubleQuote" else "'"
                parts.append(q + self.inline(c[1], refs, eqs) + q)
            elif t in ("Span", "Link", "Image"):
                kv = dict(c[0][2])
                if "reference" in kv:
                    keys = kv["reference"].split(",")
                    refs += keys
                    s = ", ".join(keys)
                    parts.append(f"({s})" if kv.get("reference-type") == "eqref" else s)
                else:
                    parts.append(self.inline(c[1], refs, eqs))
            elif t == "Code":
                parts.append(c[1])
            elif t == "Cite":
                parts.append(_cite([ci["citationId"] for ci in c[0]], refs))
            elif t == "Note":
                parts.append(f" ({self.text(c, refs, eqs)})")
            elif (tex := _display(x)) is not None:
                eqs.append(tex)
                parts.append(f"$${_clean(tex)}$$")
            elif t == "Math":
                parts.append(f"${c[1]}$")
            elif t == "RawInline" and c[0] in ("latex", "tex"):
                for m in _TEXREF.finditer(c[1]):
                    keys = [k.strip() for k in m[2].split(",")]
                    if m[1].startswith("cite"):
                        parts.append(_cite(keys, refs))
                    else:
                        refs += keys
                        s = ", ".join(keys)
                        parts.append(f"({s})" if m[1] == "eqref" else s)
        return "".join(parts)

    def text(self, blocks: Iterable[Node], refs: list[str], eqs: list[str]) -> str:
        lines: list[str] = []
        for b in blocks:
            t: str = b["t"]
            c: Any = b.get("c")
            if t in ("Para", "Plain"):
                lines.append(self.inline(c, refs, eqs))
            elif t == "BulletList":
                lines += [f"- {self.text(item, refs, eqs)}" for item in c]
            elif t == "OrderedList":
                lines += [f"{i}. {self.text(it, refs, eqs)}" for i, it in enumerate(c[1], 1)]
            elif t in ("Div", "BlockQuote"):
                lines.append(self.text(c[1] if t == "Div" else c, refs, eqs))
            elif t == "CodeBlock":
                lines.append(c[1])
            elif t != "RawBlock":
                lines.append(self.inline(_inlines(c), refs, eqs))
        return _norm("\n".join(lines))

    def container(self, type: BlockType, kids: list[Node], **kw: Any) -> None:
        head = kids[0]["c"] if self.numbered and kids and kids[0]["t"] == "Para" else []
        if head and head[0]["t"] in ("Strong", "Emph"):
            kids = [{"t": "Para", "c": head[1:]}, *kids[1:]]
        refs: list[str] = []
        eqs: list[str] = []
        text = self.text(kids, refs, eqs).rstrip(_QED).lstrip(". ")
        self.add(type, text=text, refs=tuple(dict.fromkeys(refs)), **kw)
        for e in eqs:
            self.equation(e)

    def para(self, xs: list[Node]) -> None:
        seg: list[Node] = []
        for x in [*xs, None]:
            tex = None if x is None else _display(x)
            if x is not None and tex is None:
                seg.append(x)
                continue
            refs: list[str] = []
            eqs: list[str] = []
            text = _norm(self.inline(seg, refs, eqs))
            if text.startswith(TOKEN) and text[len(TOKEN) :].isdigit():
                latex, alg, label = self.algorithms[int(text[len(TOKEN) :])]
                self.add(BlockType.ALGORITHM, text=alg, latex=latex, label=label, env="algorithm")
            elif text:
                self.add(BlockType.PARAGRAPH, text=text, refs=tuple(dict.fromkeys(refs)))
            for e in [*eqs, *([tex] if tex else [])]:
                self.equation(e)
            seg = []

    def blocks(self, blocks: Iterable[Node]) -> None:
        for b in blocks:
            t: str = b["t"]
            c: Any = b.get("c")
            if t in ("Para", "Plain"):
                self.para(c)
            elif t == "Header":
                text = _norm(self.inline(c[2], [], []))
                self.add(
                    BlockType.HEADING, text=text, level=min(max(c[0], 1), 6), label=c[1][0] or None
                )
            elif t == "Div":
                cls = c[0][1][0] if c[0][1] else ""
                label = c[0][0] or None
                if cls in self.theorems:
                    self.container(BlockType.THEOREM, c[1], env=cls, label=label)
                elif cls == "proof":
                    self.container(BlockType.PROOF, c[1], env=cls, label=label)
                else:
                    self.blocks(c[1])
            elif t in ("BulletList", "OrderedList"):
                self.container(BlockType.LIST, [b])
            elif t == "BlockQuote":
                self.blocks(c)
            elif t == "Figure":
                self.container(BlockType.FIGURE, c[1][1], label=c[0][0] or None)
            elif t == "CodeBlock":
                self.add(BlockType.CODE, text=c[1])
            elif t == "RawBlock":
                if c[0] in ("latex", "tex") and (tex := _raw_math(c[1])) is not None:
                    self.equation(tex)
            elif t not in ("HorizontalRule", "Null"):
                self.container(BlockType.PARAGRAPH, [b])

    def result(self) -> list[Block]:
        return [
            b.model_copy(
                update={"refs": tuple(dict.fromkeys(self.alias.get(r, r) for r in b.refs))}
            )
            for b in self.out
        ]


def _inlines(x: Any) -> list[Node]:
    """All inline nodes inside an arbitrary AST fragment, in order."""
    if isinstance(x, dict):
        if x.get("t") in _INLINE:
            return [x]
        x = x.get("c")
    if isinstance(x, list):
        out: list[Node] = []
        for y in x:
            got = _inlines(y)
            out += got if not out or not got else [{"t": "Space"}, *got]
        return out
    return []


_INLINE = {"Str", "Math", "Code", "Cite", "Link", "Emph", "Strong", "Span", "RawInline", "Quoted"}


def document(
    text: str,
    fmt: str,
    stem: str,
    macros: dict[str, str],
    bib: dict[str, str],
    theorems: Iterable[str] = THEOREMS,
    algorithms: Sequence[tuple[str, str, str | None]] = (),
) -> DocIR:
    tree = ast(text, fmt)
    b = Builder(theorems, algorithms, numbered=fmt == "latex")
    b.blocks(tree["blocks"])
    out = b.result()
    title = tree["meta"].get("title", {})
    if title.get("t") == "MetaInlines":
        name = _norm(b.inline(title["c"], [], []))
    else:
        name = next((x.text for x in out if x.type is BlockType.HEADING), stem)
    return ir(name, out, macros, bib)
