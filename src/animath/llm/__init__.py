import base64
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import anthropic
from anthropic.types.beta import BetaImageBlockParam, BetaTextBlockParam
from pydantic import BaseModel, ValidationError

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
    """Streamed structured-output client: cached system prompt, PNG vision input, refusal
    fallback. Streaming lifts the SDK's 10-minute bound on non-streaming `max_tokens`."""

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
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_format=schema,
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                r = stream.get_final_message()
        except anthropic.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        except ValidationError as e:
            raise LLMError(f"unparsable {schema.__name__} output: {e.errors()[0]['msg']}") from e
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


class PendingError(LLMError):
    """A session-mode request awaits its answer."""


class Session:
    """LLM answered out of band: a miss writes `<root>/<key>/request.json` (schema, system,
    prompt, image files `<i>.png`) and raises `PendingError`; `<key>/answer.json` is the reply."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def parse[T: BaseModel](
        self, schema: type[T], system: str, prompt: str, images: Sequence[bytes] = ()
    ) -> tuple[T, Usage]:
        js = schema.model_json_schema()
        d = self.root / digest_of([js, system, prompt, [digest(i) for i in images]])
        if (a := d / "answer.json").exists():
            try:
                return schema.model_validate_json(a.read_bytes()), Usage()
            except ValidationError as e:
                raise LLMError(f"invalid answer {a}: {e}") from e
        d.mkdir(parents=True, exist_ok=True)
        for i, img in enumerate(images):
            (d / f"{i}.png").write_bytes(img)
        req = {"schema": js, "system": system, "prompt": prompt}
        req["images"] = [f"{i}.png" for i in range(len(images))]
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(req, f, indent=1, ensure_ascii=False)
        os.replace(tmp, d / "request.json")
        raise PendingError(f"{schema.__name__} request pending in {d}")


def pending(root: Path) -> list[Path]:
    """Unanswered session requests under `root`."""
    return sorted(
        p.parent for p in root.glob("*/request.json") if not p.with_name("answer.json").exists()
    )


KEY_VARS = ("ANIMATH_API_KEY", "ANTHROPIC_API_KEY")


def api_key() -> str:
    key = next((k for v in KEY_VARS if (k := os.environ.get(v))), None)
    if key is None:
        raise LLMError(f"no API key: set {' or '.join(KEY_VARS)}, or offline=true")
    return key


def tag(s: Settings) -> str:
    """Provenance of LLM responses: the answering source and, for the API, model and effort."""
    return "session" if s.llm == "session" else f"{s.model}:{s.effort}"


def from_settings(s: Settings, store: Store) -> LLM:
    if s.offline:
        return Replay(store, None, tag(s))
    if s.llm == "session":
        return Replay(store, Session(s.store / "pending"), tag(s))
    client = anthropic.Anthropic(api_key=api_key())
    return Replay(store, Claude(s.model, s.effort, s.max_tokens, client), tag(s))
