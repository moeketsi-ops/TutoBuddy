"""Speech-to-text for WhatsApp voice notes.

stub   — fixed transcript, fully offline (CI-safe).
local  — faster-whisper container (no API key; model downloaded once).
openai — Whisper API (placeholder key).
"""

import httpx

from app.config import settings

STUB_TRANSCRIPT = "How do I factorise x squared plus five x plus six?"


async def transcribe(audio: bytes, mime: str) -> str:
    if settings.stt_provider == "local":
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.stt_base_url.rstrip('/')}/transcribe",
                files={"file": ("voice-note", audio, mime)},
            )
            resp.raise_for_status()
            return resp.json()["text"].strip()

    if settings.stt_provider == "openai":
        if not settings.is_set(settings.openai_api_key):
            raise RuntimeError("STT_PROVIDER=openai but OPENAI_API_KEY is a placeholder")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files={"file": ("voice-note.ogg", audio, mime)},
                data={"model": "whisper-1"},
            )
            resp.raise_for_status()
            return resp.json()["text"].strip()

    return STUB_TRANSCRIPT
