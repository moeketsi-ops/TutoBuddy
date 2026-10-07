"""E2E test helpers.

Tests drive the real gateway with Meta-format webhook payloads and assert on
what the mock Cloud API captured — the same path a live WhatsApp message takes.
Each test uses a fresh phone number, so tests are isolated without resets.

Run inside compose (recommended):  docker compose run --rm tests
Run from the host:                 GATEWAY_URL=http://localhost:8000 \
                                   MOCKWA_URL=http://localhost:8001 pytest
"""

import os
import time
import uuid

import httpx
import pytest

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")

# The suite runs against whatever LLM_PROVIDER .env selects (the tests
# container shares the app's env_file). With the keyless stub, replies are
# instant and their wording is fixed, so tests can assert exact phrases.
# With a real model (openrouter, anthropic, groq, ollama) replies take
# seconds and are phrased freely, so waits are longer and wording checks
# become behaviour checks (see stub_wording below).
REAL_LLM = os.environ.get("LLM_PROVIDER", "stub").strip().lower() not in ("", "stub")
REPLY_TIMEOUT = float(os.environ.get("TEST_REPLY_TIMEOUT") or (90 if REAL_LLM else 30))
WORKER_ERROR = "something went wrong on my side"
NO_CONTENT_FALLBACK = "couldn't find that topic"


def run_with_app_db(coro_factory):
    """Run app code that uses app.db's cached asyncpg pool inside its own event
    loop. The pool is bound to the loop that created it, so reset it before
    and close it after; otherwise a second test's asyncio.run() inherits a
    pool from a dead loop."""
    import asyncio

    import app.db as db

    async def run():
        db._pool = None
        try:
            return await coro_factory()
        finally:
            if db._pool is not None:
                await db._pool.close()
            db._pool = None

    return asyncio.run(run())


def assert_tutored(reply: str) -> None:
    """A real tutoring reply: not the worker's error message, not the
    no-content fallback, and Socratic (asks the learner something)."""
    assert WORKER_ERROR not in reply.lower(), reply
    assert NO_CONTENT_FALLBACK not in reply.lower(), reply
    assert "?" in reply, reply
MOCKWA = os.environ.get("MOCKWA_URL", "http://localhost:8001").rstrip("/")


def fresh_phone() -> str:
    return "2782" + str(int(uuid.uuid4().int % 10**7)).zfill(7)


def webhook_payload(phone: str, message: dict, msg_id: str | None = None) -> dict:
    msg = {
        "from": phone,
        "id": msg_id or f"wamid.test.{uuid.uuid4().hex}",
        "timestamp": str(int(time.time())),
        **message,
    }
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "0",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "000000000000000"},
                    "contacts": [{"wa_id": phone, "profile": {"name": "Test Learner"}}],
                    "messages": [msg],
                },
            }],
        }],
    }


class Chat:
    """A simulated learner: send messages, await Katlego's replies."""

    def __init__(self, phone: str | None = None):
        self.phone = phone or fresh_phone()
        self.cursor = 0
        self.client = httpx.Client(timeout=30)

    def send(self, message: dict, msg_id: str | None = None) -> None:
        resp = self.client.post(
            f"{GATEWAY}/webhook", json=webhook_payload(self.phone, message, msg_id)
        )
        assert resp.status_code == 200, resp.text

    def send_text(self, body: str, msg_id: str | None = None) -> None:
        self.send({"type": "text", "text": {"body": body}}, msg_id)

    def upload_media(self, blob: bytes, mime: str) -> str:
        resp = self.client.post(
            f"{MOCKWA}/media", files={"file": ("fixture", blob, mime)}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    def replies(self) -> list[str]:
        resp = self.client.get(
            f"{MOCKWA}/outbox", params={"to": self.phone, "since": self.cursor}
        )
        data = resp.json()
        self.cursor = data["next"]
        return [m["body"] for m in data["messages"]]

    def wait_for_reply(self, timeout: float | None = None) -> str:
        timeout = timeout or REPLY_TIMEOUT
        deadline = time.time() + timeout
        while time.time() < deadline:
            got = self.replies()
            if got:
                return got[0]
            time.sleep(0.4)
        raise AssertionError(f"no reply for {self.phone} within {timeout}s")

    def count_replies_within(self, seconds: float) -> int:
        time.sleep(seconds)
        return len(self.replies())


@pytest.fixture
def chat() -> Chat:
    return Chat()


@pytest.fixture
def onboarded_chat() -> Chat:
    """A learner who has completed consent + name + grade onboarding
    (nickname "Thabo", Grade 11)."""
    c = Chat()
    c.send_text("hi")
    assert "POPIA" in c.wait_for_reply()
    c.send_text("AGREE")
    assert "call you" in c.wait_for_reply().lower()
    c.send_text("Thabo")
    assert "grade" in c.wait_for_reply().lower()
    c.send_text("11")
    assert "Grade 11" in c.wait_for_reply()
    return c
