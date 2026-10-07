import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from animath.core.schemas import Line, Narration, Scene, SceneRender, Storyboard, Word
from animath.core.store import Store

Media = Callable[..., str]


@pytest.fixture
def media(tmp_path: Path, store: Store) -> Media:
    """Blob of a clip ('v': testsrc2) or narration ('a': sine, 'silent', 'peaky': + impulses)."""

    def make(kind: str, dur: float, size: str = "64x36", fps: int = 15) -> str:
        out = tmp_path / f"m{len(list(tmp_path.iterdir()))}.{'mp4' if kind == 'v' else 'wav'}"
        src = {
            "v": f"testsrc2=size={size}:rate={fps}:duration={dur}",
            "a": f"sine=frequency=440:sample_rate=24000:duration={dur}",
            "silent": f"anullsrc=r=24000:cl=mono:d={dur}",
            "peaky": f"aevalsrc=0.1*sin(2*PI*440*t)+0.8*eq(mod(n\\,12000)\\,6000):s=24000:d={dur}",
        }[kind]
        codec = ["-c:v", "libx264", "-pix_fmt", "yuv420p"] if kind == "v" else []
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", src, *codec, str(out)], check=True
        )
        return store.put_blob(out.read_bytes())

    return make


@pytest.fixture
def two(store: Store, media: Media) -> tuple[str, list[str], list[str]]:
    """Scene s1: clip 1.0 s, speech 0.8 s. Scene s2: clip 0.5 s, speech 0.9 s (clip padded)."""
    board = store.put(
        Storyboard(
            title="t",
            scenes=(
                Scene(id="s1", goal="g", narration=(Line(text="One."),), duration_s=1.0),
                Scene(id="s2", goal="g", narration=(Line(text="Two."),), duration_s=0.9),
            ),
        )
    )
    renders = [
        store.put(SceneRender(scene_id="s1", clip=media("v", 1.0), duration_s=1.0)),
        store.put(SceneRender(scene_id="s2", clip=media("v", 0.5), duration_s=0.5)),
    ]
    narrations = [
        store.put(
            Narration(
                scene_id="s1",
                audio=media("a", 0.8),
                duration_s=0.8,
                words=(Word(text="One.", start=0.1, end=0.6),),
            )
        ),
        store.put(
            Narration(
                scene_id="s2",
                audio=media("a", 0.9),
                duration_s=0.9,
                words=(Word(text="Two", start=0.0, end=0.4), Word(text="x<y.", start=0.4, end=0.8)),
            )
        ),
    ]
    return board, renders, narrations
