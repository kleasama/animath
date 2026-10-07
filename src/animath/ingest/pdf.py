import gzip
import io
import logging
import re
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pydantic import BaseModel

from animath.core.errors import IngestError
from animath.core.schemas import Block, BlockType, DocIR, Usage
from animath.ingest import blocks, latex
from animath.ingest.check import Check
from animath.llm import LLM

Fetch = Callable[[str], bytes]
CHUNK = 4
SCALE = 2.0
ARXIV = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?")
SYSTEM = """Transcribe the given pages of a mathematical document into blocks, in reading order.
- Types: heading (level 1-6), paragraph, equation, theorem, proof, algorithm, figure, list, code.
- Inline math in text as $...$. Each display equation is one equation block whose latex is the
  body only, without delimiters, \\label or numbering; multi-line displays use aligned.
- Labels from printed numbers: eq:<n>, sec:<n>, thm:<n> (env gives the kind), alg:<n>, fig:<n>.
- refs lists the labels and citation keys a block cites; citation keys are the printed labels.
- Theorem-like and proof text includes its displayed equations as $$...$$.
- Figures: caption only. Algorithms: one step per line.
- Omit running heads, page numbers, footnote marks. Transcribe the reference list into bib.
- page is the 1-based page index within the document.
- title is the document title if it appears on these pages, else null."""


class TBlock(BaseModel):
    type: BlockType
    text: str
    latex: str | None
    label: str | None
    level: int | None
    env: str | None
    refs: list[str]
    page: int


class TBib(BaseModel):
    key: str
    text: str


class Transcript(BaseModel):
    title: str | None
    blocks: list[TBlock]
    bib: list[TBib]


def fetch_url(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "animath"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data: bytes = r.read()
            return data
    except (urllib.error.URLError, OSError) as e:
        raise IngestError(f"fetch {url}: {e}") from e


def arxiv_id(text: str) -> str | None:
    m = ARXIV.search(text)
    return None if m is None else m[1] + (m[2] or "")


def unpack(data: bytes) -> tuple[dict[str, bytes], str] | None:
    """arXiv e-print -> (files, main .tex); None when the e-print is a PDF."""
    try:
        data = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        if data[:4] == b"%PDF":
            return None
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            files = {}
            for m in tar.getmembers():
                p = PurePosixPath(m.name)
                if m.isfile() and not p.is_absolute() and ".." not in p.parts:
                    f = tar.extractfile(m)
                    files[str(p)] = f.read() if f else b""
    except tarfile.ReadError:
        files = {"main.tex": data}
    except (OSError, EOFError) as e:
        raise IngestError(f"bad e-print: {e}") from e
    mains = sorted(
        (p.count("/"), p)
        for p, b in files.items()
        if p.endswith(".tex") and b"\\documentclass" in b and b"\\begin{document}" in b
    )
    if not mains:
        raise IngestError("e-print has no main .tex file")
    return files, mains[0][1]


def render(data: bytes) -> list[bytes]:
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise IngestError(f"unreadable PDF: {e}") from e
    pages = []
    for page in doc:
        buf = io.BytesIO()
        page.render(scale=SCALE).to_pil().save(buf, format="PNG")
        pages.append(buf.getvalue())
    doc.close()
    return pages


def first_text(data: bytes) -> str:
    doc = pdfium.PdfDocument(data)
    try:
        return str(doc[0].get_textpage().get_text_bounded())
    finally:
        doc.close()


def transcribe(
    llm: LLM, pages: list[bytes], r: range, check: Check | None, retries: int
) -> tuple[Transcript, Usage]:
    base = prompt = f"Pages {r.start + 1}-{r.stop} of {len(pages)}."
    usage = Usage()
    for _ in range(retries + 1):
        t, u = llm.parse(Transcript, SYSTEM, prompt, [pages[i] for i in r])
        usage += u
        eqs = [b.latex for b in t.blocks if b.type is BlockType.EQUATION and b.latex]
        bad = check(eqs, {}) if check else {}
        if not bad:
            return t, usage
        listing = "\n".join(f"{eqs[i]!r}: {msg}" for i, msg in sorted(bad.items()))
        prompt = f"{base}\nYour previous transcription had LaTeX errors; fix them:\n{listing}"
    raise IngestError(f"pages {r.start + 1}-{r.stop}: equations fail after {retries} retries")


def merge(parts: list[Transcript], stem: str) -> DocIR:
    bib = {e.key: e.text for t in parts for e in t.bib}
    out: list[Block] = []
    seen: set[str] = set()
    for b in (b for t in parts for b in t.blocks):
        eq = b.type is BlockType.EQUATION
        label = b.label if b.label and b.label not in seen else None
        seen |= {label} if label else set()
        out.append(
            Block(
                id=f"b{len(out)}",
                type=b.type if b.latex or not eq else BlockType.PARAGRAPH,
                text=b.text,
                latex=b.latex,
                label=label,
                level=min(max(b.level or 1, 1), 6) if b.type is BlockType.HEADING else None,
                env=b.env,
                refs=tuple(b.refs),
                page=max(b.page, 1),
            )
        )
    known = seen | bib.keys()
    out = [b.model_copy(update={"refs": tuple(r for r in b.refs if r in known)}) for b in out]
    title = next((t.title for t in parts if t.title), stem)
    return blocks.ir(title, out, {}, bib)


def parse(
    data: bytes,
    stem: str,
    llm: LLM,
    fetch: Fetch | None = None,
    check: Check | None = None,
    retries: int = 3,
    workers: int = 1,
) -> tuple[DocIR, Usage]:
    """arXiv source if found, else page rasters transcribed by the LLM."""
    if fetch is not None and (aid := arxiv_id(first_text(data))) is not None:
        try:
            src = unpack(fetch(f"https://arxiv.org/e-print/{aid}"))
        except IngestError as e:
            logging.getLogger(__name__).warning("arXiv %s source unusable: %s", aid, e)
        else:
            if src is not None:
                return latex.parse(*src), Usage()
    pages = render(data)
    chunks = [range(i, min(i + CHUNK, len(pages))) for i in range(0, len(pages), CHUNK)]
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda r: transcribe(llm, pages, r, check, retries), chunks))
    usage = Usage()
    for _, u in res:
        usage += u
    return merge([t for t, _ in res], stem), usage
