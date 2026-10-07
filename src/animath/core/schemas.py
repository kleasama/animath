from collections import Counter
from enum import StrEnum
from pathlib import PurePosixPath
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from animath.core.hashing import Digest, digest_of

SCHEMA_VERSION: Literal["0.1"] = "0.1"


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Artifact(Model):
    kind: ClassVar[str]
    schema_version: Literal["0.1"] = SCHEMA_VERSION


def _unique(values: list[str], what: str) -> None:
    dup = sorted(k for k, n in Counter(values).items() if n > 1)
    if dup:
        raise ValueError(f"duplicate {what}: {dup}")


def _within(times: dict[str, float], t_max: float, what: str) -> None:
    bad = sorted(k for k, t in times.items() if not 0.0 <= t <= t_max)
    if bad:
        raise ValueError(f"{what} outside [0, {t_max}]: {bad}")


class SourceFormat(StrEnum):
    MD = "md"
    LATEX = "latex"
    PDF = "pdf"


class Audience(StrEnum):
    UNDERGRADUATE = "undergraduate"
    GRADUATE = "graduate"
    EXPERT = "expert"


class Params(Model):
    duration_s: float = Field(180.0, gt=0, le=1200)
    wpm: int = Field(135, ge=80, le=220, description="speech rate in words per minute, 80 to 220")
    audience: Audience = Audience.GRADUATE
    focus: str | None = None
    language: str = "en"
    voice: str = "default"
    width: int = Field(1920, ge=320, le=3840, multiple_of=2)
    height: int = Field(1080, ge=240, le=2160, multiple_of=2)
    fps: int = Field(60, ge=15, le=120)
    style: str = "default"
    seed: int = 0
    max_retries: int = Field(3, ge=0, le=10)
    budget_usd: float | None = Field(None, gt=0)
    approval_gates: bool = True


class SourceFile(Model):
    path: str
    blob: Digest

    @model_validator(mode="after")
    def _relative(self) -> Self:
        p = PurePosixPath(self.path)
        if p.is_absolute() or ".." in p.parts or not p.parts:
            raise ValueError(f"path must be relative without '..': {self.path!r}")
        return self


class SourceBundle(Artifact):
    kind = "source"
    format: SourceFormat
    entry: str
    files: tuple[SourceFile, ...] = Field(min_length=1)
    params: Params = Params()

    @model_validator(mode="after")
    def _entry(self) -> Self:
        paths = [f.path for f in self.files]
        _unique(paths, "paths")
        if self.entry not in paths:
            raise ValueError(f"entry {self.entry!r} not among files")
        return self


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    EQUATION = "equation"
    THEOREM = "theorem"
    PROOF = "proof"
    ALGORITHM = "algorithm"
    FIGURE = "figure"
    LIST = "list"
    CODE = "code"


class Block(Model):
    id: str
    type: BlockType
    text: str = ""
    latex: str | None = None
    label: str | None = None
    level: int | None = Field(None, ge=1, le=6)
    env: str | None = None
    refs: tuple[str, ...] = ()
    page: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.type is BlockType.EQUATION and not self.latex:
            raise ValueError(f"equation {self.id} lacks latex")
        if (self.type is BlockType.HEADING) != (self.level is not None):
            raise ValueError(f"block {self.id}: level is required for headings only")
        return self


class DocIR(Artifact):
    kind = "doc"
    title: str
    blocks: tuple[Block, ...] = Field(min_length=1)
    macros: dict[str, str] = {}
    bib: dict[str, str] = {}

    @model_validator(mode="after")
    def _refs(self) -> Self:
        _unique([b.id for b in self.blocks], "block ids")
        labels = [b.label for b in self.blocks if b.label]
        _unique(labels, "labels")
        known = set(labels) | self.bib.keys()
        dangling = sorted({r for b in self.blocks for r in b.refs} - known)
        if dangling:
            raise ValueError(f"unresolved refs: {dangling}")
        return self


class NodeKind(StrEnum):
    CONCEPT = "concept"
    SYMBOL = "symbol"
    EQUATION = "equation"
    RESULT = "result"
    ALGORITHM = "algorithm"


class Relation(StrEnum):
    DEPENDS_ON = "depends_on"
    DEFINES = "defines"
    USES = "uses"


class Node(Model):
    id: str
    kind: NodeKind
    name: str
    latex: str | None = None
    meaning: str | None = None
    key: bool = False
    sources: tuple[str, ...] = Field(min_length=1)


class Edge(Model):
    src: str
    dst: str
    rel: Relation


