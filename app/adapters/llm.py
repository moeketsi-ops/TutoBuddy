"""Two-tier LLM adapter (blueprint §4.2: cheap router + frontier reasoner).

stub      — deterministic canned replies; fully offline, used by CI and the
            keyless demo. Never pretends to solve maths it didn't solve.
anthropic — Haiku for intent routing, a frontier model for Socratic tutoring.
groq      — same two-tier split, served by Groq's hosted open gpt-oss models.
            Free/cheap alternative to Anthropic; no vision support (used only
            for classify_intent/socratic_reply/direct_answer, never photos).
ollama    — fully local/offline, no API key, via a locally running Ollama
            server. Same caveat as groq: text only, and the model quality
            depends entirely on what's been `ollama pull`ed -- not assumed to
            match the hosted providers.

Vision (photo_reply) intentionally stays anthropic-only: neither Groq's
gpt-oss models nor an arbitrary local Ollama pull are assumed to be
vision-capable. Falls back to the stub message for groq/ollama, same as it
already did for stub mode.
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


def _groq_client():
    from groq import AsyncGroq

    return AsyncGroq(api_key=settings.groq_api_key)


def _ollama_client():
    from ollama import AsyncClient

    return AsyncClient(host=settings.ollama_base_url)


def _use_anthropic() -> bool:
    return settings.llm_provider == "anthropic" and settings.is_set(
        settings.anthropic_api_key
    )


def _use_groq() -> bool:
    return settings.llm_provider == "groq" and settings.is_set(settings.groq_api_key)


def _use_ollama() -> bool:
    # No API key to check -- provider selection alone is enough. A bad host
    # or an unpulled model surfaces as a real connection/response error at
    # call time rather than silently falling back to stub, so it's obvious
    # something's actually wrong rather than looking like stub mode.
    return settings.llm_provider == "ollama"


def using_stub() -> bool:
    """True when no real provider is configured -- shared with evals/run_eval.py
    so the "scores aren't meaningful" warning covers every real provider, not
    just anthropic."""
    return not (_use_anthropic() or _use_groq() or _use_ollama())


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

    if _use_anthropic():
        client = _anthropic_client()
        resp = await client.messages.create(
            model=settings.router_model,
            max_tokens=10,
            system=prompts.INTENT_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        label = resp.content[0].text.strip().lower()
        return label if label in INTENTS else "homework"

    if _use_groq():
        client = _groq_client()
        resp = await client.chat.completions.create(
            model=settings.groq_router_model,
            max_tokens=10,
            messages=[
                {"role": "system", "content": prompts.INTENT_SYSTEM},
                {"role": "user", "content": text},
            ],
        )
        label = resp.choices[0].message.content.strip().lower()
        return label if label in INTENTS else "homework"

    if _use_ollama():
        client = _ollama_client()
        resp = await client.chat(
            model=settings.ollama_router_model,
            messages=[
                {"role": "system", "content": prompts.INTENT_SYSTEM},
                {"role": "user", "content": text},
            ],
        )
        label = resp["message"]["content"].strip().lower()
        return label if label in INTENTS else "homework"

    # stub: keyword heuristic, no model call
    if any(h in lowered for h in _HOMEWORK_HINTS):
        return "homework"
    return "smalltalk" if len(lowered.split()) <= 3 else "homework"


# ── Socratic tutoring ─────────────────────────────────────────────────────────

def _stub_socratic(question: str, chunks: list[dict], grade: int) -> str:
    if not chunks:
        return (
            "Good question! I couldn't find that topic in my CAPS notes yet 📚 "
            "Try asking about algebra, functions, trigonometry, calculus or "
            "financial maths.\n\n_(stub LLM — set LLM_PROVIDER in .env "
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
        f"_(stub LLM — set LLM_PROVIDER in .env for real Socratic "
        f"tutoring)_"
    )


async def socratic_reply(question: str, chunks: list[dict], grade: int) -> str:
    if _use_anthropic():
        client = _anthropic_client()
        resp = await client.messages.create(
            model=settings.reasoner_model,
            max_tokens=600,
            system=prompts.socratic_system(grade, chunks),
            messages=[{"role": "user", "content": question}],
        )
        return resp.content[0].text.strip()

    if _use_groq():
        client = _groq_client()
        resp = await client.chat.completions.create(
            model=settings.groq_reasoner_model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": prompts.socratic_system(grade, chunks)},
                {"role": "user", "content": question},
            ],
        )
        return resp.choices[0].message.content.strip()

    if _use_ollama():
        client = _ollama_client()
        resp = await client.chat(
            model=settings.ollama_reasoner_model,
            messages=[
                {"role": "system", "content": prompts.socratic_system(grade, chunks)},
                {"role": "user", "content": question},
            ],
        )
        return resp["message"]["content"].strip()

    return _stub_socratic(question, chunks, grade)


async def direct_answer(question: str, chunks: list[dict], grade: int) -> str:
    """Full worked answer — used only by the eval harness, never sent to learners."""
    if _use_anthropic():
        client = _anthropic_client()
        resp = await client.messages.create(
            model=settings.reasoner_model,
            max_tokens=800,
            system=prompts.eval_system(grade, chunks),
            messages=[{"role": "user", "content": question}],
        )
        return resp.content[0].text.strip()

    if _use_groq():
        client = _groq_client()
        resp = await client.chat.completions.create(
            model=settings.groq_reasoner_model,
            max_tokens=800,
            messages=[
                {"role": "system", "content": prompts.eval_system(grade, chunks)},
                {"role": "user", "content": question},
            ],
        )
        return resp.choices[0].message.content.strip()

    if _use_ollama():
        client = _ollama_client()
        resp = await client.chat(
            model=settings.ollama_reasoner_model,
            messages=[
                {"role": "system", "content": prompts.eval_system(grade, chunks)},
                {"role": "user", "content": question},
            ],
        )
        return resp["message"]["content"].strip()

    return "(stub LLM cannot produce marked answers — set LLM_PROVIDER and its API key/host)"


# ── Practice questions (see prompts.practice_system for the anti-hallucination
# instructions around OCR'd past-paper excerpts) ─────────────────────────────

def _stub_practice(topic: str, grade: int) -> str:
    return (
        f"Let's practise *{topic}* 🎯 Try a Grade {grade} CAPS-level problem on this "
        f"topic and show me your working when you're ready.\n\n"
        f"_(stub LLM — set LLM_PROVIDER in .env for a real generated practice question)_"
    )


async def practice_question(
    topic: str, grade: int, band: str | None, excerpts: list[dict]
) -> str:
    system = prompts.practice_system(grade, topic, band, excerpts)
    user_msg = f"Set me a practice question on {topic}."

    if _use_anthropic():
        client = _anthropic_client()
        resp = await client.messages.create(
            model=settings.reasoner_model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
        return resp.content[0].text.strip()

    if _use_groq():
        client = _groq_client()
        resp = await client.chat.completions.create(
            model=settings.groq_reasoner_model,
            max_tokens=300,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
        )
        return resp.choices[0].message.content.strip()

    if _use_ollama():
        client = _ollama_client()
        resp = await client.chat(
            model=settings.ollama_reasoner_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
        )
        return resp["message"]["content"].strip()

    return _stub_practice(topic, grade)


# ── Vision (homework photos) ──────────────────────────────────────────────────
# Anthropic-only, deliberately: see module docstring.

async def photo_reply(image: bytes, mime: str, caption: str, grade: int) -> str:
    if not _use_anthropic():
        return (
            "I can see you sent a photo of your work 📸 Photo help runs on "
            "the real model.\n\n_(stub LLM — add the Anthropic key in .env "
            "to enable homework-photo help; groq/ollama don't support photo "
            "help here yet)_"
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
