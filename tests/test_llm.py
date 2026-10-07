import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
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
from animath.llm import (
    FALLBACK_BETA,
    KEY_VARS,
    Claude,
    PendingError,
    Replay,
    Session,
    api_key,
    from_settings,
    pending,
    tag,
)


class Answer(BaseModel):
    value: int


class FakeMessages:
    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.reply, self.error = reply, error
        self.calls: list[dict[str, Any]] = []

    @contextmanager
    def stream(self, **kw: Any) -> Iterator[Any]:
        self.calls.append(kw)
        if self.error:
            raise self.error
        yield SimpleNamespace(get_final_message=lambda: self.reply)


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


def sse_reply(text: str, stop: str) -> bytes:
    usage = {"input_tokens": 10, "output_tokens": 1, "cache_read_input_tokens": 3}
    msg: dict[str, Any] = {"id": "m", "type": "message", "role": "assistant", "content": []}
    msg |= {"model": "m", "stop_reason": None, "stop_sequence": None}
    msg["usage"] = usage | {"cache_creation_input_tokens": 6}
    events: list[dict[str, Any]] = [
        {"type": "message_start", "message": msg},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"},
    ]
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def sdk_client(body: bytes, seen: list[httpx2.Request]) -> anthropic.Anthropic:
    def handle(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    transport = httpx2.MockTransport(handle)
    return anthropic.Anthropic(
        api_key="k", http_client=anthropic.DefaultHttpxClient(transport=transport)
    )


def test_claude_streams_default_max_tokens_through_sdk() -> None:
    seen: list[httpx2.Request] = []
    s = Settings()
    llm = Claude(
        s.model, s.effort, s.max_tokens, sdk_client(sse_reply('{"value": 7}', "end_turn"), seen)
    )
    out, usage = llm.parse(Answer, "sys", "q")
    assert (out, usage) == (
        SEVEN,
        Usage(input_tokens=10, output_tokens=4, cache_read_tokens=3, cache_write_tokens=6),
    )
    body = json.loads(seen[0].content)
    assert (body["stream"], body["max_tokens"], body["fallbacks"]) == (
        True,
        s.max_tokens,
        "default",
    )
    assert body["output_config"]["effort"] == s.effort
    assert body["output_config"]["format"]["schema"]["required"] == ["value"]
    assert seen[0].headers["anthropic-beta"] == FALLBACK_BETA


def test_claude_truncated_output_is_llm_error() -> None:
    llm = Claude("m", "low", 1024, sdk_client(sse_reply('{"val', "max_tokens"), []))
    with pytest.raises(LLMError, match="unparsable Answer output"):
        llm.parse(Answer, "s", "p")


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
    for v in KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(LLMError, match="ANIMATH_API_KEY or ANTHROPIC_API_KEY"):
        from_settings(Settings(), store)
    monkeypatch.setenv("ANIMATH_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fallback")
    on = from_settings(Settings(effort="max"), store)
    assert isinstance(on, Replay)
    assert isinstance(on.inner, Claude)
    assert on.inner.effort == "max"
    assert on.inner.client.api_key == "fallback"
    monkeypatch.setenv("ANIMATH_API_KEY", "primary")
    assert api_key() == "primary"


def test_session_requests_then_answers(tmp_path: Path) -> None:
    llm = Session(tmp_path)
    with pytest.raises(PendingError, match="Answer request pending"):
        llm.parse(Answer, "sys", "q", [b"\x89PNG"])
    (d,) = pending(tmp_path)
    req = json.loads((d / "request.json").read_text())
    assert req == {
        "schema": Answer.model_json_schema(),
        "system": "sys",
        "prompt": "q",
        "images": ["0.png"],
    }
    assert (d / "0.png").read_bytes() == b"\x89PNG"
    (d / "answer.json").write_text('{"value": "seven"}')
    with pytest.raises(LLMError, match="invalid answer"):
        llm.parse(Answer, "sys", "q", [b"\x89PNG"])
    (d / "answer.json").write_text('{"value": 7}')
    assert pending(tmp_path) == []
    assert llm.parse(Answer, "sys", "q", [b"\x89PNG"]) == (SEVEN, Usage())
    with pytest.raises(PendingError):
        llm.parse(Answer, "sys", "other")
    assert len(pending(tmp_path)) == 1


def test_session_settings(tmp_path: Path, store: Store) -> None:
    s = Settings(store=tmp_path, llm="session")
    llm = from_settings(s, store)
    assert isinstance(llm, Replay)
    assert isinstance(llm.inner, Session)
    assert (llm.tag, llm.inner.root) == ("session", tmp_path / "pending")
    assert tag(Settings(effort="low")) == "claude-opus-5-5:low"
    offline = from_settings(s.model_copy(update={"offline": True}), store)
    assert isinstance(offline, Replay)
    assert (offline.inner, offline.tag) == (None, "session")
