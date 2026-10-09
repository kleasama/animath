from io import BytesIO
from pathlib import Path

import av
import numpy as np
import pytest
from PIL import Image

from animath import eval as ev
from animath.core.errors import AnimathError
from animath.core.hashing import digest_of
from animath.core.schemas import (
    DocIR,
    KnowledgeGraph,
    Manifest,
    Narration,
    Params,
    SceneRender,
    Storyboard,
)
from animath.eval import judge, metrics
from animath.pipeline import bundle
from tests.fake import Fake
from tests.test_pipeline import GOLDEN, P, make

H = "0" * 64


def render(sid: str, marks: dict[str, float], **checks: bool) -> SceneRender:
    return SceneRender(scene_id=sid, clip=H, duration_s=5, bookmarks=marks, checks=checks)


def narration(sid: str, marks: dict[str, float]) -> Narration:
    return Narration(scene_id=sid, audio=H, duration_s=5, bookmarks=marks)


def test_scene_metrics() -> None:
    rs = {
        "a": render("a", {"x": 1.0, "y": 2.0}, render=True, layout=True),
        "b": render("b", {"z": 3.0}, render=False, layout=False, critic=False),
    }
    ns = {"a": narration("a", {"x": 1.03, "y": 2.0}), "b": narration("b", {})}
    assert metrics.q1(rs) == 0.5
    assert metrics.q3(rs, ns) == pytest.approx(30.0)
    assert metrics.q3({"b": rs["b"]}, ns) == 0.0
    assert metrics.q4(rs) == 1.0


def test_coverage_duration(graph: KnowledgeGraph, board: Storyboard) -> None:
    assert metrics.q5(graph, board) == 0.0
    s = board.scenes[0].model_copy(update={"nodes": ("mom",)})
    assert metrics.q5(graph, board.model_copy(update={"scenes": (s,)})) == 1.0
    plain = graph.model_copy(
        update={"nodes": tuple(n.model_copy(update={"key": False}) for n in graph.nodes)}
    )
    assert metrics.q5(plain, board) == 1.0
    m = Manifest(video=H, subtitles=H, artifacts={}, metrics={"duration_s": 99.0})
    assert metrics.q6(m, Params(duration_s=90)) == pytest.approx(0.1)
    doc = DocIR.model_validate_json((GOLDEN / "efie/expected.json").read_text())
    assert metrics.n1(board, doc) == 1.0
    wrong = board.scenes[0].model_copy(update={"math": ("ZI=W",)})
    assert metrics.n1(board.model_copy(update={"scenes": (wrong,)}), doc) == 0.5
    assert metrics.n1(board.model_copy(update={"scenes": board.scenes[1:]}), doc) == 1.0


def test_failures() -> None:
    ok = {
        "q1_render": 0.95,
        "q3_sync_ms": 150.0,
        "q4_layout": 0.0,
        "q7_pedagogy": 4.0,
        "duration_s": 7.0,
    }
    assert metrics.failures(ok) == []
    assert metrics.failures({"q1_render": 0.9, "q3_sync_ms": 151.0, "n1_traced": 1.0}) == [
        "q1_render",
        "q3_sync_ms",
    ]


AUTO = {"q1_render", "q3_sync_ms", "q4_layout", "q5_coverage", "q6_duration", "n1_traced"}


def test_evaluate_judge_keyframes(tmp_path: Path) -> None:
    pipe = make(tmp_path)
    m = pipe.run(bundle(GOLDEN / "efie/efie.md", P, pipe.store))
    assert isinstance(m, Manifest)
    auto = {k: m.metrics[k] for k in AUTO}
    assert ev.evaluate(pipe.store, digest_of(m)) == auto
    expected = DocIR.model_validate_json((GOLDEN / "efie/expected.json").read_text())
    llm = Fake(judge.Rubric(accuracy=5, flow=4, relevance=4, layout=3, notes="ok"))
    out = ev.evaluate(pipe.store, digest_of(m), expected, llm)
    assert out == auto | {"q2_fidelity": 1.0, "q7_pedagogy": 4.0}
    assert "(eq:efie) " + str(expected.blocks[2].latex) in llm.prompts[0]
    frames = judge.keyframes(pipe.store.blob_path(m.video), m.metrics["duration_s"], 3)
    assert len(frames) == 3
    assert all(f.startswith(b"\x89PNG") for f in frames)
    with pytest.raises(AnimathError, match="keyframes of"):
        judge.keyframes(tmp_path / "none.mp4", 1.0, 1)
    with pytest.raises(AnimathError, match=r"keyframe 0 .* no frame near t=500\.00"):
        judge.keyframes(pipe.store.blob_path(m.video), 1000.0, 1, 0.1)


def test_judge_keyframes_are_stills(tmp_path: Path) -> None:
    levels = [5 * k for k in range(25)] + [200] * 10 + [5 * k for k in range(5)]
    path = tmp_path / "v.mp4"
    with av.open(str(path), "w") as f:
        s = f.add_stream("libx264", rate=10, options={"crf": "0"})
        s.width, s.height, s.pix_fmt = 64, 64, "yuv420p"
        for v in levels:
            img = np.full((64, 64, 3), v, dtype=np.uint8)
            f.mux(s.encode(av.VideoFrame.from_ndarray(img, format="rgb24")))
        f.mux(s.encode())
    (png,) = judge.keyframes(path, 4.0, 1)
    key = Image.open(BytesIO(png))
    assert key.size == (judge.WIDTH, judge.WIDTH)
    assert abs(float(np.asarray(key.convert("L")).mean()) - 200) < 3