class KnowledgeGraph(Artifact):
    kind = "graph"
    nodes: tuple[Node, ...] = Field(min_length=1)
    edges: tuple[Edge, ...] = ()

    @model_validator(mode="after")
    def _graph(self) -> Self:
        ids = [n.id for n in self.nodes]
        _unique(ids, "node ids")
        known = set(ids)
        loose = sorted({x for e in self.edges for x in (e.src, e.dst)} - known)
        if loose:
            raise ValueError(f"edges reference unknown nodes: {loose}")
        succ: dict[str, list[str]] = {i: [] for i in ids}
        indeg: Counter[str] = Counter()
        for e in self.edges:
            if e.rel is Relation.DEPENDS_ON:
                succ[e.src].append(e.dst)
                indeg[e.dst] += 1
        ready = [i for i in ids if not indeg[i]]
        while ready:
            for nxt in succ[ready.pop()]:
                indeg[nxt] -= 1
                if not indeg[nxt]:
                    ready.append(nxt)
        cyclic = sorted(i for i in ids if indeg[i] > 0)
        if cyclic:
            raise ValueError(f"depends_on cycle among {cyclic}")
        return self


class DataRequest(Model):
    kind: str
    params: dict[str, JsonValue] = {}

    @property
    def digest(self) -> str:
        return digest_of(self)


class Line(Model):
    text: str = Field(min_length=1)
    bookmark: str | None = None
    pause_s: float = Field(
        0.0, ge=0.0, le=30.0, description="silence after the line, 0 to 30 s; ends its utterance"
    )


class Visual(Model):
    primitive: str
    args: dict[str, JsonValue] = {}
    at: str | None = None


class Scene(Model):
    id: str
    goal: str
    narration: tuple[Line, ...] = Field(min_length=1)
    visuals: tuple[Visual, ...] = ()
    math: tuple[str, ...] = ()
    data: tuple[DataRequest, ...] = ()
    nodes: tuple[str, ...] = ()
    duration_s: float = Field(gt=0)

    @model_validator(mode="after")
    def _cues(self) -> Self:
        marks = [ln.bookmark for ln in self.narration if ln.bookmark]
        _unique(marks, f"bookmarks in scene {self.id}")
        missing = sorted({v.at for v in self.visuals if v.at} - set(marks))
        if missing:
            raise ValueError(f"scene {self.id}: visuals cue unknown bookmarks {missing}")
        return self


class Storyboard(Artifact):
    kind = "storyboard"
    title: str
    scenes: tuple[Scene, ...] = Field(min_length=1)
    symbols: dict[str, str] = {}

    @model_validator(mode="after")
    def _ids(self) -> Self:
        _unique([s.id for s in self.scenes], "scene ids")
        return self

    @property
    def duration_s(self) -> float:
        return sum(s.duration_s for s in self.scenes)


class DataSet(Artifact):
    kind = "dataset"
    request: DataRequest
    arrays: dict[str, Digest]
    meta: dict[str, JsonValue] = {}


class Word(Model):
    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.end < self.start:
            raise ValueError(f"word {self.text!r} ends before it starts")
        return self


class Narration(Artifact):
    kind = "narration"
    scene_id: str
    audio: Digest
    duration_s: float = Field(gt=0)
    words: tuple[Word, ...] = ()
    captions: tuple[Word, ...] = ()
    bookmarks: dict[str, float] = {}

    @model_validator(mode="after")
    def _timeline(self) -> Self:
        for name, ws in (("word", self.words), ("caption", self.captions)):
            starts = [w.start for w in ws]
            if starts != sorted(starts):
                raise ValueError(f"{name} starts not monotone")
            if ws and ws[-1].end > self.duration_s:
                raise ValueError(f"{name}s exceed audio duration")
        _within(self.bookmarks, self.duration_s, "bookmarks")
        return self


class SceneRender(Artifact):
    kind = "render"
    scene_id: str
    clip: Digest
    duration_s: float = Field(gt=0)
    bookmarks: dict[str, float] = {}
    checks: dict[str, bool] = {}

    @model_validator(mode="after")
    def _timeline(self) -> Self:
        _within(self.bookmarks, self.duration_s, "bookmarks")
        return self


class Usage(Model):
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cache_read_tokens: int = Field(0, ge=0)
    cache_write_tokens: int = Field(0, ge=0)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(**{k: getattr(self, k) + getattr(other, k) for k in Usage.model_fields})


class Manifest(Artifact):
    kind = "manifest"
    video: Digest
    subtitles: Digest
    artifacts: dict[str, Digest]
    versions: dict[str, str] = {}
    timings_s: dict[str, float] = {}
    usage: Usage = Usage()
    metrics: dict[str, float] = {}


ARTIFACTS: dict[str, type[Artifact]] = {
    a.kind: a
    for a in (
        SourceBundle,
        DocIR,
        KnowledgeGraph,
        Storyboard,
        DataSet,
        Narration,
        SceneRender,
        Manifest,
    )
}
