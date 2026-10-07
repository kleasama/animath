import re
from collections.abc import Mapping
from pathlib import PurePosixPath

from animath.core.errors import IngestError
from animath.core.schemas import DocIR
from animath.ingest import blocks

_COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")
_INPUT = re.compile(r"\\(?:input|include)(?![A-Za-z])\s*(?:\{([^}]*)\}|([^\s\\{}]+))")
_DECL = re.compile(
    r"\\(?:(?:new|renew|provide)command\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*(?:\[\d\]\s*)?"
    r"(?:\[[^\]]*\]\s*)?|DeclareMathOperator\*?\s*\{\s*\\([A-Za-z@]+)\s*\}\s*"
    r"|def\s*\\([A-Za-z@]+)\s*(?:#\d)*\s*)(?=\{)"
)
_THEBIB = re.compile(
    r"\\begin\{thebibliography\}\s*(?:\{[^}]*\})?(.*?)\\end\{thebibliography\}", re.S
)
_BIBITEM = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")
_BIBFILES = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^}]*)\}")
_FIELD = re.compile(r"(\w+)\s*=\s*")
_NEWTHM = re.compile(r"\\newtheorem\*?\s*\{([^}]*)\}")
_ALG = re.compile(r"\\begin\{(algorithm\*?|algorithmic)\}.*?\\end\{\1\}", re.S)
_KW = {
    "state": "{}",
    "statex": "{}",
    "require": "Require: {}",
    "ensure": "Ensure: {}",
    "return": "return {}",
    "if": "if {} then",
    "elsif": "else if {} then",
    "else": "else",
    "endif": "end if",
    "forall": "for all {} do",
    "for": "for {} do",
    "endfor": "end for",
    "while": "while {} do",
    "endwhile": "end while",
    "repeat": "repeat",
    "until": "until {}",
    "loop": "loop",
    "endloop": "end loop",
    "function": "function {}({})",
    "endfunction": "end function",
    "procedure": "procedure {}({})",
    "endprocedure": "end procedure",
    "comment": "▷ {}",
}
_ARGS = {"if": 1, "elsif": 1, "for": 1, "forall": 1, "while": 1, "until": 1, "comment": 1}
_ARGS |= {"function": 2, "procedure": 2}
_OPEN = {"if", "elsif", "else", "for", "forall", "while", "repeat", "loop", "function", "procedure"}
_CLOSE = {"elsif", "else", "endif", "endfor", "endwhile", "until", "endloop", "endfunction"}
_CLOSE |= {"endprocedure"}
_KWRE = re.compile(r"\\(" + "|".join(sorted(_KW, key=len, reverse=True)) + r")(?![A-Za-z])", re.I)


def decode(data: bytes) -> str:
    try:
        return data.decode()
    except UnicodeDecodeError:
        return data.decode("latin-1")


