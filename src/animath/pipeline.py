"""Orchestration of Phi_1..Phi_7 (SPEC §6.1, HANDBOOK §12)."""

import io
import multiprocessing as mp
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError

from animath import assemble, extract, ingest, narrate, numerics, plan
from animath.core.config import Settings
from animath.core.errors import AnimathError
from animath.core.hashing import digest, digest_of
from animath.core.schemas import (
    Artifact,
    BlockType,
    DataSet,
    DocIR,
    KnowledgeGraph,
    Manifest,
    Narration,
    Params,
    Scene,
    SceneRender,
    SourceBundle,
    SourceFile,
    SourceFormat,
    Storyboard,
    Usage,
)
from animath.core.store import Store
from animath.eval import metrics
from animath.llm import LLM, from_settings, tag
from animath.narrate.tts import TTS, Espeak, Kokoro
from animath.narrate.verbalize import Verbalizer
from animath.scene import animate, catalog, render

VERSION = "1"
STAGES = ("ingest", "extract", "plan", "compute", "narrate", "animate", "assemble")
FORMATS = {".md": SourceFormat.MD, ".tex": SourceFormat.LATEX, ".pdf": SourceFormat.PDF}
LATEX_FILES = {".tex", ".bib", ".bbl", ".sty", ".cls"}
RENDER_PARAMS = {"width", "height", "fps", "style", "seed", "max_retries"}
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.2, 5.0)}
PDF_ID = re.compile(rb"/ID\s*\[<[0-9A-Fa-f]{32}><[0-9A-Fa-f]{32}>\]")
ORDINALS = re.compile(r"\d+(?:\.\d+)*")


class PipelineError(AnimathError): ...


class Animate(Protocol):
    def __call__(
        self,
        scene: Scene,
        data: Mapping[str, DataSet],
        narration: Narration,
        store: Store,
        llm: LLM,
        params: Params,
    ) -> tuple[SceneRender, Usage]: ...


def render_only(
    scene: Scene,
    data: Mapping[str, DataSet],
    narration: Narration,
    store: Store,
    llm: LLM,
    params: Params,
) -> tuple[SceneRender, Usage]:
    """Phi_5 by the primitive library alone: no codegen, repair, or critic."""
    return render(scene, params, store, narration, data), Usage()


@dataclass(frozen=True)
class Paused:
    gate: str
    digest: str


class Metered:
    """LLM wrapper accumulating usage; safe under concurrent callers."""

    def __init__(self, inner: LLM) -> None:
        self.inner, self.usage, self._lock = inner, Usage(), Lock()

    def add(self, u: Usage) -> None:
        with self._lock:
            self.usage += u

    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]:
        out, u = self.inner.parse(schema, system, prompt, images)
        self.add(u)
        return out, u


def cost(u: Usage, model: str) -> float:
    """USD of `u` at the per-MTok prices of `model`."""
    if model not in PRICES:
        raise PipelineError(f"no prices for {model!r}; budget cannot be enforced")
    p = PRICES[model]
    n = (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens)
    return sum(a * b for a, b in zip(p, n, strict=True)) / 1e6


def voice(params: Params, env: Mapping[str, str] = os.environ) -> TTS:
    """Kokoro if ANIMATH_KOKORO names a model directory, else espeak-ng; both at `params.wpm`.

    espeak-ng keeps its default voice for a Kokoro voice name such as `af_heart`.
    """
    v = params.voice
    if root := env.get("ANIMATH_KOKORO"):
        speed = round(params.wpm / Kokoro.wpm_per_speed, 3)
        return (
            Kokoro(Path(root), speed=speed)
            if v == "default"
            else Kokoro(Path(root), v, speed=speed)
        )
    return Espeak(wpm=params.wpm) if v == "default" or "_" in v else Espeak(v, wpm=params.wpm)


