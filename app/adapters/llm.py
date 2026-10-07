"""Two-tier LLM adapter (blueprint §4.2: cheap router + frontier reasoner).

Tiers and who serves them:
  router   — classify_intent. Served by LLM_PROVIDER. (ROUTER_PROVIDER=jev in
             app/adapters/router.py can sit in front of it; this file is its
             fallback.)
  reasoner — socratic_reply, direct_answer, practice_question,
             grade_practice_answer, photo_reply. Served by REASONER_PROVIDER,
             or by LLM_PROVIDER when REASONER_PROVIDER is empty. That lets a
             cheap/fast provider route while a stronger one tutors, e.g.
             LLM_PROVIDER=groq + REASONER_PROVIDER=anthropic.

Providers:
  stub       — deterministic canned replies; fully offline, used by CI and
               the keyless demo. Never pretends to solve maths it didn't solve.
  anthropic  — Haiku (router) / a frontier model (reasoner). Vision capable.
  groq       — hosted open gpt-oss models. Text only.
  ollama     — fully local, no API key; quality depends on what's been
               `ollama pull`ed. Text only.
  openrouter — OpenAI-compatible API (https://openrouter.ai/api/v1), one key
               across many hosted models; wired for Qwen3.5-35B-A3B, which is
               multimodal, so it also powers photo_reply.

Every text call goes through one helper, _complete(): anthropic uses its
Messages API, ollama its native chat API, and groq + openrouter share the
OpenAI-style chat-completions path. Each public function below states only
its prompt, token budget and how to parse the reply.

Vision (photo_reply) is anthropic or openrouter only; other reasoner
providers fall back to the stub photo message.
"""

import base64
import logging
import re

from app.config import settings
from app.tutor import prompts

log = logging.getLogger("katlego.llm")

INTENTS = ("homework", "quiz", "smalltalk", "admin")
PROVIDERS = ("anthropic", "groq", "ollama", "openrouter")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


# ── Clients ───────────────────────────────────────────────────────────────────

def _anthropic_client():
    import anthropic

    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


def _groq_client():
    from groq import AsyncGroq

    return AsyncGroq(api_key=settings.groq_api_key)


def _ollama_client():
    from ollama import AsyncClient

    return AsyncClient(host=settings.ollama_base_url)


def _openrouter_client():
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=settings.openrouter_api_key)


# ── Provider selection ────────────────────────────────────────────────────────

def _available(provider: str) -> bool:
    """A provider is usable when it's named and its key is set. Ollama has no
    key: a bad host or unpulled model surfaces as a real error at call time
    rather than a silent fall-back to stub."""
    if provider == "anthropic":
        return settings.is_set(settings.anthropic_api_key)
    if provider == "groq":
        return settings.is_set(settings.groq_api_key)
    if provider == "openrouter":
        return settings.is_set(settings.openrouter_api_key)
    return provider == "ollama"


def _provider(tier: str) -> str | None:
    """The provider serving `tier` ("router" or "reasoner"), or None for stub."""
    name = settings.llm_provider
    if tier == "reasoner" and settings.reasoner_provider.strip():
        name = settings.reasoner_provider.strip()
    name = name.strip().lower()
    return name if name in PROVIDERS and _available(name) else None


def _model(provider: str, tier: str) -> str:
    return {
        ("anthropic", "router"): settings.router_model,
        ("anthropic", "reasoner"): settings.reasoner_model,
        ("groq", "router"): settings.groq_router_model,
        ("groq", "reasoner"): settings.groq_reasoner_model,
        ("ollama", "router"): settings.ollama_router_model,
        ("ollama", "reasoner"): settings.ollama_reasoner_model,
        ("openrouter", "router"): settings.openrouter_router_model,
        ("openrouter", "reasoner"): settings.openrouter_reasoner_model,
    }[(provider, tier)]


def using_stub() -> bool:
    """True when the reasoner tier has no real provider -- shared with
    evals/run_eval.py, whose scores come from direct_answer (a reasoner
    call) and aren't meaningful in stub mode."""
    return _provider("reasoner") is None


# ── The one text-completion helper ────────────────────────────────────────────

# OpenRouter + Qwen3.5 (a reasoning model): reasoning tokens count against
# max_tokens, and when they use the whole budget the API returns
# finish_reason="length" with EMPTY content
# (https://openrouter.ai/docs/use-cases/reasoning-tokens). With small budgets
# that crashed the worker on `None.strip()`. So each call states an OpenRouter
# reasoning effort ("none" for short, latency-sensitive calls; "low" plus a
# bigger budget where the model must actually solve maths), and a missing
# content field is treated as empty text, never stripped.

def _text_or_empty(content, provider: str, call: str, finish_reason=None) -> str:
    text = content or ""
    if not text.strip():
        log.warning("%s: %s returned no visible text (finish_reason=%s)",
                    call, provider, finish_reason)
    return text


