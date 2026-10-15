"""Evidence-weighted mastery per learning objective.

Every piece of evidence (a quiz answer, a chat step judged in the STATE
line, an explain-back) pulls the LO score toward a target by a step sized
by how strong that evidence is:

    m_new = m_old + w * (t - m_old)

t = 100 correct / 60 partial / 10 wrong; w from EVIDENCE_RULES below. Scores
stay in [0, 100] by construction, one lucky answer can't jump a learner a
band, and hints reduce credit without removing it. This replaces the flat
+12 / +4 / -6 quiz deltas (rag.MASTERY_DELTA) and lets homework chats count.

LO scores roll up to learner_topic_mastery (mean of the topic's LOs that
have evidence), so PROGRESS and quiz topic-picking keep working unchanged.

All weights are starting values to calibrate against real attempt data;
learner_events keeps the raw evidence so history can be replayed with a
new formula.
"""

import datetime
import re

MASTERY_START = 50.0  # same neutral start as before ("practice" band)

# evidence -> (target, weight). Chat weights are lower than quiz weights:
# the model judged the step inside a conversation, not against a checked
# answer.
EVIDENCE_RULES: dict[tuple[str, str], tuple[float, float]] = {
    ("quiz", "attempt_correct"): (100.0, 0.25),
    ("quiz", "attempt_partial"): (60.0, 0.25),
    ("quiz", "attempt_wrong"): (10.0, 0.25),
    ("chat", "explained_back"): (100.0, 0.20),
    ("chat", "attempt_correct"): (100.0, 0.15),
    ("chat", "attempt_partial"): (60.0, 0.10),
    ("chat", "attempt_wrong"): (10.0, 0.10),
    # Kept small on purpose: asking for help must never be punished.
    ("chat", "asked_for_answer"): (30.0, 0.05),
}
# Photos are judged the same way as chat steps.
for (_src, _ev), _rule in list(EVIDENCE_RULES.items()):
    if _src == "chat":
        EVIDENCE_RULES[("photo", _ev)] = _rule

QUIZ_EVIDENCE = {"correct": "attempt_correct", "partial": "attempt_partial",
                 "incorrect": "attempt_wrong"}

REVIEW_DAYS = {"remediate": 1, "practice": 3, "challenge": 7, "advance": 14}


def band(score: float) -> str:
    """Same thresholds as learner_topic_mastery.band (locked: <40/<70/<85)."""
    if score < 40:
        return "remediate"
    if score < 70:
        return "practice"
    if score < 85:
        return "challenge"
    return "advance"


def evidence_weight(source: str, evidence: str, hint_level: int = 0) -> tuple[float, float] | None:
    """(target, weight) for one event, or None if it carries no evidence.
    A correct chat step after hint level h earns w * (1 - 0.25h)."""
    rule = EVIDENCE_RULES.get((source, evidence))
    if rule is None:
        return None
    target, w = rule
    if evidence == "attempt_correct" and source != "quiz":
        w = w * (1 - 0.25 * max(0, min(3, hint_level)))
    return target, round(w, 3)


def update(score: float, target: float, weight: float) -> float:
    return round(score + weight * (target - score), 2)


def next_review(score: float, now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now + datetime.timedelta(days=REVIEW_DAYS[band(score)])


# ── Database side ────────────────────────────────────────────────────────────

PLACEHOLDER_SQL = """
INSERT INTO learning_objectives
    (objective_code, grade_id, subject_id, topic_id, objective, term, is_placeholder)
SELECT 'TOPIC-' || t.id || '.00', t.grade_id, t.subject_id, t.id,
       'Overall understanding of ' || t.name, t.term, true
FROM topics t
WHERE NOT EXISTS (SELECT 1 FROM learning_objectives lo WHERE lo.topic_id = t.id)
ON CONFLICT (objective_code) DO NOTHING
"""


async def ensure_placeholder_los(conn) -> None:
    """Idempotent: every topic without a real LO gets one placeholder LO."""
    await conn.execute(PLACEHOLDER_SQL)


async def lo_candidates(conn, topic_id: int, limit: int = 6, *, query: str | None = None,
                        keep_code: str | None = None) -> list[dict]:
    """The LOs the tutor may name in this turn's state: the topic's real
    LOs when it has any, else its placeholder. A topic can have 20+ CAPS
    objectives, so only the `limit` best word-overlap matches with `query`
    are sent (plus the LO already in play, `keep_code`), costing ~10 tokens
    each. No embeddings needed."""
    rows = await conn.fetch(
        """
        SELECT id, objective_code AS code, objective, is_placeholder
        FROM learning_objectives
        WHERE topic_id = $1
        ORDER BY is_placeholder, objective_code
        """,
        topic_id,
    )
    real = [dict(r) for r in rows if not r["is_placeholder"]]
    chosen = real or [dict(r) for r in rows]
    if not chosen:
        await ensure_placeholder_los(conn)
        return await lo_candidates(conn, topic_id, limit, query=query, keep_code=keep_code)
    if query and len(chosen) > limit:
        qw = _words(query)
        chosen = sorted(chosen, key=lambda lo: (-len(qw & _words(lo["objective"])), lo["code"]))
    top = chosen[:limit]
    if keep_code and keep_code not in {lo["code"] for lo in top}:
        kept = next((lo for lo in chosen if lo["code"] == keep_code), None)
        if kept:
            top = top[:limit - 1] + [kept]
    return top


def _words(text: str) -> set[str]:
    stop = {"and", "the", "of", "in", "a", "an", "to", "with", "for", "their"}
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in stop}


