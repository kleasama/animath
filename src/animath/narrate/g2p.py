# ruff: noqa: RUF001
import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from itertools import accumulate, pairwise

from animath.core.errors import NarrateError
from animath.narrate.proc import run

LEXICON = {
    "banach": "b'A:nA:k",
    "cauchy": "koUS'i:",
    "dirichlet": "dIrIS'leI",
    "fourier": "f'UrieI",
    "galerkin": "g@l'ErkIn",
    "lanczos": "l'A:ntSoUs",
    "legendre": "l@Z'A:ndr@",
    "mu": "mj'u:",
    "neumann": "n'OIm@n",
    "schur": "S'Ur",
    "seidel": "z'aId@L",
    "xi": "ks'aI",
}
WORDS = frozenset({"BLAS", "NASA", "RAM", "SIAM"})
OPS = frozenset(
    {"plus", "minus", "times", "over", "equals", "inverse", "transpose", "star", "squared", "hat"}
)
OPEN, CLOSE = '(“"', '.,;:!?)”"…—'
ACRONYM = re.compile(r"[A-Z]{2,4}|[A-Z]+(?:-[A-Z]+)+")
ABBREV = re.compile(r"(?:[A-Za-z]\.){2,}")
E2M = {
    "en-us": {"o^ʊ": "O", "ɜːɹ": "ɜɹ", "ɜː": "ɜɹ", "ɪə": "iə", "ː": ""},
    "en-gb": {"e^ə": "ɛː", "iə": "ɪə", "ə^ʊ": "Q"},
}
COMMON = {
    "a^ɪ": "I",
    "a^ʊ": "W",
    "d^ʒ": "ʤ",
    "e^ɪ": "A",
    "t^ʃ": "ʧ",
    "ɔ^ɪ": "Y",
    "ə^l": "ᵊl",
    "e": "A",
    "r": "ɹ",
    "x": "k",
    "ç": "k",
    "ɐ": "ə",
    "ɚ": "əɹ",
    "ɬ": "l",
    "ʲ": "",
    "ʔ": "t",
    "o": "ɔ",
    "^": "",
}

STRESS = "ˈˌ"
Word = tuple[str, str, str]


def split(word: str) -> Word:
    """(leading marks, core, trailing marks); abbreviations such as 'e.g.' keep their periods."""
    if ABBREV.fullmatch(word.strip(OPEN + CLOSE.replace(".", ""))):
        core = word.strip(OPEN + CLOSE.replace(".", ""))
    else:
        core = word.strip(OPEN + CLOSE)
    a = word.find(core) if core else len(word)
    return word[:a], core, word[a + len(core) :]


def speakable(words: Sequence[str]) -> list[str]:
    """Spoken form of each core: lexicon entries, spelled acronyms, the letter A in formulas."""
    cores = [split(w) for w in words]
    out = []
    for i, (_, core, post) in enumerate(cores):
        nxt = cores[i + 1][1] if i + 1 < len(cores) and not post else ""
        if core.lower() in LEXICON:
            core = f"[[{LEXICON[core.lower()]}]]"
        elif ACRONYM.fullmatch(core) and core not in WORDS:
            core = " ".join(c for c in core if c.isalpha())
        elif core in ("a", "A") and (not nxt or (nxt.isalpha() and len(nxt) == 1) or nxt in OPS):
            core = "[['eI]]"
        out.append(core)
    return out


def cut(ipa: str, solo: Sequence[str]) -> list[str]:
    """`ipa` cut where difflib aligns the spaces joining the stand-alone forms `solo`."""
    keep = [i for i, c in enumerate(ipa) if c not in STRESS]
    b, a = " ".join(solo), "".join(ipa[i] for i in keep)
    ops = SequenceMatcher(None, b, a, autojunk=False).get_opcodes()
    xs = [n + k for k, n in enumerate(accumulate(map(len, solo[:-1])))]
    ys = [
        next(
            j1 + round((x - i1) * (j2 - j1) / (i2 - i1))
            for _, i1, i2, j1, j2 in ops
            if i1 <= x < i2
        )
        for x in xs
    ]
    at = [0, *(keep[y - 1] + 1 if y else 0 for y in ys), len(ipa)]
    return [ipa[p:q].strip() for p, q in pairwise(at)]


class Phonemizer:
    """Words to Kokoro phonemes: espeak-ng IPA per clause, mapped to the misaki inventory."""

    def __init__(self, lang: str = "en-us", cmd: str = "espeak-ng") -> None:
        table = COMMON | E2M[lang]
        self.table = table
        self.pattern = re.compile("|".join(map(re.escape, sorted(table, key=len, reverse=True))))
        self.cmd = [cmd, "-q", "--ipa", "--tie=^", "-v", lang]

    def mapped(self, out: bytes) -> str:
        return self.pattern.sub(lambda m: self.table[m[0]], out.decode())

    def ipa(self, text: str) -> str:
        return " ".join(self.mapped(run(self.cmd, text.encode())).split())

    def solo(self, cores: Sequence[str]) -> list[str]:
        """Stand-alone IPA of each core, one clause per line, without stress marks."""
        todo = [c for c in cores if c]
        out = run([*self.cmd, "-l", "4096"], "\n".join(todo).encode()) if todo else b""
        lines = self.mapped(out).translate(str.maketrans("", "", STRESS)).splitlines()
        if len(lines) != len(todo):
            raise NarrateError(f"{self.cmd[0]} gave {len(lines)} lines for {len(todo)} words")
        it = (" ".join(ln.split()) for ln in lines)
        return [next(it) if c else "" for c in cores]

    def words(self, text: str) -> list[Word]:
        """(leading marks, phonemes, trailing marks) of each whitespace-separated word of `text`."""
        parts = [split(w) for w in text.split()]
        said = speakable(text.split())
        solo = self.solo(said)
        out: list[Word] = []
        start = 0
        for i, (_, _, post) in enumerate(parts):
            if i + 1 < len(parts) and not post and not parts[i + 1][0]:
                continue
            phones = cut(self.ipa(" ".join(said[start : i + 1])), solo[start : i + 1])
            out += [(p, w, q) for (p, _, q), w in zip(parts[start : i + 1], phones, strict=True)]
            start = i + 1
        return out
