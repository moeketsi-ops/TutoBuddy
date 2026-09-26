"""Router bake-off: which intent classifier should sit in front of the tutor?

    docker compose run --rm evals python -m evals.router_eval

Runs every available router against evals/router_golden.json (labelled
learner messages: SA English, code-switched isiZulu/Sepedi, typos, WhatsApp
shorthand) and reports accuracy, per-intent recall, latency, and cost. The
"industry" comparison is the measured number, not vendor claims: a small
LLM as router (what most agent stacks do, incl. this codebase's default)
vs Jev's typed-decision approach.

  stub — always runs (keyword heuristic, free, ~0 ms) — the floor.
  llm  — whatever LLM_PROVIDER is configured (skipped in stub mode).
  jev  — if TYPESAFE_API_KEY is set (ROUTER_PROVIDER need not be "jev"
         here — the harness calls Jev directly to measure it).

Jev also gets an accuracy-by-confidence table: that is the calibration
claim to check, and it tells you where to set JEV_MIN_CONFIDENCE.
"""

import asyncio
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from app.adapters import llm, router
from app.config import settings

GOLDEN = Path(__file__).parent / "router_golden.json"
JEV_USD_PER_M_INPUT = 0.042


def _stub_classify(text: str) -> str:
    lowered = text.lower().strip()
    if lowered in llm._SMALLTALK_WORDS:
        return "smalltalk"
    if any(w in lowered for w in ("quiz", "practice", "test me")):
        return "quiz"
    if any(h in lowered for h in llm._HOMEWORK_HINTS):
        return "homework"
    return "smalltalk" if len(lowered.split()) <= 3 else "homework"


async def _run(name, items, classify):
    preds, lat, extras = [], [], []
    for item in items:
        t0 = time.perf_counter()
        try:
            out = await classify(item["text"])
        except Exception as exc:  # a failing provider still gets reported, not hidden
            out = f"ERROR:{type(exc).__name__}"
        lat.append((time.perf_counter() - t0) * 1000)
        if isinstance(out, dict):
            extras.append(out)
            out = out.get("label")
        preds.append(out)
    return preds, lat, extras


def _report(name, items, preds, lat, extras=None):
    n = len(items)
    correct = [p == i["intent"] for p, i in zip(preds, items)]
    acc = sum(correct) / n
    recall = defaultdict(lambda: [0, 0])
    for p, i in zip(preds, items):
        recall[i["intent"]][1] += 1
        recall[i["intent"]][0] += p == i["intent"]
    conf = Counter((i["intent"], p) for p, i in zip(preds, items) if p != i["intent"])
    print(f"\n── {name} ──────────────────────────────────────────")
    print(f"accuracy {acc:.0%} ({sum(correct)}/{n})   latency p50 {statistics.median(lat):.0f} ms · "
          f"p95 {sorted(lat)[int(0.95 * (n - 1))]:.0f} ms")
    print("recall  " + "  ".join(f"{k}: {v[0]}/{v[1]}" for k, v in sorted(recall.items())))
    if conf:
        print("misses  " + ", ".join(f"{a}→{b} ×{c}" for (a, b), c in conf.most_common(6)))
    if extras:
        buckets = defaultdict(lambda: [0, 0])
        tokens = 0
        for e, ok in zip(extras, correct):
            b = min(int(e.get("confidence", 0) * 10) / 10, 0.9)
            buckets[b][1] += 1
            buckets[b][0] += ok
            tokens += e.get("input_tokens", 0)
        print("accuracy by confidence bucket (calibration check): " +
              "  ".join(f"≥{b:.1f}: {v[0]}/{v[1]}" for b, v in sorted(buckets.items())))
        print(f"cost for this run: {tokens} input tokens ≈ ${tokens / 1e6 * JEV_USD_PER_M_INPUT:.5f}")
    return acc


async def main() -> None:
    items = json.loads(GOLDEN.read_text())
    print(f"Katlego router bake-off · {len(items)} labelled messages · "
          f"{Counter(i['intent'] for i in items)}")

    ran = []
    preds, lat, _ = await _run("stub", items, lambda t: asyncio.sleep(0, _stub_classify(t)))
    ran.append(("stub heuristic (free)", _report("stub heuristic (free)", items, preds, lat)))

    if not llm.using_stub():
        name = f"llm router ({settings.llm_provider})"
        preds, lat, _ = await _run(name, items, llm.classify_intent)
        ran.append((name, _report(name, items, preds, lat)))

    if settings.is_set(settings.typesafe_api_key):
        preds, lat, extras = await _run("jev", items, router.jev_classify)
        ran.append((f"jev ({settings.jev_model})", _report(f"jev ({settings.jev_model})", items, preds, lat, extras)))

    print("\nSummary: " + "  |  ".join(f"{n}: {a:.0%}" for n, a in ran))
    if len(ran) == 1:
        print("⚠️  Only the stub ran. Set LLM_PROVIDER (+key) and/or TYPESAFE_API_KEY in .env "
              "to compare a real LLM router and Jev.")


if __name__ == "__main__":
    asyncio.run(main())
