"""Safety filter -- child-safety architecture, layers 1 and 3 (blueprint
§4.2 + technical-blueprint-reconciliation.md's 4-layer model):

  1. Input safety  -- runs before intent routing, every message, no
     exceptions. Categorised risk screen (self-harm, abuse disclosure) plus
     a lightweight PII screen for what gets *stored* (not what gets sent to
     the tutor -- the model still sees the real question).
  2. AI tutor       -- app/tutor/* (curriculum-grounded RAG). Not this file.
  3. Output safety  -- runs on the LLM's own generated reply before it is
     sent: strips links (Katlego should never hand a child an external
     URL) and re-scans for the same risk categories, in case the model
     itself ever produces something a Socratic tutor never should.
  4. Safeguarding   -- app/orchestrator/safeguarding.py: persists every
     flagged case and alerts a human. The AI is never the final authority
     on a risk case -- this file only classifies and sanitises; it does
     not decide anything is "handled".

This remains a deliberately over-sensitive keyword/regex screen for the
POC, not a trained classifier -- false positives (routed to the referral
message when it wasn't truly a crisis) are an accepted, intentional
trade-off; false negatives are not.
"""

import re

from app.config import settings

# Each category is scanned independently so a flagged case can be logged
# and escalated with *why*, not just a bare yes/no.
_RISK_PATTERNS: dict[str, list[str]] = {
    "self_harm": [
        r"\bkill (myself|me)\b",
        r"\bsuicid\w*\b",
        r"\bself[- ]?harm\w*\b",
        r"\bhurt (myself|me)\b",
        r"\bwant to die\b",
        r"\bdon'?t want to (live|be alive)\b",
        r"\bend (my life|it all)\b",
        r"\bcut(ting)? myself\b",
    ],
    "abuse_disclosure": [
        r"\babus\w*\b",
        r"\bmolest\w*\b",
        r"\brap(e|ed|ing)\b",
        r"\bbeat(s|ing)? me\b",
        r"\btouch(es|ed|ing)? me\b.*\b(bad|wrong|private)\b",
        r"\bhe (hits|hit) me\b",
        r"\bshe (hits|hit) me\b",
    ],
}

_COMPILED: dict[str, list[re.Pattern]] = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in _RISK_PATTERNS.items()
}

REFERRAL_MESSAGE = (
    "Thank you for trusting me with this — what you're feeling matters, and "
    "you don't have to carry it alone. 💛\n\n"
    "Please reach out to someone who can really help, right now if you can:\n"
    "• *Childline South Africa*: call *116* — free from any phone, 24/7\n"
    "• *SADAG* (mental health helpline): 0800 567 567, or SMS 31393\n"
    "• If you are in immediate danger, call *10111*\n\n"
    "It also helps to tell a trusted adult — a parent, teacher or school "
    "counsellor. I'm here whenever you want to talk about schoolwork, but "
    "the people above are trained for exactly this. Please contact them. 🤝"
)

# ── Layer 1: input risk + PII ────────────────────────────────────────────────


def classify_risk(text: str) -> str | None:
    """Returns the matched risk category (e.g. "self_harm"), or None."""
    for category, patterns in _COMPILED.items():
        if any(p.search(text) for p in patterns):
            return category
    return None


def check(text: str) -> bool:
    """True if the message should be routed to the referral script instead
    of the tutor. Kept as a plain bool for callers that don't need the
    category (classify_risk is preferred when the category matters, e.g.
    for safeguarding.record_and_notify)."""
    return classify_risk(text) is not None


_SA_ID_NUMBER = re.compile(r"\b\d{13}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Loose SA-style phone number (not the learner's own conversation number --
# this catches a *different* number a learner might paste, e.g. someone
# else's contact details).
_PHONE_NUMBER = re.compile(r"\b(?:\+27|0)\d{9}\b")


def redact_pii(text: str) -> str:
    """Best-effort redaction for what gets WRITTEN TO STORAGE (conversation_log)
    -- POPIA data-minimisation: don't retain a 13-digit ID number or another
    person's contact details just because a learner happened to paste them.
    Never applied to the copy sent to the LLM -- if a learner's question
    genuinely needs that text, the tutor should still see it; only the
    stored/logged copy is minimised. Not exhaustive -- a simple pattern
    screen, not a PII-detection model."""
    text = _SA_ID_NUMBER.sub("[redacted: ID number]", text)
    text = _EMAIL.sub("[redacted: email]", text)
    text = _PHONE_NUMBER.sub("[redacted: phone number]", text)
    return text


# ── Layer 3: output safety ───────────────────────────────────────────────────

_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


_CONTROL = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # terminal codes, then stray controls


def sanitize_output(text: str) -> str:
    """Runs on every LLM-generated reply before it reaches the learner.

    - Strips any URL the model might produce (hallucinated or otherwise --
      Katlego should never hand a child an external link).
    - Re-scans the model's OWN text against the same risk categories as the
      input screen. This is a defense-in-depth check, not the expected
      path: a well-behaved Socratic tutor prompt should never generate
      self-harm/abuse content, but if it ever does (a jailbreak, a bizarre
      completion), the reply is replaced with the same referral message a
      learner disclosure would get, and the caller is expected to flag it
      for review as "model_output_risk" (see app.orchestrator.safeguarding).
    """
    if classify_risk(text) is not None:
        return REFERRAL_MESSAGE
    # Models now and then emit control characters (GPT-6 Luna: \x00 and \x1b
    # where it meant code formatting). Postgres rejects \x00, so logging the
    # reply crashed and the learner got "something went wrong".
    text = _CONTROL.sub("", text)
    # The one link Katlego sends on purpose: its own wa.me address, which a
    # guardian opens to confirm consent from their own phone (consent.py).
    own = f"https://wa.me/{settings.whatsapp_public_number}?" if settings.whatsapp_public_number else None
    return _URL.sub(
        lambda m: m.group(0) if own and m.group(0).startswith(own) else "[link removed]", text)