async def _complete(
    provider: str,
    tier: str,
    call: str,
    system: str,
    user: str,
    max_tokens: int,
    *,
    openrouter_max_tokens: int | None = None,
    openrouter_reasoning: str = "none",
) -> str:
    """One system + user turn on `provider`, returning the reply text
    (possibly empty -- callers decide what empty means)."""
    model = _model(provider, tier)

    if provider == "anthropic":
        resp = await _anthropic_client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _text_or_empty(resp.content[0].text, provider, call)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    if provider == "ollama":
        # Native Ollama chat API; no token cap (unchanged from before).
        resp = await _ollama_client().chat(model=model, messages=messages)
        return _text_or_empty(resp["message"]["content"], provider, call)

    # groq + openrouter: OpenAI-style chat completions.
    if provider == "openrouter":
        client = _openrouter_client()
        extra = {
            "max_tokens": openrouter_max_tokens or max_tokens,
            "extra_body": {"reasoning": {"effort": openrouter_reasoning}},
        }
    else:
        client = _groq_client()
        extra = {"max_tokens": max_tokens}
    resp = await client.chat.completions.create(model=model, messages=messages, **extra)
    choice = resp.choices[0]
    return _text_or_empty(choice.message.content, provider, call, choice.finish_reason)


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

    provider = _provider("router")
    if provider:
        raw = await _complete(provider, "router", "classify_intent",
                              prompts.INTENT_SYSTEM, text, max_tokens=10)
        label = raw.strip().lower()
        return label if label in INTENTS else "homework"

    # stub: keyword heuristic, no model call
    if any(w in lowered for w in ("quiz", "practice", "test me")):
        return "quiz"
    if any(h in lowered for h in _HOMEWORK_HINTS):
        return "homework"
    return "smalltalk" if len(lowered.split()) <= 3 else "homework"


# ── Socratic tutoring ─────────────────────────────────────────────────────────

def _stub_socratic(
    question: str, chunks: list[dict], grade: int,
    above: dict | None = None, term_focus: dict | None = None,
) -> str:
    if above:
        # Grade rule: a higher-grade topic gets named, never taught, and the
        # learner is sent back to this term's focus for their own grade.
        focus = (
            f"This term in Grade {grade} you're working on *{term_focus['topic']}* — "
            f"say \"quiz me\" and we'll practise it."
            if term_focus else f"Which Grade {grade} topic are you busy with in class?"
        )
        return (
            f"That's a Grade {above['grade']} topic (*{above['topic']}*), so you'll learn "
            f"it in Grade {above['grade']} 🙂 For now, let's stick to Grade {grade} work. "
            f"{focus}\n\n"
            f"_(stub LLM — set LLM_PROVIDER in .env for real Socratic tutoring)_"
        )
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


async def socratic_reply(
    question: str,
    chunks: list[dict],
    grade: int,
    above: dict | None = None,
    grade_topics: list[str] | None = None,
    term_focus: dict | None = None,
) -> str:
    """`chunks` must already be the learner's own grade only (see
    app.tutor.rag.grade_scoped_context and the grade rule there)."""
    provider = _provider("reasoner")
    if not provider:
        return _stub_socratic(question, chunks, grade, above, term_focus)
    system = prompts.socratic_system(grade, chunks, above, grade_topics, term_focus)
    text = (await _complete(provider, "reasoner", "socratic_reply", system, question,
                            max_tokens=600)).strip()
    if not text:
        # An empty message would be sent to the learner as a blank reply.
        raise RuntimeError(f"socratic_reply: empty {provider} response")
    return text


async def direct_answer(question: str, chunks: list[dict], grade: int) -> str:
    """Full worked answer — used only by the eval harness, never sent to learners."""
    provider = _provider("reasoner")
    if not provider:
        return "(stub LLM cannot produce marked answers — set LLM_PROVIDER and its API key/host)"
    return (await _complete(provider, "reasoner", "direct_answer",
                            prompts.eval_system(grade, chunks), question,
                            max_tokens=800, openrouter_max_tokens=2000,
                            openrouter_reasoning="low")).strip()


# ── Practice questions (see prompts.practice_system for the anti-hallucination
# instructions around OCR'd past-paper excerpts) ─────────────────────────────

def _stub_practice(topic: str, grade: int) -> dict:
    return {
        "question": (
            f"Let's practise *{topic}* 🎯 Try a Grade {grade} CAPS-level problem on this "
            f"topic and show me your working when you're ready.\n\n"
            f"_(stub LLM — set LLM_PROVIDER in .env for a real generated practice question)_"
        ),
        # Stub never invents a ground-truth answer it hasn't actually solved
        # (see module docstring) -- grading falls back to the no-answer path.
        "model_answer": None,
    }


