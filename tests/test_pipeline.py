import json
import subprocess
import tempfile
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from animath import pipeline
from animath.cli import main
from animath.core.config import Settings
from animath.core.hashing import digest_of
from animath.core.schemas import (
    Block,
    BlockType,
    DataSet,
    DocIR,
    Manifest,
    Narration,
    Params,
    Scene,
    SceneRender,
    SourceFormat,
    Storyboard,
    Usage,
)
from animath.core.store import Store
from animath.extract.draft import Draft as XDraft
from animath.llm import LLM, Replay
from animath.narrate.tts import Espeak
from animath.pipeline import Paused, Pipeline, PipelineError
from animath.plan.draft import DData, DLine, Draft, DScene, DVisual
from tests.plan.conftest import Fake

GOLDEN = Path(__file__).parent / "golden"
EQ = {
    b.id: b.latex
    for b in DocIR.model_validate_json((GOLDEN / "efie/expected.json").read_text()).blocks
}
GMRES = ["main.tex", "refs.bib", "sec/arnoldi.tex"]
P = Params(duration_s=12, width=320, height=240, fps=15, approval_gates=False)


def words(n: int, tag: str) -> str:
    return " ".join([tag] * n)


def plan_draft() -> Draft:
    """Valid storyboard for the efie golden graph at T = 12 s: 15 + 15 words."""
    eq = json.dumps({"latex": EQ["b2"]})
    return Draft(
        title="EFIE",
        scenes=[
            DScene(
                id="s1",
                goal="state the EFIE",
                narration=[DLine(text=words(8, "field"), bookmark="a"), DLine(text=words(7, "on"))],
                visuals=[DVisual(primitive="equation", args=eq, at="a")],
                nodes=["efie", "uniqueness"],
            ),
            DScene(
                id="s2",
                goal="discretize",
                narration=[DLine(text=words(15, "moment"))],
                visuals=[DVisual(primitive="text", args='{"text": "Galerkin"}')],
                math=[EQ["b2"]],
                data=[DData(kind="quadrature.rule", params='{"n": 3}')],
                nodes=["mom"],
            ),
        ],
    )


def fake_llm() -> Fake:
    x = XDraft.model_validate_json((Path(__file__).parent / "extract/golden/efie.json").read_text())
    return Fake(x, plan_draft())


def clip(
    scene: Scene,
    data: Mapping[str, DataSet],
    narration: Narration,
    store: Store,
    llm: LLM,
    params: Params,
) -> tuple[SceneRender, Usage]:
    """Animate stand-in with the WP8 signature: a black clip of the narration's length."""
    size, d = f"{params.width}x{params.height}", narration.duration_s
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "c.mp4"
        src = f"color=c=black:s={size}:r={params.fps}:d={d}"
        cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", src, "-c:v", "libx264", str(out)]
        subprocess.run(cmd, check=True)
        blob = store.put_blob(out.read_bytes())
    r = SceneRender(
        scene_id=scene.id,
        clip=blob,
        duration_s=d,
        bookmarks=narration.bookmarks,
        checks={"layout": True, "render": True},
    )
    return r, Usage(output_tokens=3)


def settings(tmp_path: Path, workers: int = 1) -> Settings:
    return Settings(store=tmp_path / "store", workers=workers, offline=True)


def make(
    tmp_path: Path, llm: LLM | None = None, workers: int = 1, fn: pipeline.Animate = clip
) -> Pipeline:
    s = settings(tmp_path, workers)
    return Pipeline(s, llm or fake_llm(), lambda p: Espeak(), animate=fn, fetch=None, check=None)


def test_run_end_to_end(tmp_path: Path) -> None:
    pipe = make(tmp_path)
    b = pipeline.bundle(GOLDEN / "efie/efie.md", P, pipe.store)
    assert [f.path for f in b.files] == ["efie.md", "refs.bib"]
    m = pipe.run(b)
    assert isinstance(m, Manifest)
    a = m.artifacts
    assert {"source", "doc", "graph", "storyboard", "render/s1", "narration/s2"} <= a.keys()
    assert any(k.startswith("dataset/") for k in a)
    assert m.usage == Usage(input_tokens=14, output_tokens=6)
    assert set(pipeline.STAGES) <= m.timings_s.keys()
    assert m.metrics["q1_render"] == 1.0
    assert m.metrics["q3_sync_ms"] == 0.0
    assert m.metrics["q5_coverage"] == 1.0
    assert m.metrics["n1_traced"] == 1.0
    assert m.metrics["q6_duration"] == pytest.approx(abs(m.metrics["duration_s"] - 12) / 12)
    assert pipe.store.get(Manifest, digest_of(m)) == m
    again = make(tmp_path, Fake()).run(b)
    assert isinstance(again, Manifest)
    assert again.video == m.video
    assert again.usage == Usage()


