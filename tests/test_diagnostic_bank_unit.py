"""The sign-up check-in bank: structure, and every computable answer
checked by SymPy (exactly one option has the right value)."""

import json
import re
from pathlib import Path

import pytest
from sympy import Rational, factorial, gcd, sqrt, sympify  # noqa: F401 -- used by eval

BANK = Path(__file__).resolve().parent.parent / "seed" / "diagnostic"
MISCONCEPTIONS = {"SIGN_ERR", "ONE_SIDE_OP", "UNLIKE_TERMS", "PARTIAL_DISTRIB", "ORDER_OPS",
                  "EXP_AS_MULT", "FRAC_ADD_ACROSS", "PLACE_VALUE", "UNITS", "MISREAD"}
TOPIC_COUNTS = {8: 22, 10: 13, 11: 12, 12: 12}


def _items(grade):
    return json.loads((BANK / f"grade_{grade:02d}.json").read_text())["items"]


def _value(option: str):
    t = option.replace("R", "").replace("°", "").replace("%", "").replace(" ", " ")
    t = re.sub(r"\s*(?:km/h|cm|mm|km|m)[²³]?(?![a-z])", "", t)
    t = re.sub(r"^\s*x\s*=\s*", "", t).replace(" ", "")
    t = re.sub(r"(\d)√", r"\1*√", t).replace("^", "**")
    t = re.sub(r"√(\d+)", r"sqrt(\1)", t)
    if not re.fullmatch(r"[-0-9./*()sqrt]+", t):
        return None
    try:
        return sympify(t, rational=True)
    except Exception:
        return None


@pytest.mark.parametrize("grade", sorted(TOPIC_COUNTS))
def test_two_items_per_topic(grade):
    items = _items(grade)
    topics = {i["topic"] for i in items}
    assert len(topics) == TOPIC_COUNTS[grade]
    for t in topics:
        kinds = sorted(i["kind"] for i in items if i["topic"] == t)
        assert kinds == ["core", "easier"], t
    assert len({i["id"] for i in items}) == len(items)


@pytest.mark.parametrize("grade", sorted(TOPIC_COUNTS))
def test_items_are_well_formed(grade):
    for i in _items(grade):
        assert len(i["options"]) == 4 and len(set(i["options"])) == 4, i["id"]
        assert i["answer"] in "ABCD"
        for letter, code in i["misc"].items():
            assert letter != i["answer"] and code in MISCONCEPTIONS, i["id"]


@pytest.mark.parametrize("grade", sorted(TOPIC_COUNTS))
def test_computable_answers_are_right(grade):
    checked = 0
    for i in _items(grade):
        if not i["check"]:
            continue
        want = sympify(i["check"], locals={"Rational": Rational, "sqrt": sqrt,
                                           "factorial": factorial, "gcd": gcd})
        vals = [_value(o) for o in i["options"]]
        hits = [l for l, v in zip("ABCD", vals) if v is not None and abs(float(v - want)) < 1e-9]
        # the right number with the wrong unit is a fair distractor ("28 cm" for an area)
        hits = [h for h in hits if h == i["answer"] or i["misc"].get(h) != "UNITS"]
        assert hits == [i["answer"]], (i["id"], i["options"], want)
        checked += 1
    assert checked >= len(_items(grade)) // 3
