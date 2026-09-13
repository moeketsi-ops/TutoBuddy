"""Eval harness (blueprint §4.2: golden set graded vs NSC-style memos; run on
every prompt/model/corpus change and publish the number).

    docker compose run --rm evals

POC grading is keyword-based against memo answers — honest but crude. The
production harness grades against full official NSC marking memos with an
LLM judge. Scores are only meaningful with a real LLM: LLM_PROVIDER set to
anthropic, groq, or ollama (with the matching key/host configured) — see
.env.example.
"""

import asyncio
import json
import re
import unicodedata
from pathlib import Path

from app.adapters import llm
from app.config import settings
from app.tutor.engine import eval_answer
from app.tutor.prompts import PROMPT_VERSION

GOLDEN = Path(__file__).parent / "golden.json"


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("−", "-").replace("–", "-").replace("×", "x")
    return re.sub(r"\s+", " ", text.lower())


def keyword_score(answer: str, keywords: list[str]) -> float:
    answer_n = _normalise(answer)
    hits = sum(1 for kw in keywords if _normalise(kw) in answer_n)
    return hits / len(keywords) if keywords else 0.0


async def main() -> None:
    golden = json.loads(GOLDEN.read_text())
    stub_mode = llm.using_stub()

    print(f"Katlego eval harness · prompt policy {PROMPT_VERSION} · "
          f"LLM={'stub' if stub_mode else settings.llm_provider} · {len(golden)} golden questions\n")
    if stub_mode:
        print("⚠️  STUB MODE — the stub LLM cannot solve maths, so scores below are")
        print("   expected to be ~0 and are NOT meaningful. Set LLM_PROVIDER to anthropic, ")
        print("   groq, or ollama (with its key/host configured) in .env for a real number.\n")

    passed = 0
    for i, item in enumerate(golden, 1):
        answer = await eval_answer(item["question"], item["grade"])
        score = keyword_score(answer, item["memo_keywords"])
        ok = score >= 0.6
        passed += ok
        print(f"  Q{i:02d} [{'PASS' if ok else 'FAIL'}] score={score:.0%}  {item['question'][:64]}")

    accuracy = passed / len(golden)
    print(f"\nResult: {passed}/{len(golden)} passed · accuracy {accuracy:.0%}")
    if stub_mode:
        print("(stub mode — not a real measurement)")


if __name__ == "__main__":
    asyncio.run(main())
