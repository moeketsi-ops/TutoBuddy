"""Check every candidate and judge slug against OpenRouter's public model
list and print live prices. Free: no API key, no model calls.

    python -m evals.bench.prices
"""

import json
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "results" / "prices.json"
MODELS_URL = "https://openrouter.ai/api/v1/models"


def load_candidates() -> dict:
    return tomllib.loads((HERE / "candidates.toml").read_text())


def fetch() -> dict[str, dict]:
    """{slug: {in, out (USD per 1M tokens), context, vision, reasoning}} from OpenRouter."""
    req = urllib.request.Request(MODELS_URL, headers={"User-Agent": "katlego-bench"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)["data"]
    out = {}
    for m in data:
        pricing = m.get("pricing") or {}
        params = m.get("supported_parameters") or []
        out[m["id"]] = {
            "in": float(pricing.get("prompt") or 0) * 1e6,
            "out": float(pricing.get("completion") or 0) * 1e6,
            "context": m.get("context_length"),
            "vision": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
            "reasoning": "reasoning" in params or "reasoning_effort" in params,
        }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=1))
    return out


def cached() -> dict[str, dict]:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def main() -> None:
    cfg = load_candidates()
    live = fetch()
    rows = [(m["slug"], m.get("group", ""), "/".join(m["tiers"]), m.get("route", "openrouter"))
            for m in cfg["model"]]
    rows += [(s, "judge", "judge", "openrouter") for s in cfg["judges"]["models"]]
    print(f"{'slug':34} {'group':7} {'tiers':16} {'$in/M':>7} {'$out/M':>7} {'context':>9}  vision reasoning")
    missing = 0
    for slug, group, tiers, route in rows:
        if route != "openrouter":
            print(f"{slug:34} {group:7} {tiers:16} {'—':>7} {'—':>7} {'—':>9}  (route: {route})")
            continue
        info = live.get(slug)
        if not info:
            missing += 1
            near = [s for s in live if s.split("/")[0] == slug.split("/")[0]
                    and slug.split("/")[-1].split("-")[0] in s][:4]
            print(f"{slug:34} {group:7} {tiers:16}  NOT FOUND on OpenRouter. Similar: {', '.join(near) or 'none'}")
            continue
        print(f"{slug:34} {group:7} {tiers:16} {info['in']:7.3f} {info['out']:7.3f} {info['context'] or 0:9,}"
              f"  {'yes' if info['vision'] else 'no':6} {'yes' if info['reasoning'] else 'no'}")
    print(f"\n{len(rows)} models checked, {missing} not found. Prices cached to {CACHE.relative_to(HERE.parent.parent)}.")


if __name__ == "__main__":
    main()
