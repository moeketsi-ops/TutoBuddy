"""Two-tier LLM adapter (blueprint §4.2: cheap router + frontier reasoner).

stub      — deterministic canned replies; fully offline, used by CI and the
            keyless demo. Never pretends to solve maths it didn't solve.
anthropic — Haiku for intent routing, a frontier model for Socratic tutoring.
"""

import base64
import logging

from app.config import settings
from app.tutor import prompts

log = logging.getLogger("katlego.llm")

INTENTS = ("homework", "quiz", "smalltalk", "admin")


def _anthropic_client():
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _use_anthropic() -> bool:
    return settings.llm_provider == "anthropic" and settings.is_set(
        settings.anthropic_api_key
    )


# ── Intent routing ────────────────────────────────────────────────────────────

_SMALLTALK_WORDS = {"hi", "hello", "hey", "howzit", "sawubona", "thanks", "thank you", "dumela"}
_HOMEWORK_HINTS = (
    "solve", "factor", "calculate", "how do", "what is", "explain", "help",
    "equation", "prove", "graph", "derivative", "interest", "probability", "?",
)


async def classify_intent(text: str) -> str:
    lowered = text.lower().strip()
    if lowered in _SMALLTALK_WORDS:
        return "smalltalk"
    if not _use_anthropic():
        if any(h in lowered for h in _HOMEWORK_HINTS):
            return "homework"
        return "smalltalk" if len(lowered.split()) <= 3 else "homework"

    client = _anthropic_client()
    resp = await client.messages.create(
        model=settings.router_model,
        max_tokens=10,
        system=prompts.INTENT_SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    label = resp.content[0].text.strip().lower()
    return label if label in INTENTS else "homework"


# ── Socratic tutoring ─────────────────────────────────────────────────────────

def _stub_socratic(question: str, chunks: list[dict], grade: int) -> str:
    if not chunks:
        return (
            "Good question! I couldn't find that topic in my CAPS notes yet 📚 "
            "Try asking about algebra, functions, trigonometry, calculus or "
            "financial maths.\n\n_(stub LLM — add the Anthropic key in .env "
            "for real tutoring)_"
        )
    top = chunks[0]
    first_sentence = top["content"].split(". ")[0].rstrip(".") + "."
    return (
        f"Great question — this is about *{top['topic']}* (Grade {top['grade']} "
        f"{top['subject']}) 🎯\n\n"
        f"Let's think it through instead of jumping to the answer. "
        f"Remember: {first_sentence}\n\n"
        f"What do you think the first step should be? Reply with your attempt "
        f"and I'll guide you from there.\n\n"
        f"_(stub LLM — add the Anthropic key in .env for real Socratic "
        f"tutoring)_"
    )


async def socratic_reply(question: str, chunks: list[dict], grade: int) -> str:
    if not _use_anthropic():
        return _stub_socratic(question, chunks, grade)

    client = _anthropic_client()
    resp = await client.messages.create(
        model=settings.reasoner_model,
        max_tokens=600,
        system=prompts.socratic_system(grade, chunks),
        messages=[{"role": "user", "content": question}],
    )
    return resp.content[0].text.strip()


async def direct_answer(question: str, chunks: list[dict], grade: int) -> str:
    """Full worked answer — used only by the eval harness, never sent to learners."""
    if not _use_anthropic():
        return "(stub LLM cannot produce marked answers — set ANTHROPIC_API_KEY)"

    client = _anthropic_client()
    resp = await client.messages.create(
        model=settings.reasoner_model,
        max_tokens=800,
        system=prompts.eval_system(grade, chunks),
        messages=[{"role": "user", "content": question}],
    )
    return resp.content[0].text.strip()


# ── Vision (homework photos) ──────────────────────────────────────────────────

async def photo_reply(image: bytes, mime: str, caption: str, grade: int) -> str:
    if not _use_anthropic():
        return (
            "I can see you sent a photo of your work 📸 Photo help runs on "
            "the real model.\n\n_(stub LLM — add the Anthropic key in .env "
            "to enable homework-photo help)_"
        )

    client = _anthropic_client()
    resp = await client.messages.create(
        model=settings.reasoner_model,
        max_tokens=600,
        system=prompts.socratic_system(grade, []),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": base64.b64encode(image).decode(),
                        },
                    },
                    {
                        "type": "text",
                        "text": caption
                        or "Here is a photo of my homework problem. Help me work through it.",
                    },
                ],
            }
        ],
    )
    return resp.content[0].text.strip()
