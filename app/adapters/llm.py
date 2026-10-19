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
import contextlib
import contextvars
import json
import logging
import re
import time

from app.adapters import ledger
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


# ── Effort + per-call telemetry ──────────────────────────────────────────────

# Extra output tokens per effort level, on top of each call's visible budget,
# because reasoning tokens count against max_tokens on every provider.
# ponytail: fixed headroom per level; per-model tuning if the bench shows truncation.
EFFORT_HEADROOM = {"none": 0, "minimal": 512, "low": 1024, "medium": 2048, "high": 4096}

_calls: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_calls", default=None)


@contextlib.contextmanager
def capture_calls():
    """Collect telemetry for every model call made inside the block (served
    model, tokens incl. reasoning, billed cost, latency, stop reason, host).
    Used by evals/bench; a no-op cost in production, where nothing captures."""
    calls: list[dict] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


def _record(**fields) -> None:
    calls = _calls.get()
    if calls is not None:
        calls.append(fields)


async def _emit(**fields) -> None:
    """Telemetry for one real call: the bench's capture list (_record) and
    the production ledger (llm_calls table, app.adapters.ledger)."""
    _record(**fields)
    await ledger.persist(fields)


async def _log_stub(call: str, system: str, user: str, reply: str) -> None:
    """Stub calls go to the ledger as estimates (chars / 4) so prompt sizes
    can be compared offline. Not added to capture_calls(): the bench's stub
    floor stays exactly as before."""
    await ledger.persist({
        "call": call, "provider": "stub", "requested_model": "stub", "served_model": "stub",
        "input_tokens": ledger.estimate_tokens(system + user),
        "output_tokens": ledger.estimate_tokens(reply), "estimated": True,
    })


def _effort(tier: str) -> str:
    value = settings.router_effort if tier == "router" else settings.reasoner_effort
    value = (value or "").strip().lower()
    return value if value in EFFORT_HEADROOM else ""


def _usage_dict(usage) -> dict:
    """Normalise an SDK usage object (Anthropic or OpenAI-style) to plain ints.
    OpenRouter adds `cost` (USD actually billed) as an extra field."""
    if usage is None:
        return {}
    get = (lambda k: getattr(usage, k, None))
    details = get("completion_tokens_details")
    extra = getattr(usage, "model_extra", None) or {}
    return {
        "input_tokens": get("input_tokens") or get("prompt_tokens") or 0,
        "output_tokens": get("output_tokens") or get("completion_tokens") or 0,
        "reasoning_tokens": (getattr(details, "reasoning_tokens", None) or 0) if details else 0,
        "cost_usd": extra.get("cost", get("cost")),
    }


def _groq_reasoning(model: str, effort: str) -> dict:
    """Groq's reasoning parameters differ by model family (console.groq.com/docs/reasoning):
    - Qwen 3.x returns its reasoning INSIDE the reply as <think>…</think> unless
      reasoning_format is parsed/hidden, so it is always hidden here (a learner
      must never see it; JSON mode also rejects "raw"). Effort: none|low|medium|high.
    - gpt-oss takes no reasoning_format; include_reasoning=false keeps the
      reasoning out of the response. Effort: low|medium|high (cannot be off)."""
    if "qwen" in model.lower():
        body = {"reasoning_format": "hidden"}
        if effort:
            body["reasoning_effort"] = {"minimal": "low"}.get(effort, effort)
        return body
    body = {"include_reasoning": False}
    if effort:
        body["reasoning_effort"] = effort if effort in ("low", "medium", "high") else "low"
    return body


