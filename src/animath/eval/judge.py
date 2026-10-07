"""Q7: rubric score of a video by an LLM judge on storyboard, source equations and keyframes."""

import json
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from animath.core.errors import AnimathError
from animath.core.schemas import DocIR, Storyboard, Usage
from animath.eval.formula import equations
from animath.llm import LLM

FRAMES = 8
WIDTH = 768
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


def keyframes(video: Path, duration: float, n: int = FRAMES) -> list[bytes]:
    """PNG frames at t_j = (j + 1/2) T / n, width WIDTH."""
    out = []
    for j in range(n):
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{(j + 0.5) * duration / n:.3f}", "-i", str(video)]
        cmd += [
            "-frames:v",
            "1",
            "-vf",
            f"scale={WIDTH}:-2",
            "-f",
            "image2pipe",
            "-c:v",
            "png",
            "-",
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, check=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise AnimathError(f"keyframe {j} of {video}: {e}") from e
        out.append(r.stdout)
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
