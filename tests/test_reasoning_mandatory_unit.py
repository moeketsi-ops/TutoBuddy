"""OpenRouter models that cannot switch reasoning off (GLM-5.x, gpt-oss)
reject effort "none". _complete retries once at low and remembers the model;
classify_intent falls back to keywords if the router call fails."""

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters import llm


class FakeCompletions:
    def __init__(self, fail_on_none=True):
        self.calls = []
        self.fail_on_none = fail_on_none

    async def create(self, model, messages, **kw):
        self.calls.append(kw)
        if self.fail_on_none and kw["extra_body"]["reasoning"]["effort"] == "none":
            raise RuntimeError("Error code: 400 - {'error': {'message': 'Reasoning is mandatory for this endpoint and cannot be disabled.'}}")
        msg = SimpleNamespace(content="homework")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               usage=None, model=model, model_extra={})


@pytest.fixture
def fake(monkeypatch):
    comp = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    monkeypatch.setattr(llm, "_openrouter_client", lambda: client)
    monkeypatch.setattr(llm, "_effort", lambda tier: "")
    monkeypatch.setattr(llm, "_REASONING_REQUIRED", set())

    async def no_emit(**_):
        return None
    monkeypatch.setattr(llm, "_emit", no_emit)
    return comp


def test_retries_at_low_with_room_and_remembers(fake):
    out = asyncio.run(llm._complete("openrouter", "router", "classify_intent", "s", "u", max_tokens=10))
    assert out == "homework"
    assert [c["extra_body"]["reasoning"]["effort"] for c in fake.calls] == ["none", "low"]
    assert fake.calls[1]["max_tokens"] >= 10 + llm.EFFORT_HEADROOM["low"]
    # next call goes straight to low
    asyncio.run(llm._complete("openrouter", "router", "classify_intent", "s", "u", max_tokens=10))
    assert fake.calls[2]["extra_body"]["reasoning"]["effort"] == "low"
    assert len(fake.calls) == 3


def test_other_errors_still_raise(fake, monkeypatch):
    async def boom(**_):
        raise RuntimeError("401 invalid key")
    fake.create = boom
    with pytest.raises(RuntimeError, match="invalid key"):
        asyncio.run(llm._complete("openrouter", "router", "x", "s", "u", max_tokens=10))


def test_classify_intent_falls_back_to_keywords(monkeypatch):
    monkeypatch.setattr(llm, "_provider", lambda tier: "openrouter")

    async def down(*a, **k):
        raise RuntimeError("upstream 503")
    monkeypatch.setattr(llm, "_complete", down)
    assert asyncio.run(llm.classify_intent("quiz me on area")) == "quiz"
    assert asyncio.run(llm.classify_intent("How do I find the area of a rectangle?")) == "homework"


def test_error_reply_detected():
    from app.worker import ERROR_REPLY
    from evals.journey.driver import is_error
    assert is_error(ERROR_REPLY)
    assert not is_error("Nice one! What is 8 + 3?")
