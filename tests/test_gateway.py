"""Gateway behaviour: Meta verification handshake and webhook dedupe."""

import os

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")


def test_meta_verification_handshake():
    resp = httpx.get(
        f"{GATEWAY}/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "katlego-verify-token",
            "hub.challenge": "challenge-123",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "challenge-123"


def test_meta_verification_rejects_bad_token():
    resp = httpx.get(
        f"{GATEWAY}/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-123",
        },
    )
    assert resp.status_code == 403


def test_duplicate_webhook_delivery_is_processed_once(onboarded_chat):
    # Meta redelivers webhooks; the gateway dedupes on the WhatsApp message id.
    msg_id = f"wamid.dupe.{onboarded_chat.phone}"
    onboarded_chat.send_text("HELP", msg_id=msg_id)
    onboarded_chat.send_text("HELP", msg_id=msg_id)
    onboarded_chat.wait_for_reply()
    # Allow time for a hypothetical second reply, then confirm there is none.
    assert onboarded_chat.count_replies_within(3.0) == 0
