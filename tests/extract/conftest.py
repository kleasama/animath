from collections.abc import Sequence

from pydantic import BaseModel

from animath.core.schemas import Usage


class Fake:
    """LLM returning queued outputs in order and recording prompts."""

    def __init__(self, *outs: BaseModel) -> None:
        self.outs = list(outs)
        self.prompts: list[str] = []

    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]:
        self.prompts.append(prompt)
        return schema.model_validate(self.outs.pop(0).model_dump()), Usage(input_tokens=7)
