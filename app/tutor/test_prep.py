"""Test prep: know when a learner is close to writing a test, and point the
practice at the topics it covers.

Two sources, in order (founder decision, 5 Nov 2026):
1. The learner says so ("I'm writing a test on Friday on functions"), or
   answers Katlego's question about it. Stored in learner_tests.
2. Otherwise the ATP: the 2026 school calendar gives the term and week,
   and atp_topic_schedule says which topic blocks just finished (tests
   usually follow a topic block) or whether the exam block is on.

School dates vary, so the ATP is only ever a suggestion ("by the ATP, your
class has probably just finished Functions"), never stated as fact.
"""

from __future__ import annotations

import datetime
import re

# 2026 public school calendar (gov.za school calendar, DBE notice of
# 26 Feb 2025): learners' first and last day per term.
TERMS_2026 = (
    (datetime.date(2026, 1, 14), datetime.date(2026, 3, 27)),
    (datetime.date(2026, 4, 8), datetime.date(2026, 6, 26)),
    (datetime.date(2026, 7, 21), datetime.date(2026, 9, 23)),
    (datetime.date(2026, 10, 6), datetime.date(2026, 12, 9)),
)

TEST_WORDS = re.compile(r"\b(test|exam|exams|assessment|control test|common test|trials?|prelims?)\b",
                        re.IGNORECASE)
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
WHEN = re.compile(
    r"\b(today|tomorrow|next week|this week|on (?:" + "|".join(WEEKDAYS) + r")|"
    + "|".join(WEEKDAYS) + r"|in (\d+) days?|(\d{1,2}) (" + "|".join(MONTHS) + r")[a-z]*|"
    r"(\d{1,2})/(\d{1,2}))\b", re.IGNORECASE)
ABOUT = re.compile(
    r"\b(?:writing|write|wrote|have|got|there'?s)\s+(?:a|an|my|the|our)\s+(?:maths?\s+|math\s+)?"
    r"(?:control\s+|common\s+|class\s+)?(?:test|exam|assessment)\b", re.IGNORECASE)


def term_week(day: datetime.date) -> tuple[int, int] | None:
    """(term, week) for a school day in 2026, or None in the holidays."""
    for term, (start, end) in enumerate(TERMS_2026, 1):
        if start <= day <= end:
            return term, (day - start).days // 7 + 1
    return None


def mentions_test(text: str) -> bool:
    """A learner telling Katlego about a coming test (not a question that
    merely contains the word, like "how do I test if a number is prime")."""
    return bool(TEST_WORDS.search(text)) and bool(WHEN.search(text) or ABOUT.search(text))


def due_date(text: str, today: datetime.date) -> datetime.date | None:
    m = WHEN.search(text)
    if not m:
        return None
    w = m.group(1).lower()
    if w == "today":
        return today
    if w == "tomorrow":
        return today + datetime.timedelta(days=1)
    if w == "this week":
        return today + datetime.timedelta(days=max(0, 4 - today.weekday()))
    if w == "next week":
        return today + datetime.timedelta(days=7 - today.weekday())
    if m.group(2):
        return today + datetime.timedelta(days=int(m.group(2)))
    if m.group(3):
        month = MONTHS.index(m.group(4).lower()[:3]) + 1
        d = datetime.date(today.year, month, int(m.group(3)))
        return d if d >= today else datetime.date(today.year + 1, month, int(m.group(3)))
    if m.group(5):
        d = datetime.date(today.year, int(m.group(6)), int(m.group(5)))
        return d if d >= today else d.replace(year=today.year + 1)
    day = w.replace("on ", "")
    if day in WEEKDAYS:
        ahead = (WEEKDAYS.index(day) - today.weekday()) % 7 or 7
        return today + datetime.timedelta(days=ahead)
    return None


