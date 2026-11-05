"""What prompt caching saves, from the calls Katlego actually made.

    python -m app.reports.cache_eval                    # last day
    python -m app.reports.cache_eval --days 7 --fx 16.02
    python -m app.reports.cache_eval --read-mult 0.25   # cached tokens billed at 25% of input

In Docker: docker compose run --rm evals python -m app.reports.cache_eval --fx 16.02

For every model call the ledger (llm_calls) records how much of its prompt
matched, from the first character, the same learner's previous prompt for
the same call type within CACHE_TTL_SECONDS (shared_chars / prompt_chars).
That part is what a provider can serve from cache. Providers cache in
128-token steps and only once the matching part is at least 1,024 tokens,
so the estimate does the same.

The report groups calls by prompt layout (PROMPT_LAYOUT: classic or layered)
so two runs of the same week, one per layout, compare directly:
tokens sent, tokens cacheable, and input cost without and with caching.
Real calls also show what the provider says it served from cache
(cached_tokens), which is the number to trust; OpenRouter's billed cost
already includes the discount.

Prices: input/output USD per million tokens from app.adapters.ledger.PRICES
for the model on each row; stub rows (offline runs) are priced as --model.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime

from app.adapters.ledger import PRICES

MIN_CACHE = 1024
STEP = 128


def cacheable(prompt_tokens: int, prompt_chars: int | None, shared_chars: int | None) -> int:
    if not prompt_tokens or not prompt_chars or not shared_chars:
        return 0
    shared = prompt_tokens * shared_chars / prompt_chars
    return int(shared // STEP * STEP) if shared >= MIN_CACHE else 0


def summarise(rows: list[dict], read_mult: float, model: str) -> dict:
    out: dict[tuple, dict] = {}
    for r in rows:
        key = (r["layout"] or "classic", r["call"])
        g = out.setdefault(key, {"calls": 0, "tin": 0, "tout": 0, "cacheable": 0, "cached": 0,
                                 "cost_in": 0.0, "cost_in_cached": 0.0, "cost_out": 0.0, "billed": 0.0})
        price = PRICES.get(r["model"]) or PRICES.get(model) or (0.0, 0.0)
        c = cacheable(r["tin"], r["prompt_chars"], r["shared_chars"])
        # a provider's own figure wins when it reports one
        hit = r["cached"] if r["cached"] else c
        g["calls"] += 1
        g["tin"] += r["tin"]
        g["tout"] += r["tout"]
        g["cacheable"] += c
        g["cached"] += r["cached"]
        g["cost_in"] += r["tin"] * price[0] / 1e6
        g["cost_in_cached"] += ((r["tin"] - hit) + hit * read_mult) * price[0] / 1e6
        g["cost_out"] += r["tout"] * price[1] / 1e6
        g["billed"] += r["cost"] or 0.0
    return out


def report(groups: dict, read_mult: float, fx: float | None, days: float) -> str:
    def money(x):
        return f"${x:.4f}" + (f" (R{x * fx:.2f})" if fx else "")

    lines = [f"# Prompt caching: what it saves (last {days:g} days, cached input billed at {read_mult:g}x)", "",
             "| Layout | Call | Calls | Avg prompt tokens | Cacheable (est.) | Served from cache (provider) | "
             "Input cost, no cache | Input cost, cached | Output cost | Total, cached | Saving |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for (layout, call), g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        total_nc = g["cost_in"] + g["cost_out"]
        total_c = g["cost_in_cached"] + g["cost_out"]
        save = (1 - total_c / total_nc) * 100 if total_nc else 0
        lines.append(
            f"| {layout} | {call} | {g['calls']} | {g['tin'] / g['calls']:.0f} | "
            f"{100 * g['cacheable'] / g['tin'] if g['tin'] else 0:.0f}% | "
            f"{100 * g['cached'] / g['tin'] if g['tin'] else 0:.0f}% | {money(g['cost_in'])} | "
            f"{money(g['cost_in_cached'])} | {money(g['cost_out'])} | {money(total_c)} | {save:.0f}% |")
    tut = {k[0]: v for k, v in groups.items() if k[1] == "socratic_reply"}
    if "classic" in tut and "layered" in tut:
        a, b = tut["classic"], tut["layered"]
        per = lambda g, k: g[k] / g["calls"]  # noqa: E731
        ca = (a["cost_in_cached"] + a["cost_out"]) / a["calls"]
        cb = (b["cost_in_cached"] + b["cost_out"]) / b["calls"]
        lines += ["", "## Tutoring reply, per call: classic vs layered", "",
                  f"- Prompt tokens sent: {per(a, 'tin'):.0f} classic, {per(b, 'tin'):.0f} layered "
                  f"({(per(b, 'tin') / per(a, 'tin') - 1) * 100:+.0f}%: layered sends the whole session as chat).",
                  f"- Of those, cacheable: {per(a, 'cacheable'):.0f} classic, {per(b, 'cacheable'):.0f} layered.",
                  f"- Cost per tutoring reply with caching: {money(ca)} classic, {money(cb)} layered "
                  f"({(cb / ca - 1) * 100:+.0f}%)." if ca else "",
                  f"- Per 1,000 tutoring replies: {money(ca * 1000)} classic, {money(cb * 1000)} layered."]
    lines += ["", "Cacheable = the part of each prompt identical, from the start, to the same learner's previous "
              "prompt within the cache lifetime, counted in 128-token steps from 1,024 tokens. "
              "Real runs: 'served from cache' is the provider's own figure and the one to trust."]
    return "\n".join(l for l in lines if l is not None)


async def main(days: float, read_mult: float, fx: float | None, model: str) -> None:
    from app.db import get_pool

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [dict(r) for r in await conn.fetch(
            """
            SELECT call, model, layout, coalesce(prompt_tokens, 0) AS tin,
                   coalesce(completion_tokens, 0) AS tout, coalesce(cached_tokens, 0) AS cached,
                   prompt_chars, shared_chars, coalesce(cost_usd, 0)::float AS cost
            FROM llm_calls WHERE created_at >= $1 AND prompt_chars IS NOT NULL
            """, since)]
    if not rows:
        print("No calls with prompt accounting yet: run some traffic on this version first.")
        return
    print(report(summarise(rows, read_mult, model), read_mult, fx, days))


def cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=1)
    ap.add_argument("--read-mult", type=float, default=0.25,
                    help="cached input price as a share of normal input (OpenAI 0.1-0.5, Z.AI ~0.2)")
    ap.add_argument("--fx", type=float, default=None, help="rand per dollar")
    ap.add_argument("--model", default="openai/gpt-6-luna", help="price offline (stub) rows as this model")
    a = ap.parse_args()
    asyncio.run(main(a.days, a.read_mult, a.fx, a.model))


if __name__ == "__main__":
    cli()
