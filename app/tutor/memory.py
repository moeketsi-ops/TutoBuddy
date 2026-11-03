"""Per-learner working memory: a 5-turn window in Redis, the last 2 turns
in the prompt, and a code-built digest of everything older.

Spec: "Katlego memory + pedagogy spec v0.1" (steps 1-3). Key points:

- Keyed by LEARNER (mem:{learner_id}), never by phone: the household
  session sess:{phone} is shared by siblings and must not carry one child's
  conversation into another's prompt.
- The window stores the learner's messages in full but Katlego's replies
  cut to their last question (~60 tokens), so 2 raw turns cost ~260 tokens.
- "Push to memory" (consolidate) happens every 5 turns and on a topic
  change: the oldest turns roll out of the window into one DIGEST line built
  by code from their STATE lines ("Algebraic Equations: 2 right, 1 wrong,
  sign errors; worked example helped"). No LLM call, so it is free and it
  can't invent anything. The digest also persists to learners.memory_digest
  so the next session starts with it. (An LLM-written summary + soft facts
  is step 4, a separate PR.)
- Mastery evidence is NOT written here; engine.tutor_reply writes it per
  turn through app.tutor.mastery, so nothing waits for consolidation.
"""

import json
import re
import time

from app.queue import get_redis

WINDOW = 5            # turns kept in Redis
PROMPT_TURNS = 2      # turns sent word for word
IDLE_SECONDS = 30 * 60
# Long enough that a session idle overnight is still there to be rolled into
# the digest on the next visit (load() does that). DELETE removes it at once.
TTL_SECONDS = 14 * 24 * 3600
DIGEST_KEEP = 6       # digest lines kept (session + persisted)
DIGEST_IN_PROMPT = 3

NEW_QUESTION = re.compile(
    r"^(how|what|why|when|which|where|solve|simplify|find|calculate|work out|factor|"
    r"factorise|factorize|expand|can you|could you|help me|i need help|teach me)\b",
    re.IGNORECASE)


def key(learner_id: int) -> str:
    return f"mem:{learner_id}"


def _new(learner_id: int, history: list[str] | None = None) -> dict:
    now = time.time()
    return {
        "v": 1,
        "learner_id": learner_id,
        "session_started": now,
        "last_turn_at": None,
        "turn_count": 0,        # turns since last consolidation
        "session_turns": 0,
        "turns": [],
        "digest": list(history or [])[-DIGEST_KEEP:],
        "working": _fresh_working(),
        "los_seen": [],         # LO codes touched this session
    }


def _fresh_working() -> dict:
    return {
        "topic_id": None, "topic": None, "lo_code": None,
        "problem": None, "strategy": None, "fails_in_row": 0,
        "tried": [], "wrong_on_problem": 0, "asked_answer": 0,
        "misc_recent": [], "last_hint": 0,
        # CPA + switching (spec v0.1 section 4)
        "level": None, "no_progress": 0, "switches": 0, "bridge": False,
        "last_switch_id": None, "since_switch": 0,
        # a "done" problem stays open one more turn (Immanuel, 870fc2b);
        # answered: the learner has reached the answer (leak guard off)
        "closing": False, "answered": False,
    }


def ensure_working(mem: dict) -> dict:
    """Memory saved before the CPA fields existed gets their defaults."""
    for k, v in _fresh_working().items():
        mem["working"].setdefault(k, v)
    return mem["working"]


async def load(learner_id: int, history: list[str] | None = None) -> dict:
    """This learner's memory. A missing key, or one idle for more than 30
    minutes, starts a new session (window and working problem cleared,
    digest kept). `history` = persisted digest lines from Postgres, used
    only when starting fresh."""
    raw = await get_redis().get(key(learner_id))
    mem = json.loads(raw) if raw else None
    if mem and mem.get("last_turn_at") and time.time() - mem["last_turn_at"] > IDLE_SECONDS:
        consolidate(mem, keep=0)
        mem = _new(learner_id, mem["digest"])
        mem["_persist"] = True  # engine writes the digest to Postgres
    if mem is None:
        mem = _new(learner_id, history)
    return mem


async def save(mem: dict) -> None:
    await get_redis().set(key(mem["learner_id"]), json.dumps(mem), ex=TTL_SECONDS)


async def forget(learner_id: int) -> None:
    """POPIA DELETE: drop the learner's working memory immediately."""
    await get_redis().delete(key(learner_id))


def is_new_session(mem: dict) -> bool:
    return mem["session_turns"] == 0


def has_open_problem(mem: dict) -> bool:
    return bool(mem["working"]["problem"])


ASKS_ANSWER = re.compile(
    r"\b(give|tell|send|show) me the (final )?answer\b|\bjust (the|give me the) answer\b|"
    r"\bwhat('?s| is) the (final )?answer\b",
    re.IGNORECASE)


ANOTHER_WAY = re.compile(
    r"\b(another|different|other) (way|method)\b|\bexplain (it |that )?(differently|again)\b|"
    r"\bshow me (a |another )?(different|other) way\b", re.IGNORECASE)
