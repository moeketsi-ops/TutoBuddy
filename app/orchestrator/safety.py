"""Safety filter — runs before intent routing, always (blueprint §4.2).

A learner disclosing a crisis must reach a referral script, never a maths
prompt. This is a deliberately over-sensitive keyword screen for the POC;
production replaces it with a proper classifier + human review queue.
"""

import re

_CRISIS_PATTERNS = [
    r"\bkill (myself|me)\b",
    r"\bsuicid\w*\b",
    r"\bself[- ]?harm\w*\b",
    r"\bhurt (myself|me)\b",
    r"\bwant to die\b",
    r"\bdon'?t want to (live|be alive)\b",
    r"\bend (my life|it all)\b",
    r"\babus\w*\b",
    r"\bmolest\w*\b",
    r"\brap(e|ed|ing)\b",
    r"\bbeat(s|ing)? me\b",
    r"\btouch(es|ed|ing)? me\b.*\b(bad|wrong|private)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _CRISIS_PATTERNS]

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


def check(text: str) -> bool:
    """True if the message should be routed to the referral script."""
    return any(p.search(text) for p in _COMPILED)
