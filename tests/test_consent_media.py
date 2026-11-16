"""Guardian consent by voice note or photo of a signed slip, for families
who share one phone. Stored as evidence and erased with the learner. Off by
default (CONSENT_MEDIA_ENABLED): these tests run only when it is on."""

import hashlib
import os
from pathlib import Path

import pytest

from tests.conftest import db
from tests.test_photo import PNG_1PX

VOICE = Path(__file__).parent / "fixtures" / "voice_factorise.ogg"
ENABLED = os.environ.get("CONSENT_MEDIA_ENABLED", "").strip().lower() in ("1", "true", "yes")
needs_media = pytest.mark.skipif(not ENABLED, reason="CONSENT_MEDIA_ENABLED is off")


def _evidence(phone: str) -> list[dict]:
    return db(
        "SELECT r.method, r.level, r.needs_review, m.kind, m.mime, m.sha256, m.transcript "
        "FROM consent_records r JOIN consent_media m ON m.consent_record_id = r.id "
        "WHERE r.replied_from = $1", phone)


def _send_voice(chat) -> None:
    media_id = chat.upload_media(VOICE.read_bytes(), "audio/ogg")
    chat.send({"type": "audio", "audio": {"id": media_id, "mime_type": "audio/ogg", "voice": True}})


def _send_photo(chat) -> None:
    media_id = chat.upload_media(PNG_1PX, "image/png")
    chat.send({"type": "image", "image": {"id": media_id, "mime_type": "image/png", "caption": ""}})


@needs_media
def test_voice_note_is_kept_as_the_consent_record(chat):
    chat.send_text("hi")
    assert "VOICE" in chat.wait_for_reply()
    _send_voice(chat)                                   # a voice note before choosing VOICE
    assert "AGREE" in chat.wait_for_reply(timeout=120)  # is not consent
    assert _evidence(chat.phone) == []

    chat.send_text("voice")
    assert "voice note" in chat.wait_for_reply()
    _send_voice(chat)
    assert "call you" in chat.wait_for_reply(timeout=120).lower()

    (ev,) = _evidence(chat.phone)
    assert (ev["method"], ev["level"], ev["kind"]) == ("voice_note", "voice", "voice")
    assert ev["sha256"] == hashlib.sha256(VOICE.read_bytes()).hexdigest()   # the recording itself
    assert ev["transcript"]                               # what was heard, for a reviewer
    assert ev["needs_review"] is True                     # the fixture never says "agree"

    for msg in ("Thabo", "11", "DELETE"):                 # erasing the learner erases the recording
        chat.send_text(msg)
        chat.wait_for_reply()
    assert db("SELECT 1 FROM consent_media m JOIN consent_records r "
              "ON r.id = m.consent_record_id WHERE r.replied_from = $1", chat.phone) == []


@needs_media
def test_signed_slip_photo_is_kept_and_flagged_for_review(chat):
    chat.send_text("hi")
    chat.wait_for_reply()
    _send_photo(chat)                                     # a photo before choosing SLIP
    assert "AGREE" in chat.wait_for_reply()
    chat.send_text("SLIP")
    assert "photo" in chat.wait_for_reply()
    _send_photo(chat)
    assert "call you" in chat.wait_for_reply().lower()
    (ev,) = _evidence(chat.phone)
    assert (ev["method"], ev["level"], ev["kind"], ev["mime"]) == (
        "signed_slip", "slip", "slip", "image/png")
    assert ev["needs_review"] is True                     # nobody has looked at it yet


def test_media_routes_are_off_by_default(monkeypatch):
    from app.config import Settings, settings
    from app.orchestrator import consent

    assert Settings.model_fields["consent_media_enabled"].default is False
    monkeypatch.setattr(settings, "consent_media_enabled", False)
    assert "VOICE" not in consent.notice() and consent.media_choice("voice") is None
    monkeypatch.setattr(settings, "consent_media_enabled", True)
    assert "VOICE" in consent.notice() and consent.media_choice("Slip") == "slip"
