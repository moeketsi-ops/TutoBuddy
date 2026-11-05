"""Shared pieces for the journey and homework-week runs: a simulated phone
on the real WhatsApp path (gateway -> worker -> mock Cloud API), time
travel between "days", and snapshots of what the database says about a
learner.

Run inside the evals container so the gateway, mock WhatsApp, Postgres and
Redis are all reachable:

    docker compose run --rm -e GATEWAY_URL=http://gateway:8000 \\
        -e MOCKWA_URL=http://mockwa:8001 evals python -m evals.journey.full
"""

from __future__ import annotations

import datetime
import json
import os
import time
import uuid

import httpx

GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:8000").rstrip("/")
MOCKWA = os.environ.get("MOCKWA_URL", "http://mockwa:8001").rstrip("/")
REPLY_TIMEOUT = float(os.environ.get("JOURNEY_REPLY_TIMEOUT") or 120)


class Phone:
    """One learner's phone. send() posts a Meta-format webhook; reply()
    waits for Katlego's next message in the mock Cloud API outbox."""

    def __init__(self, phone: str | None = None):
        self.number = phone or "2782" + str(uuid.uuid4().int % 10**7).zfill(7)
        self.cursor = 0
        self.http = httpx.Client(timeout=30)
        self.log: list[tuple[str, str]] = []   # (who, text)

    def send(self, text: str) -> None:
        msg = {"from": self.number, "id": f"wamid.journey.{uuid.uuid4().hex}",
               "timestamp": str(int(time.time())), "type": "text", "text": {"body": text}}
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "0", "changes": [{
            "field": "messages", "value": {
                "messaging_product": "whatsapp", "metadata": {"phone_number_id": "000000000000000"},
                "contacts": [{"wa_id": self.number, "profile": {"name": "Journey"}}],
                "messages": [msg]}}]}]}
        r = self.http.post(f"{GATEWAY}/webhook", json=payload)
        r.raise_for_status()
        self.log.append(("learner", text))

    def reply(self, timeout: float | None = None) -> str:
        deadline = time.time() + (timeout or REPLY_TIMEOUT)
        while time.time() < deadline:
            data = self.http.get(f"{MOCKWA}/outbox", params={"to": self.number, "since": self.cursor}).json()
            self.cursor = data["next"]
            if data["messages"]:
                body = data["messages"][0]["body"]
                self.log.append(("katlego", body))
                return body
            time.sleep(0.4)
        raise TimeoutError(f"no reply within {timeout or REPLY_TIMEOUT}s")

    def say(self, text: str) -> str:
        self.send(text)
        return self.reply()

    def transcript(self) -> str:
        return "\n\n".join(f"{'L' if who == 'learner' else 'K'}: {t}" for who, t in self.log)


# ── Database and Redis ──────────────────────────────────────────────────────

async def learner_id(conn, phone: Phone, nickname: str | None = None) -> int | None:
    return await conn.fetchval(
        """
        SELECT l.id FROM learners l JOIN account_channels c ON c.account_id = l.account_id
        WHERE c.phone = $1 AND ($2::text IS NULL OR l.nickname = $2) ORDER BY l.id DESC LIMIT 1
        """, phone.number, nickname)


SHIFT = (
    ("conversation_log", ("created_at",)), ("diagnostic_results", ("started_at", "finished_at")),
    ("learner_events", ("created_at",)), ("learner_lo_mastery", ("last_seen_at", "next_review_at")),
    ("learner_practice_attempts", ("created_at",)), ("learner_tests", ("created_at",)),
    ("learner_topic_mastery", ("last_assessed_at",)), ("llm_calls", ("created_at",)),
    ("paper_attempts", ("finished_at",)), ("pedagogy_decisions", ("created_at",)),
)


async def time_travel(conn, learner: int, days: float = 1.0) -> None:
    """Make it `days` later for this learner: every timestamp of theirs
    moves back, and their working memory looks idle, so the next message
    starts a new session (and reviews fall due) exactly as on a real
    next day."""
    from app.queue import get_redis
    from app.tutor import memory

    iv = datetime.timedelta(days=days)
    for table, cols in SHIFT:
        sets = ", ".join(f"{c} = {c} - $2::interval" for c in cols)
        await conn.execute(f"UPDATE {table} SET {sets} WHERE learner_id = $1", learner, iv)
    r = get_redis()
    raw = await r.get(memory.key(learner))
    if raw:
        mem = json.loads(raw)
        sec = days * 86400
        for k in ("session_started", "last_turn_at"):
            if mem.get(k):
                mem[k] -= sec
        for t in mem.get("turns", []):
            t["at"] -= sec
        await r.set(memory.key(learner), json.dumps(mem), ex=memory.TTL_SECONDS)


async def working_memory(learner: int) -> dict | None:
    from app.queue import get_redis
    from app.tutor import memory

    raw = await get_redis().get(memory.key(learner))
    return json.loads(raw) if raw else None


async def snapshot(conn, learner: int, topics: list[str], since=None) -> dict:
    """What the database says now: topic mastery, objectives, today's
    evidence, strategies, switches, reviews, tokens and cost."""
    rows = await conn.fetch(
        """
        SELECT t.name, m.mastery_score FROM learner_topic_mastery m JOIN topics t ON t.id = m.topic_id
        WHERE m.learner_id = $1
        """, learner)
    topic_scores = {r["name"]: float(r["mastery_score"]) for r in rows}
    los = await conn.fetch(
        """
        SELECT t.name, count(*) AS n, avg(m.mastery_score) AS mean,
               sum((m.next_review_at < now())::int) AS due
        FROM learner_lo_mastery m JOIN learning_objectives lo ON lo.id = m.lo_id
        JOIN topics t ON t.id = lo.topic_id WHERE m.learner_id = $1 GROUP BY t.name
        """, learner)
    lo = {r["name"]: {"covered": r["n"], "mean": float(r["mean"]), "due": r["due"]} for r in los}
    since_sql = "AND created_at >= $2" if since else ""
    args = [learner] + ([since] if since else [])
    ev = await conn.fetch(
        f"SELECT source, evidence, count(*) AS n FROM learner_events WHERE learner_id = $1 {since_sql} "
        "GROUP BY 1, 2", *args)
    calls = await conn.fetchrow(
        f"""
        SELECT count(*) AS n, coalesce(sum(prompt_tokens), 0) AS tin, coalesce(sum(completion_tokens), 0) AS tout,
               coalesce(sum(reasoning_tokens), 0) AS treason, coalesce(sum(cost_usd), 0)::float AS cost,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS lat,
               sum((finish_reason IN ('error', 'length'))::int) AS errors
        FROM llm_calls WHERE learner_id = $1 {since_sql}
        """, *args)
    strategies = await conn.fetch(
        f"SELECT strategy, count(*) AS n FROM llm_calls WHERE learner_id = $1 AND call = 'socratic_reply' "
        f"AND strategy IS NOT NULL {since_sql} GROUP BY 1 ORDER BY 2 DESC", *args)
    switches = await conn.fetch(
        f"SELECT switch, outcome, count(*) AS n FROM pedagogy_decisions WHERE learner_id = $1 {since_sql} "
        "GROUP BY 1, 2", *args)
    return {
        "topics": {t: topic_scores.get(t) for t in topics} | {k: v for k, v in topic_scores.items() if k not in topics},
        "objectives": lo,
        "evidence": {f"{r['source']}:{r['evidence']}": r["n"] for r in ev},
        "calls": dict(calls),
        "strategies": {r["strategy"]: r["n"] for r in strategies},
        "switches": [(r["switch"], r["outcome"], r["n"]) for r in switches],
    }