def pages(data: bytes, spec: str) -> bytes:
    """PDF of the 1-based pages `spec` (e.g. '3-7,9'), in that order; /ID fixed by content."""
    try:
        src = pdfium.PdfDocument(data)
        n = len(src)
        idx: list[int] = []
        for part in spec.split(","):
            a, _, b = part.strip().partition("-")
            lo, hi = int(a), int(b or a)
            if not 1 <= lo <= hi <= n:
                raise PipelineError(f"pages {part!r} outside 1..{n}")
            idx += range(lo - 1, hi)
        new = pdfium.PdfDocument.new()
        new.import_pages(src, idx)
        buf = io.BytesIO()
        new.save(buf)
    except (ValueError, pdfium.PdfiumError) as e:
        raise PipelineError(f"cannot select pages {spec!r}: {e}") from e
    h = digest(data + str(idx).encode())[:32].upper().encode()
    return PDF_ID.sub(b"/ID[<" + h + b"><" + h + b">]", buf.getvalue())


def section(doc: DocIR, path: str) -> DocIR:
    """Blocks of the section `path`: components split by '/', each a heading title substring
    (case-folded) or dotted 1-based ordinals ('2.3.1'), descending one heading level each."""
    keys: list[int | str] = []
    for c in filter(None, (x.strip() for x in path.split("/"))):
        keys += [int(k) for k in c.split(".")] if ORDINALS.fullmatch(c) else [c.casefold()]
    lo, hi, heads = 0, len(doc.blocks), list[str]()
    for k in keys:
        sub = [i for i in range(lo + bool(heads), hi) if doc.blocks[i].type is BlockType.HEADING]
        top = min((doc.blocks[i].level or 0 for i in sub), default=0)
        sub = [i for i in sub if doc.blocks[i].level == top]
        hit = (
            sub[k - 1 : k]
            if isinstance(k, int) and k >= 1
            else [i for i in sub if isinstance(k, str) and k in doc.blocks[i].text.casefold()][:1]
        )
        if not hit:
            raise PipelineError(f"no section {k!r} in {path!r}")
        nxt = [i for i in sub if i > hit[0]]
        lo, hi = hit[0], nxt[0] if nxt else hi
        heads.append(doc.blocks[lo].text)
    blocks = doc.blocks[lo:hi]
    known = {b.label for b in blocks if b.label} | doc.bib.keys()
    kept = tuple(
        b.model_copy(update={"refs": tuple(r for r in b.refs if r in known)}) for b in blocks
    )
    title = " / ".join([doc.title, *heads])
    return DocIR(title=title, blocks=kept, macros=doc.macros, bib=doc.bib)


def bundle(path: Path, params: Params, store: Store, page_spec: str | None = None) -> SourceBundle:
    """SourceBundle of `path`: a PDF alone (optionally its pages `page_spec`), MD with sibling
    .bib, LaTeX with its directory tree."""
    if (fmt := FORMATS.get(path.suffix.lower())) is None:
        raise PipelineError(f"unsupported source {path}; expected one of {sorted(FORMATS)}")
    if page_spec is not None and fmt is not SourceFormat.PDF:
        raise PipelineError("page selection applies to PDF sources only")
    root = path.parent
    if fmt is SourceFormat.PDF:
        paths = [path]
    elif fmt is SourceFormat.MD:
        paths = [path, *sorted(root.glob("*.bib"))]
    else:
        paths = sorted(
            {
                path,
                *(
                    p
                    for p in root.rglob("*")
                    if p.is_file()
                    and p.suffix in LATEX_FILES
                    and not any(x.startswith(".") for x in p.relative_to(root).parts)
                ),
            }
        )
    try:
        data = {p: p.read_bytes() for p in paths}
    except OSError as e:
        raise PipelineError(f"cannot read source: {e}") from e
    if page_spec is not None:
        data[path] = pages(data[path], page_spec)
    files = tuple(
        SourceFile(path=p.relative_to(root).as_posix(), blob=store.put_blob(d))
        for p, d in data.items()
    )
    b = SourceBundle(format=fmt, entry=path.name, files=files, params=params)
    store.put(b)
    return b