def test_gates_pause_resume_edit(tmp_path: Path) -> None:
    pipe = make(tmp_path)
    b = pipeline.bundle(
        GOLDEN / "efie/efie.md", P.model_copy(update={"approval_gates": True}), pipe.store
    )
    first = pipe.run(b)
    assert isinstance(first, Paused)
    assert first.gate == "graph"
    assert pipe.run(b) == first
    second = pipe.run(b, "")
    assert isinstance(second, Paused)
    assert second.gate == "storyboard"
    board = pipe.store.get(Storyboard, second.digest)
    edited = board.model_copy(update={"title": "Edited"})
    with pytest.raises(PipelineError, match="edited storyboard invalid"):
        pipe.run(b, "{}")
    m = pipe.run(b, edited.model_dump_json())
    assert isinstance(m, Manifest)
    assert pipe.store.get(Storyboard, m.artifacts["storyboard"]).title == "Edited"


def test_parallel_render(tmp_path: Path) -> None:
    """Real Manim render over a spawn pool of two workers; identical to an in-process render."""
    pipe = make(tmp_path, workers=2, fn=pipeline.render_only)
    m = pipe.run(pipeline.bundle(GOLDEN / "efie/efie.md", P, pipe.store))
    assert isinstance(m, Manifest)
    renders = [pipe.store.get(SceneRender, m.artifacts[f"render/s{i}"]) for i in (1, 2)]
    assert all(r.checks == {"layout": True, "render": True} for r in renders)
    assert m.metrics["q3_sync_ms"] <= 1000 / (2 * P.fps)
    board = pipe.store.get(Storyboard, m.artifacts["storyboard"])
    n = pipe.store.get(Narration, m.artifacts["narration/s1"])
    again = pipeline._child(pipeline.render_only, pipe.settings, board.scenes[0], {}, n, P)
    assert again == (renders[0], Usage())


def test_run_section(tmp_path: Path) -> None:
    llm = Fake()
    pipe = make(tmp_path, llm)
    b = pipeline.bundle(GOLDEN / "efie/efie.md", P, pipe.store)
    with pytest.raises(PipelineError, match="no section"):
        pipe.run(b, part="9")
    with pytest.raises(IndexError):
        pipe.run(b, part="galerkin")
    assert "[b6 equation" in llm.prompts[0]
    assert "[b2 " not in llm.prompts[0]


def test_section() -> None:
    def h(i: str, lv: int, t: str) -> Block:
        return Block(id=i, type=BlockType.HEADING, level=lv, text=t)

    p = Block(id="p", type=BlockType.PARAGRAPH, text="see", refs=("eq", "k"))
    e = Block(id="e", type=BlockType.EQUATION, latex="x", label="eq")
    doc = DocIR(
        title="T",
        blocks=(
            h("a", 1, "Intro"),
            p,
            h("b", 1, "Krylov"),
            h("c", 2, "Arnoldi"),
            e,
            h("d", 2, "GMRES"),
            p.model_copy(update={"id": "q"}),
            h("f", 1, "End"),
        ),
        bib={"k": "ref"},
    )
    assert [x.id for x in pipeline.section(doc, "2.2").blocks] == ["d", "q"]
    s = pipeline.section(doc, "krylov/arnoldi")
    assert s.title == "T / Krylov / Arnoldi"
    assert [x.id for x in s.blocks] == ["c", "e"]
    assert pipeline.section(doc, "Krylov/gmres").blocks[1].refs == ("k",)
    assert [x.id for x in pipeline.section(doc, "1").blocks] == ["a", "p"]
    for bad in ("4", "2.3", "nothing", "0"):
        with pytest.raises(PipelineError, match="no section"):
            pipeline.section(doc, bad)


def test_pages_and_bundle(tmp_path: Path) -> None:
    store = Store(tmp_path)
    pdf = GOLDEN / "gauss/gauss.pdf"
    one = pipeline.pages(pdf.read_bytes(), "1")
    assert one == pipeline.pages(pdf.read_bytes(), "1-1")
    assert one.startswith(b"%PDF")
    for bad in ("2", "0-1", "x"):
        with pytest.raises(PipelineError, match="pages"):
            pipeline.pages(pdf.read_bytes(), bad)
    b = pipeline.bundle(pdf, P, store, "1")
    assert b.format is SourceFormat.PDF
    assert store.get_blob(b.files[0].blob) == one
    tex = pipeline.bundle(GOLDEN / "gmres/main.tex", P, store)
    assert [f.path for f in tex.files] == GMRES
    with pytest.raises(PipelineError, match="PDF sources only"):
        pipeline.bundle(GOLDEN / "efie/efie.md", P, store, "1")
    with pytest.raises(PipelineError, match="unsupported"):
        pipeline.bundle(tmp_path / "x.docx", P, store)
    for missing in ("missing.pdf", "missing.tex"):
        with pytest.raises(PipelineError, match="cannot read"):
            pipeline.bundle(tmp_path / missing, P, store)


