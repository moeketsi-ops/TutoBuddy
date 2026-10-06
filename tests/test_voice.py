"""Voice-note pipeline: media fetch → STT → safety → tutor engine.

With STT_PROVIDER=local this exercises real speech-to-text (faster-whisper)
on a real spoken-audio fixture — a live voice test with no API keys.
With STT_PROVIDER=stub the pipeline still runs end-to-end on a canned
transcript, so CI stays green without the whisper container.
"""

import os
from pathlib import Path

import httpx
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "voice_factorise.ogg"
STT_URL = os.environ.get("STT_BASE_URL", "http://localhost:9000").rstrip("/")


def _stt_mode() -> str:
    return os.environ.get("STT_PROVIDER", "stub")


def _stt_ready() -> bool:
    try:
        return httpx.get(f"{STT_URL}/health", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def test_voice_note_end_to_end(onboarded_chat):
    if not FIXTURE.exists():
        pytest.skip("voice fixture missing — run scripts/make_voice_fixture.sh")
    if _stt_mode() == "local" and not _stt_ready():
        pytest.skip("STT_PROVIDER=local but the stt service is not up yet")

    media_id = onboarded_chat.upload_media(FIXTURE.read_bytes(), "audio/ogg")
    onboarded_chat.send(
        {"type": "audio", "audio": {"id": media_id, "mime_type": "audio/ogg", "voice": True}}
    )
    # First transcription loads the whisper model — allow a generous timeout.
    reply = onboarded_chat.wait_for_reply(timeout=120)

    # The reply must echo what was heard and be grounded in the right topic.
    assert "I heard" in reply
    assert "factori" in reply.lower()  # factorise (SA/UK) or factorize (US): a real model and Whisper use either
