# ruff: noqa: RUF001
import re

TOKEN = re.compile(r"\\[A-Za-z]+|\\.|\s+|.", re.S)
GREEK: dict[str, str] = dict(
    re.findall(
        r"(\w+) (\S)",
        "alpha α beta β gamma γ delta δ epsilon ε varepsilon ε zeta ζ eta η theta θ vartheta ϑ "
        "iota ι kappa κ lambda λ mu μ nu ν xi ξ pi π rho ρ varrho ϱ sigma σ tau τ upsilon υ "
        "phi φ varphi φ chi χ psi ψ omega ω Gamma Γ Delta Δ Theta Θ Lambda Λ Xi Ξ Pi Π Sigma Σ "
        "Phi Φ Psi Ψ Omega Ω",
    )
)
SYMBOLS = GREEK | {
    "infty": "∞", "partial": "∂", "nabla": "∇", "pm": "±", "times": "×", "cdot": "·",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "approx": "≈",
    "sim": "∼", "equiv": "≡", "ll": "≪", "gg": "≫", "in": "∈", "subset": "⊂", "cup": "∪",
    "cap": "∩", "to": "→", "rightarrow": "→", "leftarrow": "←", "mapsto": "↦", "sum": "∑",
    "prod": "∏", "int": "∫", "sqrt": "√", "ldots": "…", "cdots": "⋯", "dots": "…",
    "langle": "⟨", "rangle": "⟩", "prime": "′", "ast": "∗", "circ": "∘", "otimes": "⊗",
    "oplus": "⊕", "perp": "⊥", "top": "⊤", "dagger": "†", "ell": "ℓ", "emptyset": "∅",
}  # fmt: skip
SILENT = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr"}
SILENT |= {"middle", "displaystyle", "quad", "qquad", "limits", "nonumber"}
FONTS = {"mathbf", "mathrm", "mathit", "mathsf", "mathtt", "boldsymbol", "bm", "operatorname"}
TEXT = {"text", "textrm", "textit", "textbf", "mbox"}
ACCENTS = {"hat": "\u0302", "tilde": "\u0303", "bar": "\u0304", "overline": "\u0305"}
ACCENTS |= {"vec": "\u20d7", "dot": "\u0307", "ddot": "\u0308"}
ALPHABETS = {
    "mathcal": "𝒜ℬ𝒞𝒟ℰℱ𝒢ℋℐ𝒥𝒦ℒℳ𝒩𝒪𝒫𝒬ℛ𝒮𝒯𝒰𝒱𝒲𝒳𝒴𝒵",
    "mathbb": "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ",
}
ALPHABETS["mathscr"] = ALPHABETS["mathcal"]
SCRIPTS = {
    "_": ("0123456789+−=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ"),
    "^": (
        "0123456789+−=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW*∗′⊤†",
        "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ*∗′ᵀ†",
    ),
}


def script(body: str, kind: str) -> str:
    """Unicode sub- or superscript when every character has one and `body` is no word."""
    src, dst, body = *SCRIPTS[kind], "".join(body.split())
    if body and all(c in src for c in body) and (len(body) <= 2 or not body.isalpha()):
        return body.translate(str.maketrans(src, dst))
    return kind + (f"({body})" if re.search(r"\W", body) else body)


def written(tex: str) -> str:
    """Compact Unicode form of inline TeX for captions, e.g. L_{21} -> L₂₁."""
    toks, pos = TOKEN.findall(tex), 0

    def arg(text: bool = False) -> str:
        nonlocal pos
        while pos < len(toks) and toks[pos].isspace():
            pos += 1
        pos += 1
        if pos > len(toks):
            return ""
        return seq("}", text) if toks[pos - 1] == "{" else atom(toks[pos - 1], text)

    def atom(t: str, text: bool) -> str:
        nonlocal pos
        name = t[1:]
        if not t.startswith("\\"):
            return {"-": "-" if text else "−", "'": "′", "&": " ", "~": " "}.get(t, t)
        if name in ("frac", "dfrac", "tfrac"):
            a, b = arg(), arg()
            return "/".join(f"({x})" if re.search(r"[+−=±×·/<>≤≥, ]", x) else x for x in (a, b))
        if name in ALPHABETS:
            return arg().translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", ALPHABETS[name]))
        if name in FONTS | TEXT:
            return arg(name in TEXT)
        if name in ACCENTS:
            return arg() + ACCENTS[name]
        if name in ("begin", "end"):
            arg()
            return ""
        if name in SILENT:
            pos += pos < len(toks) and toks[pos] == "."
            return ""
        if name.isalpha():
            return SYMBOLS.get(name, f" {name} ")
        return {"|": "‖", "{": "{", "}": "}", "\\": "; ", "%": "%", "_": "_"}.get(name, "")

    def seq(end: str, text: bool = False) -> str:
        nonlocal pos
        out = ""
        while pos < len(toks) and toks[pos] != end:
            t = toks[pos]
            pos += 1
            if t in ("^", "_"):
                out = out.rstrip() + script(arg(), t) + " " * out.endswith(" ")
            elif t.isspace():
                out += " " * text
            else:
                out += seq("}", text) if t == "{" else atom(t, text)
        pos += 1
        return out

    out = " ".join(re.sub(r"([=<>≤≥≠≈∼≡→←↦∈⊂≪≫])", r" \1 ", seq("")).split())
    return re.sub(r"(?<=[(\[]) | (?=[)\],;.])|(?<=\w) (?=\()", "", out)
