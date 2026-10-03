from __future__ import annotations

from types import SimpleNamespace

import httpx2
import pytest
from pydantic import BaseModel

from amg.ingest import claude


class Answer(BaseModel):
    value: str


def _response(stop_reason="end_turn", parsed=Answer(value="ok")):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                            cache_creation_input_tokens=2000, cache_read_input_tokens=0)
    return SimpleNamespace(model="claude-opus-5-5", usage=usage, stop_reason=stop_reason,
                           parsed_output=parsed, _request_id="req_123")


@pytest.fixture
def fake_client(monkeypatch):
    calls = []

    class Messages:
        response = _response()
        stream_error: Exception | None = None

        def parse(self, **kwargs):
            calls.append(kwargs)
            return self.response

        def stream(self, **kwargs):
            calls.append(kwargs)
            messages = self

            class Live:
                request_id = "req_streamed"

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def get_final_message(self):
                    if messages.stream_error:
                        raise messages.stream_error
                    return messages.response

            return Live()

    client = SimpleNamespace(beta=SimpleNamespace(messages=Messages()), options=[])

    def with_options(**options):
        client.options.append(options)
        return client

    client.with_options = with_options
    monkeypatch.setattr(claude, "client", lambda: client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # the server's .env may not exist yet
    return client, calls


def test_no_api_key_is_a_plain_error_not_a_crash(fake_client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(claude.ClaudeError, match="ANTHROPIC_API_KEY"):
        claude.parse(Answer, "system", [{"type": "text", "text": "hi"}])
    assert fake_client[1] == []  # never called


def test_parse_returns_the_object_and_usage(fake_client, monkeypatch):
    monkeypatch.delenv("AMG_CLAUDE_MODEL", raising=False)
    client, calls = fake_client
    answer, usage = claude.parse(Answer, "system", [{"type": "text", "text": "hi"}], effort="low", timeout=60)
    assert answer.value == "ok"
    assert client.options == [{"timeout": 60}]
    assert calls[0]["model"] == "claude-opus-5-5"
    assert calls[0]["fallbacks"] == "default" and calls[0]["betas"] == [claude.FALLBACK_BETA]
    assert calls[0]["output_config"] == {"effort": "low"}
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    # 1000 in at $4 + 2000 cache writes at $5 + 500 out at $20, per million
    assert usage.cost_usd == pytest.approx((1000 * 4 + 2000 * 5 + 500 * 20) / 1e6)
    assert usage.request_id == "req_123"


def test_model_comes_from_the_environment(fake_client, monkeypatch):
    monkeypatch.setenv("AMG_CLAUDE_MODEL", "claude-haiku-4-5")
    _, calls = fake_client
    claude.parse(Answer, "s", [])
    assert calls[0]["model"] == "claude-haiku-4-5"


@pytest.mark.parametrize(
    ("stop_reason", "parsed", "message"),
    [("refusal", None, "declined"), ("max_tokens", None, "cut off"), ("end_turn", None, "expected format")],
)
def test_unusable_answers_raise(fake_client, stop_reason, parsed, message):
    client, _ = fake_client
    client.beta.messages.response = _response(stop_reason, parsed)
    with pytest.raises(claude.ClaudeError, match=message):
        claude.parse(Answer, "s", [])


def test_a_streamed_answer_is_parsed_the_same_way(fake_client):
    client, calls = fake_client
    answer, usage = claude.parse(Answer, "s", [], effort="high", max_tokens=32_000, stream=True)
    assert answer.value == "ok"
    assert calls[0]["output_format"] is Answer and calls[0]["max_tokens"] == 32_000
    assert usage.request_id == "req_streamed"


def test_a_stream_that_goes_quiet_is_a_plain_error(fake_client):
    client, _ = fake_client
    client.beta.messages.stream_error = httpx2.ReadTimeout("quiet")
    with pytest.raises(claude.ClaudeError, match="too long"):
        claude.parse(Answer, "s", [], stream=True)


def test_unknown_model_has_no_cost():
    assert claude.Usage("some-future-model", 1, 1, 0, 0, 0.1, None).cost_usd is None
