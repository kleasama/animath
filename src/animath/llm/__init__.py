import base64
from collections.abc import Sequence
from typing import Any, Protocol

import anthropic
from anthropic.types.beta import BetaImageBlockParam, BetaTextBlockParam
from pydantic import BaseModel

from animath.core.config import Effort, Settings
from animath.core.errors import LLMError
from animath.core.hashing import digest, digest_of
from animath.core.schemas import Usage
from animath.core.store import Store

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM(Protocol):
    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]: ...


class Claude:
    """Structured-output client: cached system prompt, PNG vision input, refusal fallback."""

    def __init__(
        self, model: str, effort: Effort, max_tokens: int, client: Any | None = None
    ) -> None:
        self.model, self.effort, self.max_tokens = model, effort, max_tokens
        self.client = client if client is not None else anthropic.Anthropic()

    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]:
        content: list[BetaImageBlockParam | BetaTextBlockParam] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(img).decode(),
                },
            }
            for img in images
        ]
        content.append({"type": "text", "text": prompt})
        try:
            r = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_format=schema,
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        if r.stop_reason != "end_turn" or r.parsed_output is None:
            raise LLMError(f"no parsed output (stop_reason={r.stop_reason})")
        u = r.usage
        return r.parsed_output, Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        )


class Replay:
    """Content-addressed response cache over an LLM; offline when `inner` is None."""

    def __init__(self, store: Store, inner: LLM | None, tag: str) -> None:
        self.store, self.inner, self.tag = store, inner, tag

    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]:
        key = digest_of(
            [self.tag, schema.model_json_schema(), system, prompt, [digest(i) for i in images]]
        )
        if (d := self.store.ref("llm", key)) is not None:
            return schema.model_validate_json(self.store.get_blob(d)), Usage()
        if self.inner is None:
            raise LLMError(f"offline and no cached response for {schema.__name__}")
        out, usage = self.inner.parse(schema, system, prompt, images)
        self.store.set_ref("llm", key, self.store.put_blob(out.model_dump_json().encode()))
        return out, usage


def from_settings(s: Settings, store: Store) -> LLM:
    tag = f"{s.model}:{s.effort}"
    return Replay(store, None if s.offline else Claude(s.model, s.effort, s.max_tokens), tag)
