import base64
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from animath.core.config import Settings
from animath.core.errors import LLMError
from animath.core.schemas import Usage
from animath.core.store import Store
from animath.llm import FALLBACK_BETA, Claude, Replay, from_settings


class Answer(BaseModel):
    value: int


class FakeMessages:
    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.reply, self.error = reply, error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kw: Any) -> Any:
        self.calls.append(kw)
        if self.error:
            raise self.error
        return self.reply


def fake_client(messages: FakeMessages) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=messages))


SEVEN = Answer(value=7)


def reply(stop: str = "end_turn", out: Answer | None = SEVEN) -> Any:
    u = SimpleNamespace(
        input_tokens=10,
        output_tokens=4,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=6,
    )
    return SimpleNamespace(stop_reason=stop, parsed_output=out, usage=u)


def test_claude_request_shape_and_usage() -> None:
    m = FakeMessages(reply())
    out, usage = Claude("claude-opus-5-5", "high", 2048, fake_client(m)).parse(
        Answer, "sys", "q", [b"\x89PNG"]
    )
    assert out == Answer(value=7)
    assert usage == Usage(input_tokens=10, output_tokens=4, cache_write_tokens=6)
    kw = m.calls[0]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    img, txt = kw["messages"][0]["content"]
    assert base64.b64decode(img["source"]["data"]) == b"\x89PNG"
    assert txt == {"type": "text", "text": "q"}
    assert (kw["output_format"], kw["output_config"]) == (Answer, {"effort": "high"})
    assert (kw["betas"], kw["fallbacks"], kw["max_tokens"]) == ([FALLBACK_BETA], "default", 2048)


@pytest.mark.parametrize("r", [reply("refusal"), reply("max_tokens"), reply(out=None)])
def test_claude_rejects_incomplete_output(r: Any) -> None:
    with pytest.raises(LLMError, match="no parsed output"):
        Claude("m", "low", 1024, fake_client(FakeMessages(r))).parse(Answer, "s", "p")


def test_claude_wraps_api_errors() -> None:
    err = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x"))
    with pytest.raises(LLMError, match="APIConnectionError"):
        Claude("m", "low", 1024, fake_client(FakeMessages(error=err))).parse(Answer, "s", "p")


def test_replay_caches_by_full_request(store: Store) -> None:
    m = FakeMessages(reply())
    llm = Replay(store, Claude("m", "low", 1024, fake_client(m)), "m:low")
    assert llm.parse(Answer, "s", "p")[1].input_tokens == 10
    assert llm.parse(Answer, "s", "p") == (Answer(value=7), Usage())
    assert len(m.calls) == 1
    llm.parse(Answer, "s", "p", [b"img"])
    Replay(store, Claude("m", "low", 1024, fake_client(m)), "m:high").parse(Answer, "s", "p")
    assert len(m.calls) == 3
    offline = Replay(store, None, "m:low")
    assert offline.parse(Answer, "s", "p")[0] == Answer(value=7)
    with pytest.raises(LLMError, match="offline"):
        offline.parse(Answer, "s", "other")


def test_from_settings(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    off = from_settings(Settings(offline=True), store)
    assert isinstance(off, Replay)
    assert off.inner is None
    assert off.tag == "claude-opus-5-5:high"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    on = from_settings(Settings(effort="max"), store)
    assert isinstance(on, Replay)
    assert isinstance(on.inner, Claude)
    assert on.inner.effort == "max"