async def resolve_topic(conn, grade: int, chunk_topics: list[str],
                        fallback_topic_id: int | None = None) -> dict | None:
    """Map the retrieved CAPS notes to a curriculum topic in the learner's
    OWN grade (grade rule). Exact name first, then the best word overlap,
    then the topic already in working memory. caps_chunks.topic is free
    text, so this is deliberately conservative: no match means no evidence
    recorded, never evidence on the wrong topic."""
    rows = await conn.fetch(
        """
        SELECT t.id, t.name FROM topics t
        JOIN grades g ON g.id = t.grade_id JOIN subjects s ON s.id = t.subject_id
        WHERE g.grade_number = $1 AND lower(s.name) = 'mathematics'
        """,
        grade,
    )
    by_name = {r["name"].lower(): dict(r) for r in rows}
    for name in chunk_topics:
        if name and name.lower() in by_name:
            return by_name[name.lower()]
    best, best_score = None, 0.0
    for name in chunk_topics[:1]:  # only the closest note decides
        cw = _words(name or "")
        for r in rows:
            tw = _words(r["name"])
            if cw and tw:
                score = len(cw & tw) / len(cw | tw)
                if score > best_score:
                    best, best_score = dict(r), score
    if best and best_score >= 0.34:
        return best
    if fallback_topic_id:
        for r in rows:
            if r["id"] == fallback_topic_id:
                return dict(r)
    return None


