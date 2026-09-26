"""Intent router tier — the one place the worker asks "what kind of message
is this?" (blueprint §4.2: a cheap classifier in front of the expensive
reasoner).

ROUTER_PROVIDER selects the tier independently of LLM_PROVIDER:
  ""    (default) — follow LLM_PROVIDER via llm.classify_intent (unchanged).
  "jev" — TypeSafe AI's Jev: a typed-decision model that returns a Choice
          with calibrated probabilities instead of text. Falls back to
          llm.classify_intent on any error or when confidence is below
          JEV_MIN_CONFIDENCE, so a Jev outage can never break routing.

Jev API (POST https://api.typesafe.ai/v1/systemone, Bearer key): text-only,
~70–500 ms, $0.042 per million input tokens, waitlisted early access.
"""

import logging
import time

import httpx

from app.adapters import llm
from app.config import settings

log = logging.getLogger("katlego.router")

JEV_URL = "https://api.typesafe.ai/v1/systemone"

# Criteria mirror prompts.INTENT_SYSTEM so both tiers classify the same way.
INTENT_CRITERIA = {
    "homework": "A curriculum/school question or a request for help with maths (any grade, any phrasing, including code-switched or shorthand).",
    "quiz": "The learner asks to be tested, quizzed, given practice questions or exercises.",
    "smalltalk": "A greeting, thanks, chit-chat or an emotional check-in with no schoolwork content.",
    "admin": "Account, settings, profile, grade change, help, or how-the-bot-works questions.",
}


def jev_request(text: str) -> dict:
    return {
        "model": settings.jev_model,
        "state": text,
        "questions": {
            "intent": {
                "type": "choice",
                "instructions": "Classify this WhatsApp message from a South African school learner to a maths tutor bot.",
                "criteria": INTENT_CRITERIA,
            }
        },
    }


def parse_jev_response(body: dict) -> dict:
    """Normalise a /v1/systemone response to
    {label, confidence, probabilities, input_tokens}. Tolerates both the
    documented `{"answers": {"intent": …}}` shape and the flat
    `{"intent": …}` shape seen in some SDK examples."""
    answer = body.get("answers", body)["intent"]
    label = answer.get("choice")
    probs = answer.get("probabilities") or {}
    if label is None and probs:
        label = max(probs, key=probs.get)
    return {
        "label": label,
        "confidence": float(answer.get("confidence") or 0.0),
        "probabilities": probs,
        "input_tokens": int((body.get("usage") or {}).get("input_tokens") or 0),
    }


async def jev_classify(text: str) -> dict:
    """Raw Jev call: returns parse_jev_response(...) plus latency_ms. Raises on
    HTTP/parse errors — callers decide the fallback."""
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            JEV_URL,
            headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
            json=jev_request(text),
        )
        resp.raise_for_status()
        result = parse_jev_response(resp.json())
    result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def use_jev() -> bool:
    return settings.router_provider == "jev" and settings.is_set(settings.typesafe_api_key)


def accept(result: dict, threshold: float) -> bool:
    """Ponytail: a single confidence threshold is the whole acceptance policy.
    Tune it from evals/router_eval.py's accuracy-by-confidence table."""
    return result.get("label") in llm.INTENTS and result.get("confidence", 0.0) >= threshold


async def classify_intent(text: str) -> str:
    if use_jev():
        try:
            result = await jev_classify(text)
            if accept(result, settings.jev_min_confidence):
                return result["label"]
            log.warning("jev low confidence %.2f for %r — falling back", result["confidence"], text[:60])
        except Exception as exc:  # network, 4xx/5xx, unexpected body
            log.warning("jev call failed (%s) — falling back to LLM router", exc)
    return await llm.classify_intent(text)
