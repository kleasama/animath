from collections.abc import Sequence

from pydantic import BaseModel

from animath.core.schemas import Usage


class Fake:
    """LLM returning queued outputs in order at one input token per call; records each call as
    (schema name, prompt, images)."""

    def __init__(self, *outs: BaseModel) -> None:
        self.outs = list(outs)
        self.calls: list[tuple[str, str, Sequence[bytes]]] = []

    @property
    def prompts(self) -> list[str]:
        return [p for _, p, _ in self.calls]

    def parse[M: BaseModel](
        self, schema: type[M], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[M, Usage]:
        self.calls.append((schema.__name__, prompt, images))
        return schema.model_validate(self.outs.pop(0).model_dump()), Usage(input_tokens=1)
