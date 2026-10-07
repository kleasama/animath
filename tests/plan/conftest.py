import json
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import BaseModel, JsonValue

from animath.core.schemas import Usage
from animath.numerics import KINDS
from animath.plan.draft import DData, DLine, Draft, DScene, DSymbol, DVisual
from animath.scene import catalog

T = 20.0


class Fake:
    """LLM returning queued drafts in order, recording prompts."""

    def __init__(self, *outs: BaseModel) -> None:
        self.outs = list(outs)
        self.prompts: list[str] = []

    def parse[M: BaseModel](
        self, schema: type[M], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[M, Usage]:
        self.prompts.append(prompt)
        return schema.model_validate(self.outs.pop(0).model_dump()), Usage(input_tokens=7)


def line(n: int, bookmark: str | None = None) -> DLine:
    return DLine(text=" ".join(["word"] * n), bookmark=bookmark)


def vis(primitive: str, at: str | None = None, **args: Any) -> DVisual:
    return DVisual(primitive=primitive, args=json.dumps(args), at=at)


def make_draft() -> Draft:
    """Valid for the root `graph` fixture at T = 20 s: 30 + 20 words."""
    ref = {"data": 0, "array": "current"}
    return Draft(
        title="MoM",
        scenes=[
            DScene(
                id="s1",
                goal="state the EFIE",
                narration=[line(10, "a"), line(10, "b"), line(10)],
                visuals=[
                    vis("equation", "a", latex=r"\mathbf{Z}\mathbf{I}=\mathbf{V}", until="b"),
                    vis("plot", "b", series=[{"x": [0, 1], "y": {**ref, "part": "abs"}}]),
                    vis("text", None, text="EFIE", region="title"),
                ],
                data=[DData(kind="mom.efie_cylinder", params='{"ka": 1, "n": 20}')],
                nodes=["efie"],
            ),
            DScene(
                id="s2",
                goal="solve",
                narration=[line(20)],
                visuals=[
                    vis("matrix", entries=ref, region="left"),
                    vis("text", text="solve", region="right"),
                ],
                data=[DData(kind="mom.efie_cylinder", params='{"ka": 1, "n": 20}')],
                nodes=["mom"],
            ),
        ],
        symbols=[DSymbol(latex="Z", meaning="impedance matrix")],
    )


@pytest.fixture
def draft() -> Draft:
    return make_draft()


@pytest.fixture(scope="session")
def cat() -> dict[str, dict[str, JsonValue]]:
    return dict(catalog())


@pytest.fixture(scope="session")
def kernels() -> dict[str, dict[str, JsonValue]]:
    return {k: v.model_json_schema() for k, v in KINDS.items()}