def _child(
    fn: Animate,
    settings: Settings,
    s: Scene,
    data: Mapping[str, DataSet],
    narration: Narration,
    params: Params,
) -> tuple[SceneRender, Usage]:
    store = Store(settings.store)
    return fn(s, data, narration, store, from_settings(settings, store), params)


class Pipeline:
    """Phi_7 o Phi_5 o (Phi_4 || Phi_6) o Phi_3 o Phi_2 o Phi_1; gates after K and B (F12)."""

    def __init__(
        self,
        settings: Settings,
        llm: LLM | None = None,
        tts: Callable[[Params], TTS] = voice,
        verbalizer: Verbalizer | None = None,
        animate: Animate = animate,
        fetch: ingest.Fetch | None = ingest.fetch_url,
        check: ingest.Check | None = ingest.compile_errors,
    ) -> None:
        self.settings, self.store = settings, Store(settings.store)
        self.llm = Metered(llm if llm is not None else from_settings(settings, self.store))
        self.tts, self.verbalizer = tts, verbalizer or Verbalizer()
        self.fn, self.fetch, self.check = animate, fetch, check
        self.timings: dict[str, float] = {}

    @contextmanager
    def _timed(self, stage: str, params: Params | None = None) -> Iterator[None]:
        t0 = time.perf_counter()
        yield
        self.timings[stage] = round(time.perf_counter() - t0, 3)
        if params is not None and params.budget_usd is not None:
            spent = cost(self.llm.usage, self.settings.model)
            if spent > params.budget_usd:
                raise PipelineError(f"budget {params.budget_usd} USD exceeded after {stage}")

    def ingest(self, b: SourceBundle) -> DocIR:
        with self._timed("ingest", b.params):
            w = self.settings.workers
            return ingest.run(b, self.store, self.llm, self.fetch, self.check, w)[0]

    def extract(self, doc: DocIR, params: Params) -> KnowledgeGraph:
        with self._timed("extract", params):
            return extract.run(doc, self.store, self.llm, params.max_retries)[0]

    def plan(self, kg: KnowledgeGraph, params: Params) -> Storyboard:
        kernels = {k: K.model_json_schema() for k, K in numerics.KINDS.items()}
        with self._timed("plan", params):
            out = plan.run(kg, params, catalog(), self.store, self.llm, kernels, self.verbalizer)
            return out[0]

    def compute(self, board: Storyboard) -> dict[str, DataSet]:
        reqs = {r.digest: r for s in board.scenes for r in s.data}
        with self._timed("compute"), ThreadPoolExecutor(self.settings.workers) as ex:
            out = ex.map(lambda r: numerics.compute(r, self.store), reqs.values())
            return dict(zip(reqs, out, strict=True))

    def narrate(self, board: Storyboard, params: Params) -> dict[str, Narration]:
        with self._timed("narrate"):
            tts, w = self.tts(params), self.settings.workers
            ds = narrate.narrate(board, self.store, tts, self.verbalizer, w)
            return {sid: self.store.get(Narration, d) for sid, d in ds.items()}

    def animate(
        self,
        board: Storyboard,
        params: Params,
        data: Mapping[str, DataSet],
        narrations: Mapping[str, Narration],
    ) -> dict[str, SceneRender]:
        """Φ5 over scenes; cached per scene, parallel over processes (render is thread-unsafe)."""
        p = digest_of(params.model_dump(mode="json", include=RENDER_PARAMS))
        fn = f"{self.fn.__module__}.{getattr(self.fn, '__qualname__', '')}"
        jobs = {}
        for s in board.scenes:
            sub = {r.digest: data[r.digest] for r in s.data}
            ds = [digest_of(sub[k]) for k in sorted(sub)]
            d = digest_of(narrations[s.id])
            jobs[s.id] = (Store.key("animate", VERSION, fn, digest_of(s), d, p, *ds), sub)
        out = {sid: r for sid, (k, _) in jobs.items() if (r := self.store.lookup(SceneRender, k))}
        todo = [s for s in board.scenes if s.id not in out]
        with self._timed("animate", params):
            if self.settings.workers == 1 or len(todo) < 2:
                llm = self.llm.inner
                results = [
                    self.fn(s, jobs[s.id][1], narrations[s.id], self.store, llm, params)
                    for s in todo
                ]
            else:
                n = min(self.settings.workers, len(todo))
                with ProcessPoolExecutor(n, mp_context=mp.get_context("spawn")) as ex:
                    futs = [
                        ex.submit(
                            _child,
                            self.fn,
                            self.settings,
                            s,
                            jobs[s.id][1],
                            narrations[s.id],
                            params,
                        )
                        for s in todo
                    ]
                    results = [f.result() for f in futs]
            for s, (r, u) in zip(todo, results, strict=True):
                self.llm.add(u)
                self.store.put(r, jobs[s.id][0])
                out[s.id] = r
        return {s.id: out[s.id] for s in board.scenes}

    def assemble(
        self,
        board: Storyboard,
        renders: Mapping[str, SceneRender],
        narrations: Mapping[str, Narration],
    ) -> Manifest:
        with self._timed("assemble"):
            d = assemble.assemble(
                self.store,
                self.store.put(board),
                [self.store.put(r) for r in renders.values()],
                [self.store.put(n) for n in narrations.values()],
                self.settings.workers,
            )
            return self.store.get(Manifest, d)

    def _gate[A: Artifact](self, art: A, params: Params, edit: list[str | None]) -> A | Paused:
        """Approved `art`; if unapproved, consumes `edit[0]` ('' = as is, else JSON) or pauses."""
        if not params.approval_gates:
            return art
        key = Store.key("gate", art.kind, digest_of(art))
        if (d := self.store.ref("gate", key)) is not None:
            return self.store.get(type(art), d)
        if (text := edit[0]) is None:
            return Paused(art.kind, digest_of(art))
        edit[0] = None
        try:
            new = type(art).model_validate_json(text) if text else art
        except ValidationError as e:
            raise PipelineError(f"edited {art.kind} invalid: {e}") from e
        self.store.set_ref("gate", key, self.store.put(new))
        return new

    def run(
        self, b: SourceBundle, edit: str | None = None, part: str | None = None
    ) -> Manifest | Paused:
        """Algorithm 12.1. `edit` approves the first pending gate ('' as is, else by JSON);
        `part` restricts D to a section path."""
        p, pending = b.params, [edit]
        doc = self.ingest(b)
        if part is not None:
            doc = section(doc, part)
            self.store.put(doc)
        kg = self._gate(self.extract(doc, p), p, pending)
        if isinstance(kg, Paused):
            return kg
        board = self._gate(self.plan(kg, p), p, pending)
        if isinstance(board, Paused):
            return board
        with ThreadPoolExecutor(2) as ex:
            fd = ex.submit(self.compute, board)
            fn = ex.submit(self.narrate, board, p)
            data, narrations = fd.result(), fn.result()
        renders = self.animate(board, p, data, narrations)
        m = self.assemble(board, renders, narrations)
        extra = {"source": digest_of(b), "doc": digest_of(doc), "graph": digest_of(kg)}
        extra |= {f"dataset/{k}": digest_of(v) for k, v in data.items()}
        versions = {
            "pipeline": VERSION,
            "ingest": ingest.VERSION,
            "extract": extract.VERSION,
            "plan": plan.VERSION,
            "numerics": numerics.VERSION,
            "narrate": narrate.VERSION,
            "model": tag(self.settings),
        }
        final = m.model_copy(
            update={
                "artifacts": m.artifacts | extra,
                "versions": m.versions | versions,
                "timings_s": m.timings_s | self.timings,
                "usage": self.llm.usage,
                "metrics": m.metrics | metrics.automatic(doc, kg, board, renders, narrations, m, p),
            }
        )
        self.store.put(final)
        return final
