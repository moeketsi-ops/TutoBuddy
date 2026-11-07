"""An AI-played learner for the homework week: a cheap model plays a
Grade 8 learner with set misconceptions, through OpenRouter.

How it "learns": each problem type has one misconception. It stays active
until the learner has solved that type of problem twice with Katlego; after
that the persona no longer includes it. So the week shows whether Katlego's
teaching gets the learner to correct answers, and whether the mastery
numbers follow. It is a simulation: a language model pretending to have a
misconception is not a child, and real efficacy is measured in the pilot.

Its calls are billed to OpenRouter like any other, but are NOT written to
llm_calls (they are not Katlego's cost); the week report shows them apart.
"""

from __future__ import annotations

import re

from app.adapters.llm import OPENROUTER_BASE_URL, _usage_dict
from app.config import settings

PERSONA = """You are {name}, a Grade {grade} learner in South Africa, chatting with your maths tutor Katlego on WhatsApp about your homework.

How you write: one short WhatsApp message, informal, sometimes no capital letters, no emojis most of the time. Never more than two sentences. Never explain like a teacher.

What you know right now:
{state}
{traits}
Rules:
- You do not know the answer in advance. Work it out the way a Grade {grade} learner with the mistakes above would.
- If one of your mistakes applies to this problem, make it on your first try.
- When the tutor shows you why a step is wrong, or gives you a smaller step, try that step. Usually you get it, sometimes you need one more hint.
- If the explanation is confusing, say so ("i dont get it").
- When you give an answer, give the number (with units if you remember them).
Reply with only your next message to the tutor."""


class SimLearner:
    def __init__(self, misconceptions: dict[str, str], *, name: str = "Ntando", grade: int = 8,
                 model: str = "openai/gpt-5.4-nano", traits: str = ""):
        self.misc = dict(misconceptions)
        self.traits = traits
        self.solved: dict[str, int] = {}
        self.name, self.grade, self.model = name, grade, model
        self.cost = 0.0
        self.calls = 0
        self.tokens = [0, 0]

    def active(self, ptype: str) -> str | None:
        return self.misc.get(ptype) if self.solved.get(ptype, 0) < 2 else None

    def state(self, ptype: str | None = None) -> str:
        lines = [f"- {m}" for t, m in self.misc.items() if self.solved.get(t, 0) < 2]
        learned = [t for t in self.misc if self.solved.get(t, 0) >= 2]
        if learned:
            lines.append("- You now understand: " + ", ".join(t.replace("_", " ") for t in learned) + ".")
        return "\n".join(lines) or "- You understand these problems well now."

    def record_solved(self, ptype: str) -> None:
        self.solved[ptype] = self.solved.get(ptype, 0) + 1

    async def _ask(self, system: str, messages: list[dict], max_tokens: int = 120) -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=OPENROUTER_BASE_URL, api_key=settings.openrouter_api_key)
        resp = await client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=0.7,
            messages=[{"role": "system", "content": system}, *messages],
            extra_body={"reasoning": {"effort": "none"}, "usage": {"include": True}})
        u = _usage_dict(resp.usage)
        self.cost += u.get("cost_usd") or 0.0
        self.calls += 1
        self.tokens[0] += u.get("input_tokens") or 0
        self.tokens[1] += u.get("output_tokens") or 0
        text = (resp.choices[0].message.content or "").strip()
        return text.splitlines()[0][:300] if text else "i dont get it"

    async def reply(self, ptype: str, chat: list[tuple[str, str]]) -> str:
        """Next learner message, given the chat so far on this problem as
        (who, text) with who in {"learner", "katlego"}."""
        system = PERSONA.format(name=self.name, grade=self.grade, state=self.state(ptype),
                                traits=("\nHow you behave:\n" + self.traits + "\n") if self.traits else "")
        msgs = [{"role": "assistant" if who == "learner" else "user", "content": text} for who, text in chat]
        return await self._ask(system, msgs)

    async def answer_mcq(self, question: str) -> str:
        system = PERSONA.format(name=self.name, grade=self.grade, state=self.state(), traits="")
        text = await self._ask(system + "\nThis is a multiple-choice check-in. Reply with ONE letter only.",
                               [{"role": "user", "content": question}], max_tokens=5)
        m = re.search(r"\b([ABCD])\b", text.upper())
        return m.group(1) if m else "?"
