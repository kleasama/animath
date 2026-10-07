"""Stage Φ1: SourceBundle -> DocIR."""

from pathlib import PurePosixPath

from animath.core.hashing import digest_of
from animath.core.schemas import DocIR, SourceBundle, SourceFormat, Usage
from animath.core.store import Store
from animath.ingest import blocks, latex, pdf
from animath.ingest.check import Check, compile_errors
from animath.ingest.pdf import Fetch, fetch_url
from animath.llm import LLM

VERSION = "1"
__all__ = ["VERSION", "Check", "Fetch", "compile_errors", "fetch_url", "run"]


def run(
    bundle: SourceBundle,
    store: Store,
    llm: LLM,
    fetch: Fetch | None = None,
    check: Check | None = None,
    workers: int = 1,
) -> tuple[DocIR, Usage]:
    """Ingest `bundle`; skipped iff a DocIR is indexed under the stage key (Invariant 4.1.2)."""
    key = Store.key("ingest", VERSION, digest_of(bundle), str(fetch is not None), str(bool(check)))
    if (doc := store.lookup(DocIR, key)) is not None:
        return doc, Usage()
    files = {f.path: store.get_blob(f.blob) for f in bundle.files}
    stem = PurePosixPath(bundle.entry).stem
    usage = Usage()
    if bundle.format is SourceFormat.MD:
        text = latex.decode(files[bundle.entry])
        bib: dict[str, str] = {}
        for p in sorted(p for p in files if p.endswith(".bib")):
            bib |= latex.bibtex(latex.decode(files[p]))
        doc = blocks.document(text, "markdown", stem, latex.macros(text), bib)
    elif bundle.format is SourceFormat.LATEX:
        doc = latex.parse(files, bundle.entry)
    else:
        retries = bundle.params.max_retries
        doc, usage = pdf.parse(files[bundle.entry], stem, llm, fetch, check, retries, workers)
    store.put(doc, key)
    return doc, usage
