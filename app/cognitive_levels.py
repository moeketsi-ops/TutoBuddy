"""The four CAPS cognitive levels, one vocabulary for the whole app.

CAPS Mathematics (Senior Phase Table 4.2; FET Section 4) classifies every
assessment item into four levels. Two tables used to spell them
differently: question_bank.cognitive_level held free text ("routine
procedure") while cognitive_level_weights.level_name held an enum
("routine_procedures"). Both now use LEVELS below; app/db.py enforces it
with a CHECK on question_bank and migrates old free-text rows.
"""

LEVELS = ("knowledge", "routine_procedures", "complex_procedures", "problem_solving")

# Spellings seen in authored content and CAPS documents -> canonical level.
_ALIASES = {
    "knowledge": "knowledge",
    "routine procedure": "routine_procedures",
    "routine procedures": "routine_procedures",
    "complex procedure": "complex_procedures",
    "complex procedures": "complex_procedures",
    "problem solving": "problem_solving",
    "problem-solving": "problem_solving",
}


def normalize(value: str | None) -> str | None:
    """Canonical level for `value`, or None for a blank value. Raises
    ValueError for anything that isn't one of the four CAPS levels, so a
    typo in seed content fails the seed run instead of loading silently."""
    if value is None or not str(value).strip():
        return None
    key = " ".join(str(value).strip().lower().replace("_", " ").split())
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(f"unknown CAPS cognitive level {value!r}; expected one of {LEVELS}")