def _parse_practice_response(raw: str) -> dict:
    """Split a real provider's QUESTION:/FINAL_ANSWER: response (see
    prompts.practice_system) into the two fields. If a provider doesn't
    follow the format, fall back to treating the whole reply as the
    question with no captured ground-truth answer -- grade_practice_answer
    already has a defined fallback for that (see prompts.grade_practice_system)."""
    m = re.search(r"QUESTION:\s*(.*?)\s*FINAL_ANSWER:\s*(.*)", raw, re.DOTALL | re.IGNORECASE)
    if not m:
        log.warning("practice_question: response didn't match QUESTION:/FINAL_ANSWER: format")
        return {"question": raw.strip(), "model_answer": None}
    return {"question": m.group(1).strip(), "model_answer": m.group(2).strip()}


async def practice_question(
    topic: str, grade: int, band: str | None, excerpts: list[dict]
) -> dict:
    """Returns {"question": str, "model_answer": str | None} -- see
    prompts.practice_system for the QUESTION:/FINAL_ANSWER: contract this
    parses. Callers (app.tutor.engine.practice_reply) must only ever send
    the "question" field to the learner; "model_answer" is the ground
    truth grade_practice_answer() grades against later, never shown."""
    provider = _provider("reasoner")
    if not provider:
        return _stub_practice(topic, grade)
    system = prompts.practice_system(grade, topic, band, excerpts)
    user = f"Set me a practice question on {topic}."
    raw = await _complete(provider, "reasoner", "practice_question", system, user,
                          max_tokens=300, openrouter_max_tokens=1500,
                          openrouter_reasoning="low")
    if not raw.strip() and provider == "openrouter":
        # Seen in the Docker suite: even "low" reasoning can use the whole
        # 1500-token budget, leaving no question. Retry once without it.
        raw = await _complete(provider, "reasoner", "practice_question", system, user,
                              max_tokens=300, openrouter_max_tokens=1500,
                              openrouter_reasoning="none")
    if not raw.strip():
        # Never send the learner a blank "question" (the worker replies with
        # its error message instead and no practice question is left pending).
        raise RuntimeError(f"practice_question: empty {provider} response")
    return _parse_practice_response(raw)


# ── Grading a learner's answer to a practice question (closes the mastery
# loop -- see app.tutor.rag.record_practice_attempt) ────────────────────────

def _stub_grade(model_answer: str | None, learner_answer: str) -> dict:
    if model_answer and model_answer.strip().lower() in learner_answer.strip().lower():
        return {
            "correctness": "correct",
            "feedback": "Correct! Nicely worked out. _(stub LLM)_",
        }
    return {
        "correctness": "partial",
        "feedback": (
            "Thanks for giving that a go — set LLM_PROVIDER in .env for real "
            "grading. _(stub LLM)_"
        ),
    }


def _parse_grade_response(raw: str) -> dict:
    m = re.search(r"CORRECTNESS:\s*(correct|partial|incorrect)\s*FEEDBACK:\s*(.*)", raw, re.DOTALL | re.IGNORECASE)
    if not m:
        log.warning("grade_practice_answer: response didn't match CORRECTNESS:/FEEDBACK: format")
        return {"correctness": "partial", "feedback": raw.strip()[:300]}
    return {"correctness": m.group(1).strip().lower(), "feedback": m.group(2).strip()}


async def grade_practice_answer(
    question: str, model_answer: str | None, learner_answer: str, grade: int
) -> dict:
    """Returns {"correctness": "correct"|"partial"|"incorrect", "feedback": str}."""
    provider = _provider("reasoner")
    if not provider:
        return _stub_grade(model_answer, learner_answer)
    raw = await _complete(provider, "reasoner", "grade_practice_answer",
                          prompts.grade_practice_system(grade, question, model_answer),
                          learner_answer, max_tokens=200)
    return _parse_grade_response(raw)


# ── Vision (homework photos) ──────────────────────────────────────────────────
# anthropic or openrouter only (see module docstring). Multimodal message
# shapes differ per API, so this stays outside _complete().

async def photo_reply(image: bytes, mime: str, caption: str, grade: int) -> str:
    prompt_text = (
        caption or "Here is a photo of my homework problem. Help me work through it."
    )
    provider = _provider("reasoner")
    b64 = base64.b64encode(image).decode()

    if provider == "anthropic":
        resp = await _anthropic_client().messages.create(
            model=settings.reasoner_model,
            max_tokens=600,
            system=prompts.socratic_system(grade, []),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": mime, "data": b64},
                        },
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
        )
        return _text_or_empty(resp.content[0].text, provider, "photo_reply").strip()

    if provider == "openrouter":
        resp = await _openrouter_client().chat.completions.create(
            model=settings.openrouter_vision_model,
            max_tokens=600,
            extra_body={"reasoning": {"effort": "none"}},
            messages=[
                {"role": "system", "content": prompts.socratic_system(grade, [])},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": prompt_text},
                    ],
                },
            ],
        )
        choice = resp.choices[0]
        return _text_or_empty(choice.message.content, provider, "photo_reply",
                              choice.finish_reason).strip()

    return (
        "I can see you sent a photo of your work 📸 Photo help runs on "
        "the real model.\n\n_(stub LLM — add the Anthropic or OpenRouter key "
        "in .env to enable homework-photo help; groq/ollama don't support "
        "photo help here yet)_"
    )
