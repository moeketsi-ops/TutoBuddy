"""Production token, latency and cost ledger (table llm_calls).

The bench (evals/bench) captures per-call telemetry in memory with
llm.capture_calls(); this module persists the SAME telemetry fields for live
traffic, one row per model call, so production cost per learner and the
bake-off numbers come from one definition.

- Real calls: fields from llm._emit (served model, input/output/reasoning
  tokens, OpenRouter's billed `cost`, latency, stop reason, host).
- Stub calls: estimates (characters / 4, estimated=true) so prompt sizes can
  be compared offline.
- cost_usd = the billed amount when the provider returns one (OpenRouter
  usage.cost), else tokens x PRICES below (billed=false).
- The engine adds what only it knows: which learner, which teaching
  strategy, and whether the reply's STATE line parsed.

A ledger failure is logged and swallowed: bookkeeping never breaks a reply.
"""

import contextvars
import logging

log = logging.getLogger("katlego.ledger")

# USD per million tokens (input, output). Fallback only: OpenRouter bills
# per call and that figure wins. Checked Oct 2026: qwen3.5-35b-a3b via the
# pricepertoken.com OpenRouter listing (13 Oct 2026); Groq and Anthropic as
# in the project's LLM cost blueprint (2 Sep 2026). `python -m
# evals.bench.prices` prints live OpenRouter prices.
PRICES: dict[str, tuple[float, float]] = {
    "qwen/qwen3.5-35b-a3b": (0.08, 0.75),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (2.00, 10.00),
}

# Set by the engine for one learner's turn, so adapter code doesn't need
# learner ids threaded through every call.
current_learner: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_learner", default=None)
current_strategy: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_strategy", default=None)
# Id of the most recent llm_calls row in this context, so the engine can
# mark whether that reply's STATE line parsed.
last_call_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "last_call_id", default=None)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def priced_cost(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    price = PRICES.get(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


async def persist(fields: dict) -> int | None:
    """Write one telemetry dict (llm._emit / llm._log_stub shape) to
    llm_calls. Returns the row id, also kept in last_call_id."""
    from app.db import get_pool
    from app.tutor.prompts import PROMPT_VERSION

    model = fields.get("served_model") or fields.get("requested_model") or "unknown"
    inp, out = fields.get("input_tokens"), fields.get("output_tokens")
    billed = fields.get("cost_usd")
    cost = billed if billed is not None else priced_cost(fields.get("requested_model", model), inp, out)
    latency = fields.get("latency_s")
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row_id = await conn.fetchval(
                """
                INSERT INTO llm_calls (learner_id, call, provider, model, prompt_version,
                    prompt_tokens, completion_tokens, reasoning_tokens, estimated,
                    latency_ms, cost_usd, billed, finish_reason, host, strategy)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                RETURNING id
                """,
                current_learner.get(), fields.get("call", "?"), fields.get("provider", "?"),
                str(model)[:80], PROMPT_VERSION, inp, out, fields.get("reasoning_tokens"),
                bool(fields.get("estimated")),
                int(latency * 1000) if latency is not None else None,
                cost, billed is not None, fields.get("finish_reason"),
                (str(fields["host"])[:40] if fields.get("host") else None),
                current_strategy.get(),
            )
    except Exception:  # noqa: BLE001 -- never break a reply over bookkeeping
        log.exception("ledger: could not record %s call", fields.get("call"))
        row_id = None
    last_call_id.set(row_id)
    return row_id


async def mark_state(call_id: int | None, valid: bool, mode: str | None = None) -> None:
    """Record whether that reply's state parsed, and how it came back
    (json / json_prompt / state_line / json_failed:...)."""
    if call_id is None:
        return
    from app.db import get_pool

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE llm_calls SET state_valid = $2, output_mode = $3 WHERE id = $1",
                               call_id, valid, mode)
    except Exception:  # noqa: BLE001
        log.exception("ledger: could not mark state for call %s", call_id)