def topics_named(text: str, grade_topics: list[str]) -> list[str]:
    """Grade topics the message names: the keyword hints first, then any
    topic sharing a meaningful word ("functions", "trig", "probability")."""
    from app.tutor.rag import topic_hint

    found = []
    hint = topic_hint(text, grade_topics)
    if hint:
        found.append(hint)
    t = text.lower().replace("trig ", "trigonometry ").replace("stats", "statistics")
    words = {w for w in re.findall(r"[a-z]+", t) if len(w) > 4}
    for topic in grade_topics:
        tw = {w for w in re.findall(r"[a-z]+", topic.lower()) if len(w) > 4}
        if tw & words and topic not in found:
            found.append(topic)
    return found


def plan_text(due: datetime.date | None, topics: list[str], today: datetime.date,
              have_papers: list[str]) -> str:
    when = "soon"
    if due:
        days = (due - today).days
        when = ("today" if days == 0 else "tomorrow" if days == 1
                else f"on {due.strftime('%A %d %b').replace(' 0', ' ')} ({days} days)")
    lines = [f"Noted: test {when}" + (f" on {', '.join(topics)}" if topics else "") + " 📅"]
    covered = [t for t in topics if t in have_papers]
    lines.append("\nHere's the plan:")
    if covered:
        lines.append(f"1. Send *PREP* for real past-paper questions on {', '.join(covered)}, "
                     "marked against the memo.")
    else:
        lines.append("1. Send *PREP* for real past-paper questions on your grade's topics, marked "
                     "against the memo.")
    lines.append("2. Stuck on one? Reply HELP and we'll work it through step by step.")
    lines.append("3. Say \"quiz me\" for quick practice questions.")
    if due and (due - today).days >= 3:
        lines.append("\nA little every day beats one long night before 💪")
    return "\n".join(lines)


def atp_suggestion(rows: list[dict], day: datetime.date) -> dict | None:
    """From this grade's atp_topic_schedule rows: what the ATP says now.
    {"kind": "exam"|"revision"|"topic", "topics": [...], "term", "week"}"""
    tw = term_week(day)
    if not tw:
        return None
    term, week = tw
    now = [r for r in rows if r["term"] == term and r["week_start"] <= week <= r["week_end"]]
    if any(r["kind"] == "exam" for r in now):
        return {"kind": "exam", "topics": [], "term": term, "week": week}
    # a topic block that ended this week or last week: its test is likely now
    just_done = [r for r in rows if r["term"] == term and r["kind"] == "topic"
                 and week - 1 <= r["week_end"] <= week]
    if just_done:
        names = list(dict.fromkeys(r["topic"] or r["label"] for r in just_done))
        return {"kind": "topic", "topics": names, "term": term, "week": week}
    if any(r["kind"] == "revision" for r in now):
        return {"kind": "revision", "topics": [], "term": term, "week": week}
    return None


# ── Database side ────────────────────────────────────────────────────────────

async def save(conn, learner_id: int, due: datetime.date | None, topics: list[str], note: str) -> None:
    await conn.execute(
        "INSERT INTO learner_tests (learner_id, due_on, topics, note, source) "
        "VALUES ($1, $2, $3::jsonb, $4, 'learner')", learner_id, due,
        __import__("json").dumps(topics), note[:300])


async def upcoming(conn, learner_id: int, today: datetime.date) -> dict | None:
    row = await conn.fetchrow(
        "SELECT due_on, topics FROM learner_tests WHERE learner_id = $1 "
        "AND (due_on IS NULL OR due_on >= $2) ORDER BY created_at DESC LIMIT 1", learner_id, today)
    if not row:
        return None
    return {"due": row["due_on"], "topics": __import__("json").loads(row["topics"])}


async def atp_rows(conn, grade: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT a.term, a.week_start, a.week_end, a.kind, a.label, t.name AS topic
        FROM atp_topic_schedule a JOIN grades g ON g.id = a.grade_id
        LEFT JOIN topics t ON t.id = a.topic_id
        WHERE g.grade_number = $1
        """, grade)
    return [dict(r) for r in rows]