def group(s: str, i: int) -> int:
    """Index after the brace group opening at s[i]."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return j + 1
    raise IngestError(f"unbalanced braces from offset {i}: {s[i : i + 40]!r}")


def strip_comments(s: str) -> str:
    return "\n".join(_COMMENT.sub(r"\1", ln) for ln in s.splitlines())


def flatten(files: Mapping[str, str], entry: str, stack: tuple[str, ...] = ()) -> str:
    """Entry with comments removed and \\input/\\include resolved relative to the root file."""
    if entry in stack:
        raise IngestError(f"input cycle: {' -> '.join((*stack, entry))}")
    root = PurePosixPath((stack or (entry,))[0]).parent

    def sub(m: re.Match[str]) -> str:
        name = (m[1] or m[2]).strip()
        for cand in (name, name + ".tex"):
            if (p := str(root / cand)) in files:
                return flatten(files, p, (*stack, entry))
        raise IngestError(f"{entry}: missing input {name!r}")

    return _INPUT.sub(sub, strip_comments(files[entry]))


def macros(src: str) -> dict[str, str]:
    """Macro name -> full declaration."""
    return {
        "\\" + (m[1] or m[2] or m[3]): src[m.start() : group(src, m.end())]
        for m in _DECL.finditer(src)
    }


def plain(s: str) -> str:
    s = re.sub(r"\\[A-Za-z]+\*?\s*", "", s.replace("~", " "))
    s = re.sub(r"\\(.)", r"\1", s).replace("{", "").replace("}", "")
    return " ".join(s.split())


def bibitems(src: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for body in _THEBIB.findall(src):
        parts = _BIBITEM.split(body)
        out |= {k.strip(): plain(t) for k, t in zip(parts[1::2], parts[2::2], strict=True)}
    return out


def bibtex(src: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"@(\w+)\s*(?=\{)", src):
        if m[1].lower() in ("comment", "string", "preamble"):
            continue
        key, _, body = src[m.end() + 1 : group(src, m.end()) - 1].partition(",")
        fields: dict[str, str] = {}
        i = 0
        while f := _FIELD.search(body, i):
            i = f.end()
            if body.startswith("{", i):
                j = group(body, i)
            elif body.startswith('"', i):
                j = body.index('"', i + 1) + 1
            else:
                j = body.find(",", i) % (len(body) + 1)
            fields[f[1].lower()] = plain(body[i:j].strip('"'))
            i = j
        keys = ("author", "title", "journal", "booktitle", "publisher", "year")
        out[key.strip()] = ", ".join(fields[k] for k in keys if k in fields)
    return out


def steps(src: str) -> str:
    """Plain-text listing of algorithmic(x) pseudocode."""
    toks = list(_KWRE.finditer(src))
    lines: list[str] = []
    depth = 0
    for k, m in enumerate(toks):
        kw = m[1].lower()
        rest = src[m.end() : toks[k + 1].start() if k + 1 < len(toks) else len(src)]
        args = []
        for _ in range(_ARGS.get(kw, 0)):
            rest = rest.lstrip()
            j = group(rest, 0) if rest.startswith("{") else 0
            args.append(rest[1 : j - 1] if j else "")
            rest = rest[j:]
        rest = " ".join(re.sub(r"\\end\{algorithmic\}.*", "", rest, flags=re.S).split())
        if "{}" in _KW[kw] and not args:
            args, rest = [rest], ""
        line = (_KW[kw].format(*args) + " " + rest).strip()
        if not line or (kw == "comment" and lines):
            lines[-1:] = [f"{lines[-1]} {line}".rstrip()] if lines else []
            continue
        depth -= kw in _CLOSE
        lines.append("  " * max(depth, 0) + line)
        depth += kw in _OPEN
    return "\n".join(lines)


def algorithms(src: str) -> tuple[str, list[tuple[str, str, str | None]]]:
    """Source with algorithm environments replaced by tokens; (latex, text, label) per token."""
    found: list[tuple[str, str, str | None]] = []

    def sub(m: re.Match[str]) -> str:
        env = m[0]
        cap = ""
        if (c := re.search(r"\\caption\s*(?=\{)", env)) is not None:
            cap = plain(env[c.end() + 1 : group(env, c.end()) - 1])
        label = re.search(r"\\label\{([^}]*)\}", env)
        text = "\n".join(filter(None, (cap, steps(env))))
        found.append((env, text, label[1] if label else None))
        return f"\n\n{blocks.TOKEN}{len(found) - 1}\n\n"

    return _ALG.sub(sub, src), found


def parse(files: Mapping[str, bytes], entry: str) -> DocIR:
    texts = {p: decode(b) for p, b in files.items() if p.endswith((".tex", ".bib", ".bbl"))}
    src = flatten(texts, entry)
    bib = bibitems(src)
    bbl = str(PurePosixPath(entry).with_suffix(".bbl"))
    if bbl in texts:
        bib |= bibitems(texts[bbl])
    else:
        root = PurePosixPath(entry).parent
        for m in _BIBFILES.finditer(src):
            for name in m[1].split(","):
                p = str(root / name.strip())
                p = p if p.endswith(".bib") else p + ".bib"
                if p not in texts:
                    raise IngestError(f"missing bibliography {p!r}")
                bib |= bibtex(texts[p])
    src, algs = algorithms(_THEBIB.sub("", src))
    return blocks.document(
        src,
        "latex",
        PurePosixPath(entry).stem,
        macros(src),
        bib,
        blocks.THEOREMS | set(_NEWTHM.findall(src)),
        algs,
    )
