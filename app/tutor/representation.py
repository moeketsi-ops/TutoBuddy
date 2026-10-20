"""Concrete -> Pictorial -> Abstract (CPA): the representation layer on top
of the teaching strategies (spec "Katlego CPA + mastery switching v0.1",
section 3, and the DBE Teaching Mathematics for Understanding framework,
which asks for "concrete, pictorial, and symbolic material", p. 15).

A strategy says HOW Katlego teaches (Socratic question, worked example...);
a level says IN WHAT FORM the maths is shown. Code picks both; the model
carries them out and reports the level the learner actually worked at.

On WhatsApp "concrete" can't be blocks on a desk: it is objects from the
learner's life, shown as emojis they can count and move (Grade 8-9), or a
real context with numbers to try by hand (Grade 10-12).
"""

LEVELS = ("concrete", "pictorial", "abstract")

EMOJI_RULES = (
    "Emoji rules: one emoji = one meaning, give the legend in the first line "
    "(e.g. 🍬 = 1 sweet, 🛍️ = a bag of x sweets) and keep it for the whole problem; "
    "objects from the learner's world (🚕 taxi fares, 🍞 bread, 📱 data, ⚽ scores, 🌽 mealies); "
    "count only up to about 20; never put emojis inside an equation as decoration; "
    "always say it in words too, in case the phone shows boxes.")

_INSTRUCTIONS = {
    ("concrete", "junior"): (
        "LEVEL concrete: turn the problem into a real situation with objects the learner can "
        "count, using emojis as the objects. Ask them to DO something to the objects (take "
        "away, share, group) and tell you what is left."),
    ("concrete", "fet"): (
        "LEVEL concrete: put the problem in a real context the learner knows (taxi fares, data "
        "bundles, savings, sport, folding paper) and ask them to try one or two numbers by hand. "
        "Emojis may label the context, not count it."),
    ("pictorial", "junior"): (
        "LEVEL pictorial: draw it in plain text: a bar model like [ x ][ x ][ x ][4] = 19, a "
        "balance, a number line or a small table. Emojis may label the parts. Ask ONE question "
        "about the picture."),
    ("pictorial", "fet"): (
        "LEVEL pictorial: show it as a small table of values, a text sketch of a graph or an "
        "area diagram in plain characters. Ask ONE question about it."),
    ("abstract", "junior"): "LEVEL abstract: work in symbols with the standard method.",
    ("abstract", "fet"): "LEVEL abstract: work in symbols with the standard method.",
}

BRIDGE = ("BRIDGE: the learner succeeded with a picture or real objects. Ask them to write what "
          "they just did in symbols (an equation or expression) before the problem is closed.")


def phase(grade: int) -> str:
    return "fet" if grade >= 10 else "junior"


def instruction(level: str, grade: int) -> str:
    line = _INSTRUCTIONS[(level, phase(grade))]
    if level != "abstract":
        line += "\n" + EMOJI_RULES
    return line


def step_down(level: str) -> str:
    """One step toward concrete (abstract -> pictorial -> concrete)."""
    i = LEVELS.index(level)
    return LEVELS[max(0, i - 1)]


def step_up(level: str) -> str:
    i = LEVELS.index(level)
    return LEVELS[min(len(LEVELS) - 1, i + 1)]


def start_level(score: float, level_stats: dict[str, tuple[int, int]] | None = None) -> tuple[str, str]:
    """(level, why) for a new problem. The learner's own history wins: the
    level with the best success share on this topic once it has 2+ tries.
    Otherwise entry comes from mastery, not grade: a weak score starts
    pictorial, everyone else abstract (concrete is reached by switching)."""
    stats = level_stats or {}
    seen = {lv: (t, s) for lv, (t, s) in stats.items() if lv in LEVELS and t >= 2}
    if seen:
        best = max(seen, key=lambda lv: ((seen[lv][1] + 1) / (seen[lv][0] + 2), LEVELS.index(lv)))
        t, s = seen[best]
        return best, f"works best for this learner ({s}/{t})"
    from app.tutor.mastery import band
    if band(score) == "remediate":
        return "pictorial", "low mastery: start with a picture"
    return "abstract", f"{band(score)} band start"


def effectiveness(tries: int, successes: int) -> float:
    """(successes + 1) / (tries + 2): a pair tried once is not over-trusted."""
    return (successes + 1) / (tries + 2)


# ── Database side ────────────────────────────────────────────────────────────

async def load_stats(conn, learner_id: int, topic_id: int) -> dict[str, tuple[int, int]]:
    rows = await conn.fetch(
        "SELECT cpa_level, tries, successes FROM learner_level_stats "
        "WHERE learner_id = $1 AND topic_id = $2", learner_id, topic_id)
    return {r["cpa_level"]: (r["tries"], r["successes"]) for r in rows}


async def record_outcome(conn, learner_id: int, topic_id: int, level: str, success: bool) -> None:
    await conn.execute(
        """
        INSERT INTO learner_level_stats (learner_id, topic_id, cpa_level, tries, successes)
        VALUES ($1, $2, $3, 1, $4)
        ON CONFLICT (learner_id, topic_id, cpa_level) DO UPDATE
            SET tries = learner_level_stats.tries + 1,
                successes = learner_level_stats.successes + EXCLUDED.successes
        """, learner_id, topic_id, level, 1 if success else 0)