async def record_event(
    conn,
    learner_id: int,
    topic_id: int,
    *,
    source: str,
    evidence: str,
    lo_id: int | None = None,
    hint_level: int = 0,
    strategy: str | None = None,
    misconception: str | None = None,
) -> dict | None:
    """Write one evidence event, move LO mastery, roll up topic mastery.
    Returns {"lo_id", "before", "after", "topic_score"} or None when the
    event carries no evidence. Must run inside the caller's transaction.

    Grade rule: refuses (ValueError) a topic outside the learner's grade."""
    rule = evidence_weight(source, evidence, hint_level)
    if rule is None:
        return None
    target, weight = rule

    same_grade = await conn.fetchval(
        "SELECT g.grade_number = l.grade FROM topics t "
        "JOIN grades g ON g.id = t.grade_id, learners l "
        "WHERE t.id = $1 AND l.id = $2",
        topic_id, learner_id,
    )
    if not same_grade:
        raise ValueError(f"grade rule: topic {topic_id} is not in learner {learner_id}'s grade")

    if lo_id is None:
        cands = await lo_candidates(conn, topic_id)
        lo_id = cands[0]["id"]

    before = await conn.fetchval(
        "SELECT mastery_score FROM learner_lo_mastery WHERE learner_id = $1 AND lo_id = $2",
        learner_id, lo_id,
    )
    if before is None:
        # First evidence on this LO: start from the learner's existing topic
        # score (earlier quiz history) rather than resetting them to 50.
        before = await conn.fetchval(
            "SELECT mastery_score FROM learner_topic_mastery WHERE learner_id = $1 AND topic_id = $2",
            learner_id, topic_id)
    before = float(before) if before is not None else MASTERY_START
    after = update(before, target, weight)

    await conn.execute(
        """
        INSERT INTO learner_lo_mastery
            (learner_id, lo_id, mastery_score, evidence_count, last_seen_at, next_review_at)
        VALUES ($1, $2, $3, 1, now(), $4)
        ON CONFLICT (learner_id, lo_id) DO UPDATE
            SET mastery_score = EXCLUDED.mastery_score,
                evidence_count = learner_lo_mastery.evidence_count + 1,
                last_seen_at = now(),
                next_review_at = EXCLUDED.next_review_at
        """,
        learner_id, lo_id, after, next_review(after),
    )
    await conn.execute(
        """
        INSERT INTO learner_events
            (learner_id, topic_id, lo_id, source, evidence, hint_level, strategy,
             misconception_code, weight, mastery_before, mastery_after)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        learner_id, topic_id, lo_id, source, evidence, hint_level, strategy,
        misconception, weight, before, after,
    )
    topic_score = await conn.fetchval(
        """
        SELECT round(avg(m.mastery_score), 2)
        FROM learner_lo_mastery m JOIN learning_objectives lo ON lo.id = m.lo_id
        WHERE m.learner_id = $1 AND lo.topic_id = $2
        """,
        learner_id, topic_id,
    )
    await conn.execute(
        """
        INSERT INTO learner_topic_mastery (learner_id, topic_id, mastery_score)
        VALUES ($1, $2, $3)
        ON CONFLICT (learner_id, topic_id) DO UPDATE
            SET mastery_score = EXCLUDED.mastery_score, last_assessed_at = now()
        """,
        learner_id, topic_id, topic_score,
    )
    return {"lo_id": lo_id, "before": before, "after": after,
            "topic_score": float(topic_score)}


async def misconception_codes(conn, topic_id: int | None) -> list[dict]:
    rows = await conn.fetch(
        "SELECT code, description FROM misconceptions "
        "WHERE topic_id IS NULL OR topic_id = $1 ORDER BY code",
        topic_id,
    )
    return [dict(r) for r in rows]


# ── Scoring: objectives -> topic -> term/subject ─────────────────────────────
# Two numbers, never blended (spec v0.1): COVERAGE = share of a topic's CAPS
# objectives with any evidence; UNDERSTANDING = mean mastery over the covered
# ones. Topics are weighted by their CAPS teaching hours in the term
# (topics.term_hours), so a 9-hour topic counts three times a 3-hour one:
# CAPS hours are CAPS's own statement of emphasis.

async def objective_progress(conn, learner_id: int, topic_ids: list[int], term: int | None) -> dict:
    """{"topics": {topic_id: {"covered", "total", "understanding"}},
        "covered", "total", "coverage_pct", "understanding"} for the given
    topics. Placeholder LOs count only for topics with no real LO."""
    if not topic_ids:
        return {"topics": {}, "covered": 0, "total": 0, "coverage_pct": 0, "understanding": None}
    rows = await conn.fetch(
        """
        WITH real AS (SELECT DISTINCT topic_id FROM learning_objectives
                      WHERE NOT is_placeholder AND topic_id = ANY($2::int[]))
        SELECT lo.topic_id, t.term_hours, t.duration_hours, m.mastery_score
        FROM learning_objectives lo
        JOIN topics t ON t.id = lo.topic_id
        LEFT JOIN learner_lo_mastery m ON m.lo_id = lo.id AND m.learner_id = $1
        WHERE lo.topic_id = ANY($2::int[])
          AND (NOT lo.is_placeholder OR lo.topic_id NOT IN (SELECT topic_id FROM real))
        """,
        learner_id, topic_ids,
    )
    per: dict[int, dict] = {}
    for r in rows:
        t = per.setdefault(r["topic_id"], {"scores": [], "total": 0, "weight": 1.0})
        t["total"] += 1
        if r["mastery_score"] is not None:
            t["scores"].append(float(r["mastery_score"]))
        hours = r["term_hours"]
        if isinstance(hours, str):
            import json as _json
            hours = _json.loads(hours)
        if term is not None and hours and str(term) in hours:
            t["weight"] = float(hours[str(term)])
        elif r["duration_hours"]:
            t["weight"] = float(r["duration_hours"])
    out, wsum, wcov, wund, wund_sum = {}, 0.0, 0.0, 0.0, 0.0
    covered = total = 0
    for tid, t in per.items():
        cov = len(t["scores"])
        und = round(sum(t["scores"]) / cov, 1) if cov else None
        out[tid] = {"covered": cov, "total": t["total"], "understanding": und}
        covered += cov
        total += t["total"]
        wsum += t["weight"]
        wcov += t["weight"] * cov / t["total"]
        if und is not None:
            wund += t["weight"] * und
            wund_sum += t["weight"]
    return {
        "topics": out,
        "covered": covered,
        "total": total,
        "coverage_pct": round(100 * wcov / wsum) if wsum else 0,
        "understanding": round(wund / wund_sum, 1) if wund_sum else None,
    }