CONFUSED = re.compile(
    r"\bi (still )?(don'?t|do not|dont) (get|understand)\b|\bi'?m (lost|confused)\b|"
    r"\bmakes no sense\b|\bno idea\b", re.IGNORECASE)


def asks_other_way(text: str) -> bool:
    return bool(ANOTHER_WAY.search(text))


def is_confused(text: str) -> bool:
    return bool(CONFUSED.search(text))


SWITCH_INTENT = re.compile(r"\b(quiz|test me|practi[cs]e|another question)\b", re.IGNORECASE)


def asks_for_answer(text: str) -> bool:
    """Cheap pre-call check, so the second request is honoured on the SAME
    turn (the STATE line would only report it after the reply)."""
    return bool(ASKS_ANSWER.search(text))


def is_new_question(text: str) -> bool:
    """A fresh question ("How do I...", "Solve 5x = 35", "what about
    probability?") as opposed to a reply to the working problem ("x = 6",
    "minus 5?", "just give me the answer", "because 3a and 5a are like
    terms...")."""
    t = text.strip()
    words = t.split()
    return bool(NEW_QUESTION.match(t)) and len(words) >= 2 or ("?" in t and len(words) >= 5)


def continues_problem(mem: dict, text: str) -> bool:
    """Is this message about the problem we're working on? Then it skips
    intent routing (the router would see "minus 5?" out of context) and
    keeps the working topic instead of re-guessing it from retrieval."""
    if SWITCH_INTENT.search(text):
        return False  # "quiz me" mid-problem is a request, not an attempt
    if has_open_problem(mem) and (asks_other_way(text) or is_confused(text)):
        return True  # "can you show me another way?" is about THIS problem
    return has_open_problem(mem) and not is_new_question(text) and len(text.split()) <= 60


def compress_reply(reply: str, limit: int = 240) -> str:
    """Keep the part of Katlego's reply the learner is answering: its last
    question, else its tail."""
    flat = " ".join(reply.split())
    questions = re.findall(r"[^.!?\n]*\?", flat)
    text = questions[-1].strip() if questions else flat[-limit:]
    return text[:limit]


def record_turn(mem: dict, learner_text: str, reply: str, state: dict | None,
                topic: dict | None, strategy: str, *, new_problem: bool = False) -> bool:
    """Append a turn and update working state. Returns True when the window
    should be consolidated now (5 turns, or the topic changed)."""
    w = ensure_working(mem)
    ev = (state or {}).get("ev", "none")
    progress = (state or {}).get("progress")
    topic_changed = bool(topic and w["topic_id"] and topic["id"] != w["topic_id"])

    if topic_changed:
        consolidate(mem, keep=0)
        mem["_persist"] = True
        w = mem["working"] = _fresh_working()
        new_problem = True

    if topic:
        w["topic_id"], w["topic"] = topic["id"], topic["name"]
    if state and state.get("lo"):
        w["lo_code"] = state["lo"]
        if state["lo"] not in mem["los_seen"]:
            mem["los_seen"].append(state["lo"])

    # Working problem: a new question (or the first substantive message)
    # opens it, whatever the model labelled it ("What is -8 + 3?" often comes
    # back as asked_for_answer). A STATE step of "done" closes it a turn later.
    if new_problem and learner_text.strip():
        w["problem"] = learner_text[:200]
        w.update(fails_in_row=0, tried=[], wrong_on_problem=0, asked_answer=0, misc_recent=[],
                 level=None, no_progress=0, switches=0, bridge=False, last_switch_id=None,
                 since_switch=0, closing=False, answered=False)

    # No-progress count for the 3-turn switch rule: a turn with a step
    # forward (or a correct answer) resets it; a wrong / partial-without-
    # progress attempt, an answer request or "I don't get it" adds one.
    if progress in ("step_forward", "solved") or ev in ("attempt_correct", "explained_back"):
        w["no_progress"] = 0
    elif ev in ("attempt_wrong", "attempt_partial", "asked_for_answer") or is_confused(learner_text):
        w["no_progress"] += 1

    # `ev` judges the learner's message, i.e. the strategy of the PREVIOUS
    # reply; `strategy` is what THIS reply used.
    if ev in ("attempt_wrong", "attempt_partial", "asked_for_answer"):
        w["fails_in_row"] += 1
        if ev == "asked_for_answer":
            w["asked_answer"] += 1
        else:
            w["wrong_on_problem"] += 1
    elif ev in ("attempt_correct", "explained_back"):
        w["fails_in_row"] = 0
    if state and state.get("misc"):
        w["misc_recent"] = (w["misc_recent"] + [state["misc"]])[-WINDOW:]
    if strategy == "MISCONCEPTION_REMEDIATION":
        w["misc_recent"] = []  # remediated: don't keep re-triggering rule 3
    if strategy != w["strategy"]:
        w["fails_in_row"] = 0  # the new strategy hasn't failed yet
        w["strategy"] = strategy
    w["last_hint"] = (state or {}).get("hint", 0)
    if strategy not in w["tried"]:
        w["tried"].append(strategy)

    mem["turns"].append({
        "at": time.time(),
        "learner": learner_text[:300],
        "katlego": compress_reply(reply),
        "ev": ev,
        "misc": (state or {}).get("misc"),
        "strategy": strategy,
        "topic": w["topic"],
        "level": (state or {}).get("level") or w.get("level"),
    })
    mem["turns"] = mem["turns"][-WINDOW:]
    mem["turn_count"] += 1
    mem["session_turns"] += 1
    mem["last_turn_at"] = time.time()

    # A "done" problem stays open for one more turn, so the learner's echo of
    # the answer ("x = 32") is still read against it instead of retrieving
    # a random topic for "x = 32" alone. A wrong or partial attempt on that
    # turn means the "done" was premature, so it stays open. Code-checked
    # "solved" (CPA branch) counts as done.
    if w.get("closing") and not new_problem and ev not in ("attempt_wrong", "attempt_partial"):
        w["problem"], w["answered"] = None, False
    w["closing"] = bool(state and (state.get("step") == "done" or progress == "solved"))
    if w["closing"]:
        w.update(fails_in_row=0, tried=[], wrong_on_problem=0, asked_answer=0, misc_recent=[],
                 level=None, no_progress=0, switches=0, bridge=False, last_switch_id=None,
                 since_switch=0)
        if w["strategy"] == "RETRIEVAL_PRACTICE":
            w["strategy"] = None

    return mem["turn_count"] >= WINDOW


