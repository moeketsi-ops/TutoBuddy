"""The STATE line: how the tutor reports what happened in a turn without a
second LLM call.

Every Socratic reply ends with one hidden line, e.g.

    <<STATE lo=ZA-MATH-G08-ALG-EQ-001 ev=attempt_partial misc=SIGN_ERR strat=WORKED_EXAMPLE hint=1 step=2/3>>

The line is stripped before the reply is sent. Every field is checked
against a closed list that CODE supplied for this turn (LO candidates,
misconception codes, the strategy library). Anything unknown is dropped,
never stored, and a missing or broken line simply means "no evidence this
turn" -- the learner still gets their reply.

Why piggyback instead of a separate extraction call (Mem0-style): the
tutoring call has already read the learner's message and the working
problem, so judging the attempt there costs ~30 output tokens instead of a
second ~600-token call per turn.
"""

import json
import re

EVIDENCE = (
    "none",
    "attempt_correct",
    "attempt_partial",
    "attempt_wrong",
    "asked_for_answer",
    "explained_back",
)

# Any line that looks like a STATE line, however the model drifted: "<<STATE
# k=v ...>>", "<STATE k=v>", "STATE: k=v", stray brackets inside, or a line
# cut off by the token limit. Upper-case STATE followed by key=value pairs,
# so an ordinary sentence starting "State the rule..." is never touched.
_INLINE = re.compile(r"<{1,3}\s*STATE\b\s*:?(?P<body>[^\n]*)$", re.MULTILINE)
_BARE = re.compile(r"^[^\w\n]*STATE\b\s*:?\s*(?P<body>[a-z_]+\s*=[^\n]*)$", re.MULTILINE)
_PAIR = re.compile(r"([a-z_]+)\s*=\s*(\"[^\"]*\"|[^\s<>]+)", re.IGNORECASE)
_STEP = re.compile(r"^(\d{1,2}/\d{1,2}|done)$", re.IGNORECASE)


def strip_state(reply: str) -> tuple[str, str | None]:
    """(reply without any STATE line, the last STATE body or None).
    Removes every STATE-looking fragment so none can ever reach a learner:
    from "<STATE"/"<<STATE" to the end of its line wherever it starts, and
    any line that is just "STATE k=v ...". Then trims stray brackets."""
    found = [(m.start(), m.group("body")) for m in _INLINE.finditer(reply)]
    clean = _INLINE.sub("", reply)
    found += [(10**9 + m.start(), m.group("body")) for m in _BARE.finditer(clean)]
    clean = _BARE.sub("", clean)
    clean = re.sub(r"[ \t]+$", "", clean, flags=re.MULTILINE)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    bodies = [b.strip().rstrip(">").strip() for _, b in sorted(found)]
    bodies = [b for b in bodies if b]
    return clean, (bodies[-1] if bodies else None)


def parse_state(
    body: str | dict | None,
    *,
    lo_codes: set[str],
    misconception_codes: set[str],
    strategies: set[str],
) -> dict | None:
    """Validated STATE fields, or None when there is no usable line.
    Unknown values become the safe default for that field (lo/misc -> None,
    ev -> "none", hint -> 0); they are never passed through."""
    if body is None:
        return None
    if isinstance(body, dict):
        raw = {str(k).lower(): str(v) for k, v in body.items() if v is not None}
    else:
        raw = {k.lower(): v.strip('"') for k, v in _PAIR.findall(body)}
    if not raw:
        return None

    lo = raw.get("lo")
    ev = (raw.get("ev") or "none").lower()
    misc = raw.get("misc")
    strat = (raw.get("strat") or "").upper()
    try:
        hint = max(0, min(3, int(raw.get("hint", "0"))))
    except ValueError:
        hint = 0
    step = raw.get("step") if raw.get("step") and _STEP.match(raw["step"]) else None

    state = {
        "lo": lo if lo in lo_codes else None,
        "ev": ev if ev in EVIDENCE else "none",
        "misc": misc if misc in misconception_codes else None,
        "strategy": strat if strat in strategies else None,
        "hint": hint,
        "step": step,
    }
    # Evidence about an attempt is only usable when we know which objective
    # it was about; without an LO it is recorded against the working topic
    # by the caller, so keep ev as is.
    state["valid"] = (
        (lo is None or lo == "none" or state["lo"] is not None)
        and ev in EVIDENCE
        and (misc in (None, "none") or state["misc"] is not None)
        and state["strategy"] is not None
    )
    return state


# ── Structured output (founder decision 16 Oct: preferred over the STATE line)
# The tutoring call returns ONE JSON object: the turn's state first (judge the
# learner's message, choose the strategy), then the WhatsApp reply. With a
# provider that enforces the schema, every lo/misc/strat value is from this
# turn's closed lists by construction. The STATE line stays as the fallback
# for providers or models that refuse structured output.

def turn_schema(lo_codes: list[str], misconception_codes: list[str],
                strategies: list[str]) -> dict:
    """Strict JSON schema for one tutoring turn, built per turn so the enums
    are exactly this turn's candidates. Only types every provider's strict
    mode accepts (object, string, enum); hint is a string enum."""
    state = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ev": {"type": "string", "enum": list(EVIDENCE)},
            "lo": {"type": "string", "enum": sorted(set(lo_codes)) + ["none"]},
            "misc": {"type": "string", "enum": sorted(set(misconception_codes)) + ["none"]},
            "strat": {"type": "string", "enum": sorted(set(strategies))},
            "hint": {"type": "string", "enum": ["0", "1", "2", "3"]},
            "step": {"type": "string"},
        },
        "required": ["ev", "lo", "misc", "strat", "hint", "step"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"state": state, "reply": {"type": "string"}},
        "required": ["state", "reply"],
    }


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_REPLY_FIELD = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)


def parse_turn(text: str) -> tuple[str, str | dict | None, str]:
    """(reply for the learner, state body, mode). mode is "json" when the
    output was the JSON object, "state_line" when the model fell back to the
    hidden line, "none" when neither was found. Never returns JSON or a
    STATE fragment as the reply: a JSON-looking output that won't parse
    yields only its "reply" string, or "" (the caller treats "" as a failed
    turn, never sends it)."""
    raw = _FENCE.sub("", (text or "").strip())
    if raw.startswith("{"):
        obj = None
        try:
            obj = json.loads(raw)
        except ValueError:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except ValueError:
                    obj = None
        if isinstance(obj, dict) and isinstance(obj.get("reply"), str):
            reply, _ = strip_state(obj["reply"])
            st = obj.get("state") if isinstance(obj.get("state"), dict) else None
            return reply, st, "json"
        m = _REPLY_FIELD.search(raw)
        if m:
            try:
                reply = json.loads(f'"{m.group(1)}"')
            except ValueError:
                reply = m.group(1)
            return strip_state(reply)[0], None, "none"
        return "", None, "none"
    reply, body = strip_state(text or "")
    return reply, body, ("state_line" if body else "none")
