"""Programmatic graders for the bake-off. Pure functions, no model calls."""

import math
import re

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_SUP_RUN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+")


def normalize(text: str) -> str:
    """Make maths answers comparable across formatting styles: unicode minus,
    superscripts, LaTeX, decimal commas, thousands spaces, spaces round operators."""
    t = text.lower()
    t = _SUP_RUN.sub(lambda m: "^" + m.group(0).translate(_SUPERSCRIPTS), t)
    t = t.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))   # log₂ → log2
    t = t.replace("−", "-").replace("–", "-").replace("÷", "/")
    t = re.sub(r"\\d?frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", t)
    t = re.sub(r"\\(times|cdot)", "×", t)
    t = re.sub(r"\\left|\\right|\\[()\[\]]|[$*_`]", "", t)
    t = t.replace("·", "×").replace("°", "")
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)                      # decimal comma
    t = re.sub(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))", "", t)       # thousands space
    t = re.sub(r"\s*([=+\-/^×:])\s*", r"\1", t)
    t = t.replace("×", "x")
    return re.sub(r"\s+", " ", t).strip()


_NUMERIC = re.compile(r"-?\d+(\.\d+)?(/\d+(\.\d+)?)?")


def _found(alt: str, haystack: str) -> bool:
    a = normalize(alt)
    if not a:
        return False
    if _NUMERIC.fullmatch(a):
        behind = r"(?<![\d./])" if a.startswith("-") else r"(?<![\d./-])"
        return re.search(behind + re.escape(a) + r"(?![\d./])", haystack) is not None
    return a in haystack


def final_region(text: str) -> str:
    """The part of a worked solution that states the answer: after the last
    'final answer', else the last two non-empty lines."""
    m = list(re.finditer(r"final answer", text, re.IGNORECASE))
    if m:
        return text[m[-1].end():]
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-2:])


def answer_matches(output: str, alts: list[str]) -> bool:
    region = normalize(final_region(output))
    return any(_found(a, region) for a in alts)


def leaks_answer(reply: str, alts: list[str]) -> bool:
    """True if the reply states the final answer anywhere."""
    text = normalize(reply)
    return any(_found(a, text) for a in alts)


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def asks_question(text: str) -> bool:
    return "?" in text


def has_link(text: str) -> bool:
    return re.search(r"https?://|www\.", text, re.IGNORECASE) is not None


def marking_outcome(expected: str, predicted: str) -> dict:
    return {
        "exact": float(predicted == expected),
        "false_correct": float(predicted == "correct" and expected != "correct"),
        "false_incorrect": float(predicted == "incorrect" and expected == "correct"),
    }


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a pass rate; (0, 0) when n == 0."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
