import gzip
import io
import logging
import tarfile
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytest

from animath.core.errors import IngestError
from animath.core.schemas import BlockType, Usage
from animath.ingest import pdf
from animath.ingest.pdf import TBib, TBlock, Transcript
from tests.ingest.conftest import Fake

MAIN = b"\\documentclass{article}\\begin{document}\\section{S}x\\end{document}"


def blank(n: int) -> bytes:
    doc = pdfium.PdfDocument.new()
    for _ in range(n):
        doc.new_page(200, 100)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        d = tarfile.TarInfo("d")
        d.type = tarfile.DIRTYPE
        t.addfile(d)
    return gzip.compress(buf.getvalue())


def tb(type: str, page: int = 1, **kw: Any) -> TBlock:
    base: dict[str, Any] = dict(text="", latex=None, label=None, level=None, env=None, refs=[])
    return TBlock.model_validate({**base, "type": type, "page": page, **kw})


def t(*blocks: TBlock, title: str | None = None, bib: Sequence[TBib] = ()) -> Transcript:
    return Transcript(title=title, blocks=list(blocks), bib=list(bib))


def test_arxiv_id() -> None:
    assert pdf.arxiv_id("x arXiv:2101.01234v2 [math.NA] 1 Jan") == "2101.01234v2"
    assert pdf.arxiv_id("arXiv: math.NA/0601001") == "math.NA/0601001"
    assert pdf.arxiv_id("arXiv:hep-th/9901001") == "hep-th/9901001"
    assert pdf.arxiv_id("no id") is None


def test_unpack_variants() -> None:
    files, main = pdf.unpack(
        tar({"a/x.tex": MAIN, "m.tex": MAIN, "/abs.tex": b"", "../u": b""})
    ) or ({}, "")
    assert (sorted(files), main) == (["a/x.tex", "m.tex"], "m.tex")
    assert pdf.unpack(gzip.compress(MAIN)) == ({"main.tex": MAIN}, "main.tex")
    assert pdf.unpack(gzip.compress(b"%PDF-1.5")) is None
    with pytest.raises(IngestError, match="no main"):
        pdf.unpack(tar({"x.tex": b"\\section{a}"}))
    with pytest.raises(IngestError, match="bad e-print"):
        pdf.unpack(b"\x1f\x8bbroken")


def test_fetch_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def ok(req: urllib.request.Request, timeout: float) -> Any:
        assert req.get_header("User-agent") == "animath"
        return io.BytesIO(b"payload")

    monkeypatch.setattr(urllib.request, "urlopen", ok)
    assert pdf.fetch_url("https://x") == b"payload"

    def fail(req: urllib.request.Request, timeout: float) -> Any:
        raise urllib.error.URLError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(IngestError, match="fetch https://x"):
        pdf.fetch_url("https://x")


def test_render_and_errors() -> None:
    pages = pdf.render(blank(2))
    assert len(pages) == 2
    assert all(p.startswith(b"\x89PNG") for p in pages)
    with pytest.raises(IngestError, match="unreadable PDF"):
        pdf.render(b"not a pdf")


def test_transcribe_repairs_then_gives_up() -> None:
    eq = tb("equation", latex="x")
    llm = Fake(t(eq), t(eq), t(eq))
    seen: list[list[str]] = []

    def check(eqs: Sequence[str], macros: Mapping[str, str]) -> dict[int, str]:
        seen.append(list(eqs))
        return {0: "boom"} if len(seen) < 2 else {}

    out, usage = pdf.transcribe(llm, [b"p1", b"p2"], range(0, 2), check, 3)
    assert out.blocks == [eq]
    assert usage == Usage(input_tokens=10)
    assert llm.calls[0] == ("Pages 1-2 of 2.", 2)
    assert "'x': boom" in llm.calls[1][0]
    with pytest.raises(IngestError, match="pages 1-1: equations fail after 0 retries"):
        pdf.transcribe(llm, [b"p"], range(0, 1), lambda e, m: {0: "bad"}, 0)


def test_merge_normalises_llm_output() -> None:
    parts = [
        t(
            tb("heading", text="H", label="sec:1", level=9),
            tb("equation", text="lost", label="sec:1"),
        ),
        t(
            tb("paragraph", page=0, text="see", refs=["sec:1", "ghost", "k"], level=2),
            title="T",
            bib=[TBib(key="k", text="K")],
        ),
    ]
    doc = pdf.merge(parts, "stem")
    assert doc.title == "T"
    assert [(b.type, b.label, b.level, b.page) for b in doc.blocks] == [
        (BlockType.HEADING, "sec:1", 6, 1),
        (BlockType.PARAGRAPH, None, None, 1),
        (BlockType.PARAGRAPH, None, None, 1),
    ]
    assert doc.blocks[2].refs == ("sec:1", "k")
    assert pdf.merge([t(tb("paragraph", text="x"))], "stem").title == "stem"


def test_parse_chunks_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = Fake(t(tb("paragraph", text="a")), t(tb("paragraph", page=5, text="b")))
    doc, usage = pdf.parse(blank(5), "s", llm, fetch=None, workers=1)
    assert [c for c in llm.calls] == [("Pages 1-4 of 5.", 4), ("Pages 5-5 of 5.", 1)]
    assert [b.text for b in doc.blocks] == ["a", "b"]
    assert usage == Usage(input_tokens=10)


def test_parse_prefers_arxiv_source(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(pdf, "first_text", lambda data: "arXiv:2101.01234v1")
    urls: list[str] = []

    def fetch(url: str) -> bytes:
        urls.append(url)
        return tar({"m.tex": MAIN})

    doc, usage = pdf.parse(b"", "s", Fake(), fetch=fetch)
    assert urls == ["https://arxiv.org/e-print/2101.01234v1"]
    assert (doc.blocks[0].text, usage) == ("S", Usage())

    def down(url: str) -> bytes:
        raise IngestError("down")

    llm = Fake(t(tb("paragraph", text="p")))
    with caplog.at_level(logging.WARNING):
        doc, _ = pdf.parse(blank(1), "s", llm, fetch=down)
    assert "arXiv 2101.01234v1 source unusable: down" in caplog.text
    assert doc.blocks[0].text == "p"
    llm = Fake(t(tb("paragraph", text="q")))
    assert (
        pdf.parse(blank(1), "s", llm, fetch=lambda u: gzip.compress(b"%PDF"))[0].blocks[0].text
        == "q"
    )


def test_first_text_reads_golden(golden: Path) -> None:
    assert pdf.first_text((golden / "gauss" / "gauss.pdf").read_bytes()).startswith("Gauss")
