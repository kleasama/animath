# ruff: noqa: RUF001
import shutil
from pathlib import Path

import pytest

from animath.core.errors import NarrateError
from animath.narrate.g2p import Phonemizer, cut, speakable, split
from tests.narrate.conftest import Script

IPA = {
    "Take": "tˈe^ɪk",
    "one": "wˈʌn",
    "leaf": "lˈiːf",
    "t": "tˈiː",
    "with": "wˈɪð",
    "points": "pˈɔ^ɪnts",
    "64": "sˈɪksti fˈoː^ɹ",
    "hello": "həlˈo^ʊ",
    "world": "wˈɜːld",
    "the": "ðˈə",
}
FAKE = """
args, data = " ".join(sys.argv[1:]), sys.stdin.read()
open(LOG, "a").write(data.replace("\\n", "/") + "|" + args + "\\n")
for ln in data.split("\\n") if "-l" in args else [data.replace("with the", "with_the")]:
    print(" ".join(IPA.get(w, "wɪððə" if w == "with_the" else "pˈɪvət") for w in ln.split()))
"""


@pytest.fixture
def fake(script: Script, tmp_path: Path) -> tuple[str, Path]:
    log = tmp_path / "espeak.log"
    return script(f"LOG, IPA = {str(log)!r}, {IPA!r}\n{FAKE}"), log


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("it,", ("", "it", ",")),
        ("(t)", ("(", "t", ")")),
        ("e.g.,", ("", "e.g.", ",")),
        ("“stop.”", ("“", "stop", ".”")),
        ("—", ("—", "", "")),
        ("H2-matrix", ("", "H2-matrix", "")),
    ],
)
def test_split(word: str, parts: tuple[str, str, str]) -> None:
    assert split(word) == parts


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("The Schur complement of LU.", "The [[S'Ur]] complement of L U"),
        ("RS-S and EFIE, not BLAS", "R S S and E F I E not BLAS"),
        ("A x equals b", "[['eI]] x equals b"),
        ("A stage takes a 3 by 3 matrix A.", "A stage takes a 3 by 3 matrix [['eI]]"),
        ("a plus b over a,", "[['eI]] plus b over [['eI]]"),
        ("xi and mu", "[[ks'aI]] and [[mj'u:]]"),
    ],
)
def test_speakable(text: str, said: str) -> None:
    assert " ".join(speakable(text.split())) == said


def test_ipa_maps_espeak_to_misaki(fake: tuple[str, Path]) -> None:
    cmd, log = fake
    us = Phonemizer(cmd=cmd)
    assert us.ipa("hello world 64") == "həlˈO wˈɜɹld sˈɪksti fˈɔɹ"
    assert us.ipa("  ") == ""
    gb = Phonemizer("en-gb", cmd)
    assert gb.ipa("world 64") == "wˈɜːld sˈɪksti fˈɔːɹ"
    assert gb.solo(["world", "", "64"]) == ["wɜːld", "", "sɪksti fɔːɹ"]
    assert log.read_text().splitlines()[-2:] == [
        "world 64|-q --ipa --tie=^ -v en-gb",
        "world/64|-q --ipa --tie=^ -v en-gb -l 4096",
    ]


def test_words_by_clause_with_marks(fake: tuple[str, Path]) -> None:
    cmd, log = fake
    words = Phonemizer(cmd=cmd).words("Take one leaf, (t) with 64 points.")
    assert words == [
        ("", "tˈAk", ""),
        ("", "wˈʌn", ""),
        ("", "lˈif", ","),
        ("(", "tˈi", ")"),
        ("", "wˈɪð", ""),
        ("", "sˈɪksti fˈɔɹ", ""),
        ("", "pˈYnts", "."),
    ]
    calls = [ln.split("|")[0] for ln in log.read_text().splitlines()]
    assert calls == ["Take/one/leaf/t/with/64/points", "Take one leaf", "t", "with 64 points"]


def test_words_split_where_espeak_joins(fake: tuple[str, Path]) -> None:
    words = Phonemizer(cmd=fake[0]).words("with the pivot")
    assert words == [("", "wɪð", ""), ("", "ðə", ""), ("", "pˈɪvət", "")]


def test_solo_needs_one_line_per_word(script: Script) -> None:
    with pytest.raises(NarrateError, match="gave 1 lines for 2 words"):
        Phonemizer(cmd=script('print("x")')).words("one two")


@pytest.mark.parametrize(
    ("ipa", "solo", "parts"),
    [
        ("fɹʌmðə lˈivz", ["fɹʌm", "ðə", "livz"], ["fɹʌm", "ðə", "lˈivz"]),
        ("fəɹɹˈə", ["fɔɹ", "A"], ["fəɹ", "ɹˈə"]),
        ("əvˈən", ["ʌv", "æn"], ["əv", "ˈən"]),
        ("wˈʌn θˈWzənd pˈYnts", ["wʌn θWzənd", "pYnts"], ["wˈʌn θˈWzənd", "pˈYnts"]),
        ("ˈʌp", ["", "ʌp"], ["", "ˈʌp"]),
        ("", ["", ""], ["", ""]),
    ],
)
def test_cut_at_aligned_word_ends(ipa: str, solo: list[str], parts: list[str]) -> None:
    assert cut(ipa, solo) == parts


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng")
def test_words_real_espeak() -> None:
    text = "A block LU eliminates it, with the Schur complement of the first block."
    words = Phonemizer().words(text)
    assert [w[2] for w in words] == ["", "", "", "", ",", *[""] * 7, "."]
    assert [w[1] for w in words[5:11]] == ["wɪð", "ðə", "ʃˈʊɹ", "kˈɑmplɪmənt", "ʌv", "ðə"]
    assert len(words[2][1].split()) == 2
    assert all(w[1] for w in words)
    assert not any(c in "^ː" for w in words for c in w[1])
