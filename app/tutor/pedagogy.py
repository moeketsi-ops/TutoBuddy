"""Pedagogy engine v1: code decides HOW Katlego teaches the next reply; the
model only carries it out.

Design note: tutobuddy-dynamic-pedagogy-engine-design.md (sections 4, 6, 9,
16, 17). This is the smallest version that closes the loop:

    STATE line says what happened -> evidence + strategy stats updated ->
    choose() picks the next strategy -> one instruction line goes in the
    prompt -> the next STATE line reports which strategy was really used.

Selection = six deterministic guard-rail rules (readable, testable), and
inside rule 3 a per-learner Thompson-sampling bandit: each strategy's
success rate for THIS learner on THIS topic is a Beta(1+successes,
1+failures) belief, and we pick the strategy with the highest draw. With
no data it falls back to the ladder order, so behaviour is predictable for
a new learner and personalises as evidence arrives ("learning style is
dynamic, not a label", design note section 3). Cost: zero tokens.
"""

import random

# Instruction lines are deliberately short: only the chosen one is sent.
STRATEGIES: dict[str, str] = {
    "PRIOR_KNOWLEDGE_ACTIVATION": (
        "Before teaching, ask ONE short question about what they already remember "
        "about this objective. Do not explain yet."),
    "SOCRATIC_QUESTIONING": (
        "Ask ONE leading question that points at the next step. Do not do the step."),
    "SCAFFOLDED_EXAMPLE": (
        "Do the first step of THEIR problem yourself, explain why in one line, then "
        "ask them to do the next step."),
    "WORKED_EXAMPLE": (
        "Solve a DIFFERENT but parallel problem fully, step by step, then hand their "
        "problem back and ask for the first step."),
    "VISUAL_MODEL": (
        "Show the idea as a simple text picture (number line, balance scale, table or "
        "grid using plain characters), then ask one question about it."),
    "ANALOGY": (
        "Explain with one everyday South African comparison, then link it back to the "
        "maths with one question."),
    "MISCONCEPTION_REMEDIATION": (
        "Name the specific mistake kindly, show with a tiny example why it fails, then "
        "ask them to retry their step."),
    "RETRIEVAL_PRACTICE": (
        "Start with one quick recall question on the objective due for review, then "
        "continue with what they asked."),
}

LADDER = ("SOCRATIC_QUESTIONING", "SCAFFOLDED_EXAMPLE", "WORKED_EXAMPLE",
          "VISUAL_MODEL", "ANALOGY")

BAND_START = {"remediate": "WORKED_EXAMPLE", "practice": "SCAFFOLDED_EXAMPLE",
              "challenge": "SOCRATIC_QUESTIONING", "advance": "SOCRATIC_QUESTIONING"}

SUCCESS = {"attempt_correct", "explained_back"}
FAILURE = {"attempt_wrong", "attempt_partial", "asked_for_answer"}

MAX_STRATEGIES_PER_PROBLEM = 4  # bounded exploration (design note section 9)
SKIP_BELOW_RATE = 0.30          # once a strategy has >= 3 tries for this learner+topic
MIN_TRIES_TO_SKIP = 3


def _band(score: float) -> str:
    from app.tutor.mastery import band
    return band(score)


def _thompson(candidates: list[str], stats: dict[str, tuple[int, int]],
              rng: random.Random) -> tuple[str, str]:
    """(strategy, why). `candidates` arrive in preference order; that order
    wins when this learner has no data on any of them, otherwise the best
    Beta draw (ties keep the preference order)."""
    if not any(stats.get(c, (0, 0))[0] for c in candidates):
        return candidates[0], "next on the ladder"
    draws = {}
    for c in candidates:
        tries, wins = stats.get(c, (0, 0))
        draws[c] = rng.betavariate(1 + wins, 1 + max(0, tries - wins))
    best = max(candidates, key=lambda c: (draws[c], -candidates.index(c)))
    tries, wins = stats.get(best, (0, 0))
    return best, f"best fit for this learner so far ({wins}/{tries})"


