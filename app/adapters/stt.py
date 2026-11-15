"""Speech-to-text for WhatsApp voice notes.

stub   — fixed transcript, fully offline (CI-safe).
local  — faster-whisper container (no API key; model downloaded once).
openai — Whisper API (placeholder key).
groq   — Groq-hosted Whisper (GROQ_STT_MODEL, default whisper-large-v3), GROQ_API_KEY.
"""

import httpx

from app.config import settings

STUB_TRANSCRIPT = "How do I factorise x squared plus five x plus six?"


def _language() -> dict:
    """STT_LANGUAGE=en forces English (the default); auto lets Whisper detect."""
    lang = settings.stt_language.strip().lower()
    out = {} if lang in ("", "auto") else {"language": lang}
    if settings.stt_prompt.strip():
        out["prompt"] = settings.stt_prompt.strip()
    return out


async def transcribe(audio: bytes, mime: str) -> str:
    if settings.stt_provider == "local":
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.stt_base_url.rstrip('/')}/transcribe",
                files={"file": ("voice-note", audio, mime)},
                data={"language": settings.stt_language.strip().lower() or "auto"},
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
                data={"model": "whisper-1", **({"prompt": settings.stt_prompt.strip()}
                                               if settings.stt_prompt.strip() else {})},
            )
            resp.raise_for_status()
            return resp.json()["text"].strip()

    if settings.stt_provider == "groq":
        if not settings.is_set(settings.groq_api_key):
            raise RuntimeError("STT_PROVIDER=groq but GROQ_API_KEY is a placeholder")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                files={"file": ("voice-note.ogg", audio, mime)},
                data={"model": settings.groq_stt_model, **_language()},
            )
            resp.raise_for_status()
            return resp.json()["text"].strip()

    return STUB_TRANSCRIPT