def test_budget_and_cost(tmp_path: Path) -> None:
    u = Usage(
        input_tokens=10**6, output_tokens=10**6, cache_read_tokens=10**6, cache_write_tokens=10**6
    )
    assert pipeline.cost(u, "claude-opus-5-5") == pytest.approx(29.2)
    with pytest.raises(PipelineError, match="no prices"):
        pipeline.cost(u, "other")
    pipe = make(tmp_path)
    p = P.model_copy(update={"budget_usd": 1e-9})
    with pytest.raises(PipelineError, match=r"budget .* exceeded after extract"):
        pipe.run(pipeline.bundle(GOLDEN / "efie/efie.md", p, pipe.store))


def test_voice(tmp_path: Path) -> None:
    assert isinstance(pipeline.voice(P, {}), Espeak)
    assert pipeline.voice(P.model_copy(update={"voice": "en-gb"}), {}).id.startswith(
        "espeak-ng:en-gb"
    )
    with pytest.raises(Exception, match="Kokoro"):
        pipeline.voice(P, {"ANIMATH_KOKORO": str(tmp_path)})


def test_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """run pauses and resumes offline from the replay cache; stage reruns every stage."""
    s = settings(tmp_path)
    store = Store(s.store)
    pipe = Pipeline(
        s,
        Replay(store, fake_llm(), f"{s.model}:{s.effort}"),
        lambda p: Espeak(),
        animate=clip,
        fetch=None,
        check=None,
    )
    b = pipeline.bundle(GOLDEN / "efie/efie.md", P, store)
    m = pipe.run(b)
    assert isinstance(m, Manifest)
    monkeypatch.setenv("ANIMATH_STORE", str(s.store))
    monkeypatch.setenv("ANIMATH_OFFLINE", "1")
    monkeypatch.setenv("ANIMATH_WORKERS", "1")
    monkeypatch.delenv("ANIMATH_KOKORO", raising=False)
    monkeypatch.setattr(
        pipeline, "Pipeline", partial(Pipeline, animate=clip, fetch=None, check=None)
    )

    def cli(*argv: str) -> Any:
        assert main(list(argv)) == 0
        return json.loads(capsys.readouterr().out)

    src = str(GOLDEN / "efie/efie.md")
    ps = ["-p", "duration_s=12", "-p", "width=320", "-p", "height=240", "-p", "fps=15"]
    out = cli("run", src, *ps)
    assert out == {"source": out["source"], "paused": "graph", "digest": m.artifacts["graph"]}
    assert cli("run", src, *ps, "--approve")["paused"] == "storyboard"
    edit = tmp_path / "b.json"
    edit.write_text(store.get(Storyboard, m.artifacts["storyboard"]).model_dump_json())
    done = cli("run", src, *ps, "--edit", str(edit))
    assert Path(done["video"]).is_file()
    a = m.artifacts
    assert cli("stage", "ingest", a["source"]) == a["doc"]
    assert cli("stage", "extract", a["doc"]) == a["graph"]
    assert cli("stage", "plan", a["graph"], *ps[:2]) == a["storyboard"]
    board = a["storyboard"]
    assert list(cli("stage", "compute", board).values()) == [
        v for k, v in a.items() if k.startswith("dataset/")
    ]
    assert cli("stage", "narrate", board, *ps) == {"s1": a["narration/s1"], "s2": a["narration/s2"]}
    assert cli("stage", "animate", board, *ps) == {"s1": a["render/s1"], "s2": a["render/s2"]}
    assembled = cli("stage", "assemble", board, *ps)
    assert Store(s.store).get(Manifest, assembled).video == m.video
    ev = cli("eval", digest_of(m), "--expected", str(GOLDEN / "efie/expected.json"))
    assert ev["metrics"]["q2_fidelity"] == 1.0
    assert main(["run", src, "-p", "duration_s"]) == 1
    assert "invalid parameters" in capsys.readouterr().err
    assert main(["eval", digest_of(m), "--expected", str(tmp_path / "none.json")]) == 1
    assert "cannot read" in capsys.readouterr().err


def test_cli_session_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANIMATH_STORE", str(tmp_path))
    monkeypatch.setenv("ANIMATH_LLM", "session")
    assert main(["run", str(GOLDEN / "efie/efie.md")]) == 0
    (d,) = json.loads(capsys.readouterr().out)["pending"]
    assert json.loads((Path(d) / "request.json").read_text())["schema"]["title"] == "Draft"
