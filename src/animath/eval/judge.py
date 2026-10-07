"""Q7: rubric score of a video by an LLM judge on storyboard, source equations and keyframes."""

import json
from io import BytesIO
from pathlib import Path

import av
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from animath.core.errors import AnimathError
from animath.core.schemas import DocIR, Storyboard, Usage
from animath.eval.formula import equations
from animath.llm import LLM

FRAMES = 8
WIDTH = 768
WINDOW_S = 1.0
SYSTEM = """You grade a short educational mathematics video against its source.
Score each criterion from 1 (poor) to 5 (excellent):
accuracy: every statement and formula agrees with the source;
flow: concepts are introduced before use and the argument is ordered;
relevance: visuals illustrate what the narration says;
layout: frames are legible, uncluttered, nothing overlaps or leaves the frame.
Judge layout from the keyframes, the rest from the storyboard and source equations.
Give one sentence of justification per criterion in notes."""


class Rubric(BaseModel):
    accuracy: int = Field(ge=1, le=5)
    flow: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    layout: int = Field(ge=1, le=5)
    notes: str

    @property
    def score(self) -> float:
        return (self.accuracy + self.flow + self.relevance + self.layout) / 4


def keyframes(video: Path, duration: float, n: int = FRAMES, w: float = WINDOW_S) -> list[bytes]:
    """PNG frames, width WIDTH: for t_j = (j + 1/2) T / n, the frame in [t_j - w, t_j + w] least
    changed from its predecessor, nearest t_j among ties (a still, not a transition)."""
    out = []
    try:
        with av.open(str(video)) as f:
            s = f.streams.video[0]
            for j in range(n):
                t = (j + 0.5) * duration / n
                f.seek(int(max(0.0, t - w - 1.0) / s.time_base), stream=s)
                prev, best, img = None, (np.inf, np.inf), None
                for fr in f.decode(s):
                    if fr.time > t + w:
                        break
                    cur = fr.reformat(width=96, height=54, format="gray").to_ndarray().astype(float)
                    if prev is not None and fr.time >= t - w:
                        key = (float(np.abs(cur - prev).mean()), abs(fr.time - t))
                        if key < best:
                            best, img = key, Image.fromarray(fr.to_ndarray(format="rgb24"))
                    prev = cur
                if img is None:
                    raise AnimathError(f"keyframe {j} of {video}: no frame near t={t:.2f} s")
                buf = BytesIO()
                img.resize((WIDTH, round(WIDTH * img.height / img.width / 2) * 2)).save(buf, "PNG")
                out.append(buf.getvalue())
    except (av.FFmpegError, OSError) as e:
        raise AnimathError(f"keyframes of {video}: {e}") from e
    return out


def prompt(board: Storyboard, doc: DocIR) -> str:
    scenes = [
        {"goal": s.goal, "narration": [ln.text for ln in s.narration], "math": list(s.math)}
        for s in board.scenes
    ]
    eqs = "\n".join(f"({k}) {tex}" for k, tex in equations(doc))
    return (
        f"Source: {doc.title}\nSource equations:\n{eqs}\n"
        f"Storyboard:\n{json.dumps(scenes, ensure_ascii=False)}\nKeyframes in time order above."
    )


def judge(board: Storyboard, doc: DocIR, frames: list[bytes], llm: LLM) -> tuple[Rubric, Usage]:
    return llm.parse(Rubric, SYSTEM, prompt(board, doc), frames)