def _anthropic_text(resp) -> str:
    """First text block. Claude 5.x models think by default, so content[0]
    can be a thinking block with no .text."""
    return next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")


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
    effort_override: str | None = None,
    json_schema: dict | None = None,
) -> str:
    """One system + user turn on `provider`, returning the reply text
    (possibly empty -- callers decide what empty means).

    `json_schema`, when given, asks the provider to constrain the output to
    it (OpenAI-style response_format json_schema strict, Anthropic
    output_config.format, Ollama format). A provider that refuses raises;
    callers that can live without it catch and retry (socratic_reply).

    ROUTER_EFFORT / REASONER_EFFORT, when set, override the per-call effort
    default and widen the token limit by EFFORT_HEADROOM; when blank,
    behaviour is exactly as before."""
    model = _model(provider, tier)
    # effort_override lets a caller's own retry (e.g. practice_question's
    # "retry without reasoning") win over the configured effort.
    effort = effort_override if effort_override is not None else _effort(tier)
    headroom = EFFORT_HEADROOM.get(effort, 0)
    started = time.perf_counter()

    if provider == "anthropic":
        kwargs = {}
        if effort:
            # Anthropic levels are low|medium|high|xhigh|max; thinking can't be
            # switched off on Claude 5.5 models, so none/minimal map to low.
            kwargs["output_config"] = {"effort": effort if effort in ("low", "medium", "high") else "low"}
        if json_schema:
            kwargs.setdefault("output_config", {})["format"] = {"type": "json_schema", "schema": json_schema}
        resp = await _anthropic_client().messages.create(
            model=model,
            max_tokens=max_tokens + headroom,
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        await _emit(call=call, tier=tier, provider=provider, requested_model=model,
                served_model=resp.model, finish_reason=resp.stop_reason, host="anthropic",
                latency_s=round(time.perf_counter() - started, 3), **_usage_dict(resp.usage))
        return _text_or_empty(_anthropic_text(resp), provider, call)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    if provider == "ollama":
        # Native Ollama chat API; no token cap (unchanged from before).
        resp = await _ollama_client().chat(model=model, messages=messages,
                                           **({"format": json_schema} if json_schema else {}))
        await _emit(call=call, tier=tier, provider=provider, requested_model=model,
                served_model=model, finish_reason=None, host="ollama",
                latency_s=round(time.perf_counter() - started, 3))
        return _text_or_empty(resp["message"]["content"], provider, call)

    # groq + openrouter: OpenAI-style chat completions.
    if provider == "openrouter":
        client = _openrouter_client()
        body = {"reasoning": {"effort": effort or openrouter_reasoning}, "usage": {"include": True}}
        if settings.openrouter_provider.strip():
            body["provider"] = {"order": [settings.openrouter_provider.strip()], "allow_fallbacks": False}
        base = openrouter_max_tokens or max_tokens
        extra = {"max_tokens": max(base, max_tokens + headroom) if effort else base, "extra_body": body}
    else:
        client = _groq_client()
        if "qwen" not in model.lower() and effort in ("", "none", "minimal"):
            # gpt-oss always reasons (no "off" switch); without room for it a
            # 10-token router call comes back empty and silently becomes "homework".
            headroom = max(headroom, EFFORT_HEADROOM["minimal"])
        extra = {"max_tokens": max_tokens + headroom, "extra_body": _groq_reasoning(model, effort)}
    if json_schema:
        extra["response_format"] = {"type": "json_schema", "json_schema": {
            "name": call, "strict": True, "schema": json_schema}}
        if provider == "openrouter":
            # Route only to hosts that honour the schema; without this
            # OpenRouter may silently drop response_format.
            extra["extra_body"] = {**extra["extra_body"],
                                   "provider": {**extra["extra_body"].get("provider", {}),
                                                "require_parameters": True}}
    resp = await client.chat.completions.create(model=model, messages=messages, **extra)
    choice = resp.choices[0]
    await _emit(call=call, tier=tier, provider=provider, requested_model=model,
            served_model=getattr(resp, "model", model), finish_reason=choice.finish_reason,
            host=(getattr(resp, "model_extra", None) or {}).get("provider", provider),
            latency_s=round(time.perf_counter() - started, 3), **_usage_dict(getattr(resp, "usage", None)))
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


# How the last socratic_reply came back: "json" (schema enforced),
# "json_prompt" (provider refused the schema; JSON asked for in the prompt),
# "state_line" (STRUCTURED_OUTPUT=state_line) or "plain" (no pedagogy).
last_output_mode: contextvars.ContextVar[str] = contextvars.ContextVar("last_output_mode", default="plain")


def _stub_state(question: str, pedagogy: dict, lo_candidates: list[dict] | None,
                continuing: bool) -> dict:
    """A deterministic state for the offline stub, so the memory, mastery
    and pedagogy paths run end to end in CI. It never claims a correct
    answer it didn't check: an attempt is always 'partial'."""
    q = question.lower()
    if "explain" in q and ("because" in q or "i did" in q):
        ev = "explained_back"
    elif any(p in q for p in ("give me the answer", "tell me the answer", "just the answer")):
        ev = "asked_for_answer"
    elif continuing and re.search(r"\d|=", q):
        ev = "attempt_partial"
    else:
        ev = "none"
    return {"ev": ev, "lo": lo_candidates[0]["code"] if lo_candidates else "none",
            "misc": "none", "strat": pedagogy["strategy"], "hint": str(pedagogy["hint"]),
            "step": "1/3"}


def _is_refusal(exc: Exception) -> bool:
    """A provider rejecting the request shape (unsupported response_format /
    output_config), as opposed to an outage."""
    msg = repr(exc).lower()
    return any(k in msg for k in ("400", "422", "response_format", "not supported",
                                  "no endpoints", "output_config", "json_schema"))


async def socratic_reply(
    question: str,
    chunks: list[dict],
    grade: int,
    above: dict | None = None,
    grade_topics: list[str] | None = None,
    term_focus: dict | None = None,
    *,
    memory_block: str | None = None,
    pedagogy: dict | None = None,
    lo_candidates: list[dict] | None = None,
    misconceptions: list[dict] | None = None,
    continuing: bool = False,
) -> str:
    """`chunks` must already be the learner's own grade only (see
    app.tutor.rag.grade_scoped_context and the grade rule there).

    With `pedagogy` set (app.tutor.engine) the output carries the turn's
    state: by default a schema-constrained JSON object {state, reply}
    (STRUCTURED_OUTPUT=json); with STRUCTURED_OUTPUT=state_line, or when the
    provider refuses the schema, the hidden STATE line / prompt-only JSON.
    The engine parses it (app.tutor.state.parse_turn); this function never
    decides what reaches the learner."""
    from app.tutor import pedagogy as ped
    from app.tutor.state import turn_schema

    output = "plain"
    schema = None
    if pedagogy:
        output = "json" if settings.structured_output.strip().lower() != "state_line" else "state_line"
        if output == "json":
            schema = turn_schema([lo["code"] for lo in (lo_candidates or [])],
                                 [m["code"] for m in (misconceptions or [])],
                                 list(ped.STRATEGIES))
    system = prompts.socratic_system(
        grade, chunks, above, grade_topics, term_focus,
        memory_block=memory_block, pedagogy=pedagogy,
        lo_candidates=lo_candidates, misconceptions=misconceptions,
        output="json" if output == "json" else "state_line",
    )
    provider = _provider("reasoner")
    if not provider:
        reply = _stub_socratic(question, chunks, grade, above, term_focus)
        if output == "json":
            st = _stub_state(question, pedagogy, lo_candidates, continuing)
            reply = json.dumps({"state": st, "reply": reply}, ensure_ascii=False)
        elif output == "state_line":
            st = _stub_state(question, pedagogy, lo_candidates, continuing)
            reply += "\n<<STATE " + " ".join(f"{k}={v}" for k, v in st.items()) + ">>"
        last_output_mode.set(output)
        await _log_stub("socratic_reply", system, question, reply)
        return reply
    # 400 (was 600): a 120-word reply is ~160 tokens, plus ~40 for the state.
    # Effort headroom (REASONER_EFFORT) is added on top by _complete.
    mode = output
    try:
        text = await _complete(provider, "reasoner", "socratic_reply", system, question,
                               max_tokens=400, json_schema=schema)
    except Exception as exc:
        if schema is None or not _is_refusal(exc):
            raise
        log.warning("socratic_reply: %s refused the JSON schema (%s); asking in the prompt instead",
                    provider, repr(exc)[:200])
        mode = "json_prompt"
        text = await _complete(provider, "reasoner", "socratic_reply", system, question,
                               max_tokens=400)
    text = text.strip()
    if not text:
        # An empty message would be sent to the learner as a blank reply.
        raise RuntimeError(f"socratic_reply: empty {provider} response")
    last_output_mode.set(mode)
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
    system = prompts.practice_system(grade, topic, band, excerpts)
    user = f"Set me a practice question on {topic}."
    if not provider:
        out = _stub_practice(topic, grade)
        await _log_stub("practice_question", system, user, out["question"])
        return out
    raw = await _complete(provider, "reasoner", "practice_question", system, user,
                          max_tokens=300, openrouter_max_tokens=1500,
                          openrouter_reasoning="low")
    if not raw.strip() and provider == "openrouter":
        # Seen in the Docker suite: even "low" reasoning can use the whole
        # 1500-token budget, leaving no question. Retry once without it.
        raw = await _complete(provider, "reasoner", "practice_question", system, user,
                              max_tokens=300, openrouter_max_tokens=1500,
                              openrouter_reasoning="none", effort_override="none")
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
    system = prompts.grade_practice_system(grade, question, model_answer)
    if not provider:
        out = _stub_grade(model_answer, learner_answer)
        await _log_stub("grade_practice_answer", system, learner_answer, out["feedback"])
        return out
    raw = await _complete(provider, "reasoner", "grade_practice_answer",
                          system, learner_answer, max_tokens=200)
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
        return _text_or_empty(_anthropic_text(resp), provider, "photo_reply").strip()

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
