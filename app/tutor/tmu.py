"""Teaching Mathematics for Understanding (TMU): the DBE framework's four
strands, and a small library of alternative solution methods per topic.

Source: DBE "Mathematics Teaching and Learning Framework for South Africa:
Teaching Mathematics for Understanding" (draft 6). Its dimensions are
conceptual understanding, procedural fluency, strategic competence and
reasoning, plus a learning-centred classroom (pp. 9-10). The fifth is how
Katlego behaves (patience, wait time, inviting the learner's own method),
so it is a design rule, not a score.

Mastery evidence gets a strand tag in code (strand_for), so a learner's
profile can show "fluent at the steps, not yet able to justify" per
objective. The method library (seed/tmu/methods.json) feeds the
MULTIPLE_METHODS strategy and the misconception hints; mastery accepts any
valid method (design note section 8)."""

from __future__ import annotations

import functools
import json
from pathlib import Path

STRANDS = ("conceptual_understanding", "procedural_fluency", "strategic_competence", "reasoning")

STRAND_LABELS = {"conceptual_understanding": "Conceptual understanding",
                 "procedural_fluency": "Procedural fluency",
                 "strategic_competence": "Strategic competence",
                 "reasoning": "Reasoning"}

# What each strategy mainly exercises when it works.
STRATEGY_STRAND = {
    "PRIOR_KNOWLEDGE_ACTIVATION": "conceptual_understanding",
    "SOCRATIC_QUESTIONING": "procedural_fluency",
    "SCAFFOLDED_EXAMPLE": "procedural_fluency",
    "WORKED_EXAMPLE": "procedural_fluency",
    "VISUAL_MODEL": "conceptual_understanding",
    "ANALOGY": "conceptual_understanding",
    "MISCONCEPTION_REMEDIATION": "conceptual_understanding",
    "RETRIEVAL_PRACTICE": "procedural_fluency",
    "MULTIPLE_METHODS": "strategic_competence",
    "WHEN_TO_USE": "procedural_fluency",
    "CONNECT_REPRESENTATIONS": "conceptual_understanding",
    "JUSTIFY_AND_CHECK": "reasoning",
}

METHODS_PATH = Path(__file__).resolve().parents[2] / "seed" / "tmu" / "methods.json"


def strand_for(strategy: str | None, evidence: str, level: str | None) -> str | None:
    """Which strand a piece of evidence speaks to (None = no evidence).
    Explaining back is conceptual; success below the abstract level is
    conceptual (they understood the idea, not yet the symbols); otherwise
    the strand of the strategy that prompted it."""
    if evidence in (None, "none", "asked_for_answer"):
        return None
    if evidence == "explained_back":
        return "conceptual_understanding"
    if level in ("concrete", "pictorial"):
        return "conceptual_understanding"
    return STRATEGY_STRAND.get(strategy or "", "procedural_fluency")


@functools.lru_cache(maxsize=1)
def library() -> list[dict]:
    try:
        return json.loads(METHODS_PATH.read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError):
        return []


def find_methods(text: str, grade: int, topic: str | None = None) -> dict | None:
    """The best library entry for this problem and grade, or None.
    Keyword hits (weighted by length) on the problem text and topic name; an entry outside the
    learner's grade is never offered (grade rule)."""
    hay = f"{topic or ''} {text or ''}".lower()
    best, score = None, 0
    for e in library():
        if grade not in e.get("grades", []):
            continue
        # longer keywords are more specific: "complete the square" beats "x^"
        hits = sum(len(k) for k in e.get("keywords", []) if k.lower() in hay)
        if hits > score:
            best, score = e, hits
    return best


def methods_line(entry: dict | None, limit: int = 4) -> str | None:
    if not entry:
        return None
    ms = "; ".join(f"({i + 1}) {m}" for i, m in enumerate(entry["methods"][:limit]))
    line = f"METHODS for this problem (any valid method counts): {ms}"
    if entry.get("misconceptions"):
        line += "\nWATCH FOR: " + "; ".join(entry["misconceptions"][:2])
    return line


# ── Database side: the strand profile for reports ───────────────────────────

async def strand_profile(conn, learner_id: int, topic_id: int | None = None) -> dict[str, dict]:
    """Per strand: evidence count and share of successful evidence, from
    learner_events (mastery's raw evidence log)."""
    rows = await conn.fetch(
        """
        SELECT strand, count(*) AS n,
               count(*) FILTER (WHERE evidence IN ('attempt_correct', 'explained_back')) AS ok
        FROM learner_events
        WHERE learner_id = $1 AND strand IS NOT NULL AND ($2::int IS NULL OR topic_id = $2)
        GROUP BY strand
        """, learner_id, topic_id)
    out = {s: {"evidence": 0, "success_share": None} for s in STRANDS}
    for r in rows:
        if r["strand"] in out:
            out[r["strand"]] = {"evidence": r["n"], "success_share": round(r["ok"] / r["n"], 2)}
    return out