def digest_line(turns: list[dict]) -> str | None:
    """One line of history from STATE data, written by code."""
    if not turns:
        return None
    topic = next((t["topic"] for t in reversed(turns) if t.get("topic")), None) or "general"
    right = sum(t["ev"] in ("attempt_correct", "explained_back") for t in turns)
    wrong = sum(t["ev"] in ("attempt_wrong", "attempt_partial") for t in turns)
    asked = sum(t["ev"] == "asked_for_answer" for t in turns)
    miscs = sorted({t["misc"] for t in turns if t.get("misc")})
    helped = None
    for prev, nxt in zip(turns, turns[1:]):
        if nxt["ev"] in ("attempt_correct", "explained_back"):
            helped = prev["strategy"]
    bits = [f"{topic}: {right} right, {wrong} not yet"]
    if asked:
        bits.append(f"asked for the answer {asked}x")
    if miscs:
        bits.append("mistakes " + ", ".join(miscs))
    if helped:
        bits.append(helped.lower().replace("_", " ") + " helped")
    return "; ".join(bits)


def consolidate(mem: dict, keep: int = PROMPT_TURNS) -> str | None:
    """Roll all but the last `keep` turns into one digest line. Returns the
    line (or None if nothing rolled). Caller persists with persist_digest."""
    rolled = mem["turns"][:-keep] if keep else mem["turns"]
    mem["turns"] = mem["turns"][-keep:] if keep else []
    mem["turn_count"] = len(mem["turns"])
    line = digest_line(rolled)
    if line:
        mem["digest"] = (mem["digest"] + [line])[-DIGEST_KEEP:]
    return line


async def persist_digest(conn, mem: dict) -> None:
    await conn.execute(
        "UPDATE learners SET memory_digest = $2 WHERE id = $1",
        mem["learner_id"], json.dumps(mem["digest"][-DIGEST_KEEP:]),
    )


async def load_history(conn, learner_id: int) -> list[str]:
    raw = await conn.fetchval("SELECT memory_digest FROM learners WHERE id = $1", learner_id)
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def prompt_block(mem: dict, *, name: str | None, grade: int, lo_score: float | None,
                 review: dict | None) -> str:
    """The MEMORY section of the prompt (~150-300 tokens)."""
    w = mem["working"]
    lines = [f"MEMORY (what you know about this learner; never read it out)"]
    lines.append(f"LEARNER {name or 'learner'} · Grade {grade}")
    if w["topic"]:
        now = f"NOW {w['topic']}"
        if w["lo_code"]:
            now += f" · {w['lo_code']}"
        if lo_score is not None:
            from app.tutor.mastery import band
            now += f" · mastery {lo_score:.0f}% ({band(lo_score)})"
        lines.append(now)
    if w["problem"]:
        lines.append(f"WORKING PROBLEM \"{w['problem']}\" · not-yet attempts {w['wrong_on_problem']}"
                     + (f" · level {w['level']}" if w.get("level") else ""))
    if review:
        lines.append(f"REVIEW DUE {review['code']} ({review['score']:.0f}%): {review['objective'][:60]}")
    if mem["digest"]:
        lines.append("EARLIER " + " | ".join(mem["digest"][-DIGEST_IN_PROMPT:]))
    recent = mem["turns"][-PROMPT_TURNS:]
    if recent:
        lines.append("LAST TURNS")
        for t in recent:
            lines.append(f"  Learner: {t['learner']}")
            lines.append(f"  You: {t['katlego']}")
    return "\n".join(lines)