def choose(
    *,
    score: float,
    current: str | None,
    fails_in_row: int,
    tried_on_problem: list[str],
    new_lo_this_session: bool,
    misconception_repeated: bool,
    review_due: bool,
    has_open_problem: bool,
    asked_answer_count: int,
    wrong_on_problem: int,
    stats: dict[str, tuple[int, int]] | None = None,
    rng: random.Random | None = None,
) -> dict:
    """The pedagogy decision object (design note section 17, compact form).
    Pure function: everything it needs is passed in."""
    stats = stats or {}
    rng = rng or random.Random(0)
    hint = min(3, wrong_on_problem)
    reveal = hint >= 3 or asked_answer_count >= 2
    decision = {"hint": hint, "reveal": reveal, "require_attempt": not reveal}

    if review_due and not has_open_problem:
        return {**decision, "strategy": "RETRIEVAL_PRACTICE", "why": "review is due"}
    if new_lo_this_session and not has_open_problem:
        return {**decision, "strategy": "PRIOR_KNOWLEDGE_ACTIVATION",
                "why": "new objective this session"}
    if misconception_repeated:
        return {**decision, "strategy": "MISCONCEPTION_REMEDIATION",
                "why": "same mistake twice"}

    if current in LADDER and fails_in_row >= 2:
        if len(set(tried_on_problem)) >= MAX_STRATEGIES_PER_PROBLEM:
            # Patient, not permissive: show it fully, then an easier parallel
            # problem restarts the ladder (engine clears tried_on_problem).
            return {**decision, "strategy": "WORKED_EXAMPLE", "reveal": True,
                    "require_attempt": True, "restart": True,
                    "why": f"{len(set(tried_on_problem))} approaches tried: show it, then an easier one"}
        # Move toward MORE support first (the ladder is ordered least to most
        # scaffolded), then wrap round to anything not yet tried.
        i = LADDER.index(current)
        order = list(LADDER[i + 1:]) + list(LADDER[:i])
        remaining = [s for s in order if s not in tried_on_problem]
        remaining = [s for s in remaining
                     if not (stats.get(s, (0, 0))[0] >= MIN_TRIES_TO_SKIP
                             and stats[s][1] / stats[s][0] < SKIP_BELOW_RATE)] or remaining
        if remaining:
            pick, why = _thompson(remaining, stats, rng)
            return {**decision, "strategy": pick,
                    "why": f"{current.lower().replace('_', ' ')} failed {fails_in_row}x; {why}"}

    if current in STRATEGIES and current not in ("PRIOR_KNOWLEDGE_ACTIVATION", "RETRIEVAL_PRACTICE",
                                                  "MISCONCEPTION_REMEDIATION"):
        return {**decision, "strategy": current, "why": "keep going"}

    start = BAND_START[_band(score)]
    return {**decision, "strategy": start, "why": f"{_band(score)} band start"}


def with_fallback(decide_kwargs: dict) -> dict:
    """choose(), plus what to do if the learner's CURRENT message turns out
    to be another miss. Code can't judge the message before the call, so
    the model gets both: "use X; if this attempt is wrong too, switch to
    Y". The STATE line reports which one it used. Removes the one-turn lag
    a decide-then-judge loop would have, at ~15 extra prompt tokens."""
    d = choose(**decide_kwargs)
    worse = dict(decide_kwargs,
                 fails_in_row=decide_kwargs["fails_in_row"] + 1,
                 wrong_on_problem=decide_kwargs["wrong_on_problem"] + 1,
                 current=d["strategy"],
                 tried_on_problem=list(decide_kwargs["tried_on_problem"]) + [d["strategy"]])
    if decide_kwargs["has_open_problem"] and d["strategy"] in LADDER:
        f = choose(**worse)
        if f["strategy"] != d["strategy"]:
            d["fallback"] = f["strategy"]
    return d


def decision_line(d: dict) -> str:
    line = (f"PEDAGOGY strat={d['strategy']} why=\"{d['why']}\" hint={d['hint']} "
            f"reveal={'yes' if d['reveal'] else 'no'} "
            f"require_attempt={'yes' if d['require_attempt'] else 'no'}\n"
            f"How: {STRATEGIES[d['strategy']]}")
    if d.get("fallback"):
        line += (f"\nIf their latest message is ANOTHER wrong attempt, use "
                 f"strat={d['fallback']} instead: {STRATEGIES[d['fallback']]}")
    return line


def instruction(strategy: str) -> str:
    return STRATEGIES[strategy]


def outcome(evidence: str) -> bool | None:
    """Did the strategy that prompted this learner message work?"""
    if evidence in SUCCESS:
        return True
    if evidence in FAILURE:
        return False
    return None


# ── Database side ────────────────────────────────────────────────────────────

async def load_stats(conn, learner_id: int, topic_id: int) -> dict[str, tuple[int, int]]:
    rows = await conn.fetch(
        "SELECT strategy, tries, successes FROM learner_strategy_stats "
        "WHERE learner_id = $1 AND topic_id = $2",
        learner_id, topic_id,
    )
    return {r["strategy"]: (r["tries"], r["successes"]) for r in rows}


async def record_outcome(conn, learner_id: int, topic_id: int, strategy: str, success: bool) -> None:
    await conn.execute(
        """
        INSERT INTO learner_strategy_stats (learner_id, topic_id, strategy, tries, successes)
        VALUES ($1, $2, $3, 1, $4)
        ON CONFLICT (learner_id, topic_id, strategy) DO UPDATE
            SET tries = learner_strategy_stats.tries + 1,
                successes = learner_strategy_stats.successes + EXCLUDED.successes
        """,
        learner_id, topic_id, strategy, 1 if success else 0,
    )
