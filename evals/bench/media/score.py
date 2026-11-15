"""Scoring for the media bench: did a transcript keep the maths that was
said, and did a photo read keep what was written. Pure functions, no I/O.

    python -m evals.bench.media.score      # self-check
"""

import re

_UNITS_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
                "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_NUMBER_WORD = "|".join(list(_UNITS_WORDS) + list(_TENS) + ["hundred"])
_FRACTION = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4,
             "fifth": 5, "fifths": 5, "sixth": 6, "sixths": 6, "eighth": 8, "eighths": 8}


def _number_words(t: str) -> str:
    """ "one hundred and twenty" -> 120, "thirty two" -> 32, "twenty-eight" -> 28."""
    def value(m: re.Match) -> str:
        total = 0
        for w in re.findall(r"[a-z]+", m.group(0)):
            if w == "hundred":
                total = max(total, 1) * 100
            elif w != "and":
                total += _UNITS_WORDS.get(w, 0) + _TENS.get(w, 0)
        return str(total)
    run = rf"\b(?:{_NUMBER_WORD})(?:[ -](?:and )?(?:{_NUMBER_WORD}))*\b"
    return re.sub(run, value, t)


def spoken_to_maths(text: str) -> str:
    """Words to symbols: "x equals negative five" -> "x = -5",
    "two thirds" -> "2/3", "three x squared" -> "3 x^2". Leaves anything
    already in symbols alone, so said text and a transcript end up alike."""
    t = text.lower()
    for a, b in (("−", "-"), ("–", "-"), ("×", "*"), ("÷", "/"), ("²", "^2"), ("³", "^3"),
                 ("½", "1/2"), ("¼", "1/4"), ("¾", "3/4"), ("⁄", "/")):
        t = t.replace(a, b)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    # a hyphen inside a word or before a unit is not a minus: "two-thirds", "28-square"
    t = re.sub(r"(?<=[a-z])-(?=[a-z])|(?<=\d)-(?=(?!negative|minus)[a-z]{2})", " ", t)
    t = _number_words(t)
    t = re.sub(r"\b(\d+) and a half\b", lambda m: f"{m.group(1)}.5", t)
    t = re.sub(r"\b(\d+) 1/2\b", lambda m: f"{m.group(1)}.5", t)
    t = re.sub(r"\b(\d+) (" + "|".join(_FRACTION) + r")\b", lambda m: f"{m.group(1)}/{_FRACTION[m.group(2)]}", t)
    t = re.sub(r"\ba (half|third|quarter)\b", lambda m: f"1/{_FRACTION[m.group(1)]}", t)
    t = re.sub(r"(?<=\d) point (?=\d)", ".", t)
    t = re.sub(r"\bf of x\b", "f(x)", t)
    for pat, sym in ((r"\b(?:raised )?to the power(?: of)?\b", "^"), (r"\bsquared\b", "^2"), (r"\bcubed\b", "^3"),
                     (r"\bopen(?:ing)? (?:bracket|parenthesis)s?\b", "("), (r"\bclosed? (?:bracket|parenthesis)s?\b", ")"),
                     (r"\bclosing (?:bracket|parenthesis)s?\b", ")"),
                     (r"\bdivided by\b|\bover\b", "/"), (r"\bmultiplied by\b|\btimes\b", "*"),
                     (r"\bplus\b", "+"), (r"\bminus\b|\bnegative\b", "-"),
                     (r"\b(?:is )?equals?(?: to)?\b", "="), (r"\bper ?cent\b", "%"),
                     (r"\b(?:kilomet(?:re|er)s?|km) per hour\b|\bkph\b", "km/h"),
                     (r"\bsquare (?:centimet(?:re|er)s?|cm)\b", "cm^2"),
                     (r"\bcentimet(?:re|er)s?\b", "cm"), (r"\bkilomet(?:re|er)s?\b", "km"),
                     (r"\bmet(?:re|er)s?\b", "m"), (r"\br(\d+)\b", r"\1 rand")):
        t = re.sub(pat, sym, t)
    # a bare "bracket ... bracket": first opens, second closes
    n = 0
    def alt(_m):
        nonlocal n
        n += 1
        return "(" if n % 2 else ")"
    return re.sub(r"\bbrackets?\b", alt, t)


_TOKEN = re.compile(r"\d+(?:\.\d+)?|km/h|cm|km|rand|[xybfm]|(?<=\d)a|(?<=\d )a|[-+*/^=()%]")


def maths_tokens(text: str) -> list[str]:
    """The maths in a sentence as a token list, words ignored:
    "How do I solve three x plus four equals nineteen?" -> 3 x + 4 = 19."""
    t = re.sub(r"[a-z]{2,}", lambda m: m.group(0) if m.group(0) in ("cm", "km", "rand") else " ",
               spoken_to_maths(text).replace("km/h", " kmh "))
    t = t.replace("kmh", "km/h")
    return _TOKEN.findall(t)


def maths_kept(said: str, transcript: str) -> bool:
    """Same maths tokens. Words Whisper garbled in front of the maths (a
    greeting in another language) may leave stray letters; they are allowed
    as long as they hold no digits and the maths after them is intact."""
    want, got = maths_tokens(said), maths_tokens(transcript)
    extra = got[:len(got) - len(want)]
    return got == want or (bool(want) and got[len(extra):] == want
                           and not any(tok[0].isdigit() or tok in "=^%" for tok in extra))


# ── Photos ───────────────────────────────────────────────────────────────────

def flat(text: str) -> str:
    """Written maths with spacing, markup and typography removed, so
    "x² − 5x + 6 = 0", "x^2 - 5x + 6 = 0" and "{17/3}" forms compare."""
    t = str(text).lower()
    for a, b in (("−", "-"), ("–", "-"), ("×", "*"), ("·", "*"), ("÷", "/"), ("²", "^2"), ("³", "^3"),
                 ("′", "'"), ("’", "'"), ("{", ""), ("}", ""), ("$", ""), ("\\", ""), ("**", "^")):
        t = t.replace(a, b)
    t = re.sub(r"\^\{?\(?(\w+)\)?\}?", r"^\1", t)
    t = re.sub(r"frac(\w+?)(\d+)\b", r"\1/\2", t)
    return re.sub(r"\s+", "", t)


def _line(text: str) -> str:
    return flat(text).lstrip("=").replace("∴", "")


def _values(text: str) -> set[str]:
    t = str(text).lower().replace("−", "-").replace("–", "-")
    coords = {f"({a.replace(',', '.')};{b.replace(',', '.')})" for a, b in re.findall(
        r"\(\s*(-?\d+(?:[.,]\d+)?)\s*[;,]\s*(-?\d+(?:[.,]\d+)?)\s*\)", t)}
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    return coords | set(re.findall(r"-?\d+(?:\.\d+)?|\bx\b", t))


def score_read(photo: dict, read: dict | None) -> dict:
    """What a photo read got right against the manifest (1.0 / 0.0 each):
    problem   the question was read exactly
    working   every line of the learner's working, in order, exactly
    mistake   the wrong line was copied as written (not silently fixed)
    values    every label on the diagram was read"""
    if not read:
        return {"usable": 0.0, "problem": 0.0,
                **({"working": 0.0} if photo["type"] == "working" else {}),
                **({"mistake": 0.0} if photo.get("wrong_line") else {}),
                **({"values": 0.0} if photo["type"] == "diagram" else {})}
    out = {"usable": 1.0}
    everything = flat(read["problem"] + " " + " ".join(read["working"]))
    if photo["type"] != "diagram":
        out["problem"] = float(all(flat(k) in flat(read["problem"]) for k in photo["keys"]))
    if photo["type"] == "working":
        want = [_line(x) for x in photo["lines"][1:]]
        got = [_line(x) for x in read["working"]]
        if got and got[0] == _line(photo["lines"][0]):
            got = got[1:]  # the first line repeated as working is not an error
        out["working"] = float(got == want)
        if photo.get("wrong_line"):
            out["mistake"] = float(_line(photo["lines"][photo["wrong_line"] - 1]) in everything)
    if photo["type"] == "diagram":
        seen = _values(read["problem"] + " " + " ".join(read["values"]))
        want = {v.replace(",", ".") if not v.startswith("(") else v for v in photo["values"]}
        out["values"] = float(want <= seen)
        out["problem"] = out["values"]  # for a diagram, reading the problem IS reading its values
    return out


def demo() -> None:
    assert maths_tokens("How do I solve three x plus four equals nineteen?") == ["3", "x", "+", "4", "=", "19"]
    assert maths_kept("x equals negative five", "x = -5")
    assert maths_kept("x equals negative five", "X equals negative 5.")
    assert not maths_kept("x equals negative five", "x equals 5")
    assert maths_kept("How do I add two thirds and one quarter?", "How do I add 2/3 and 1/4?")
    assert maths_kept("one hundred and twenty kilometres in one and a half hours", "120 km in 1.5 hours")
    assert maths_kept("Solve two bracket x minus one bracket equals ten.", "Solve 2(x - 1) = 10")
    assert maths_kept("three x squared minus six", "3x² − 6")
    assert maths_kept("fifteen percent of two hundred and forty rand", "15% of R240")
    assert spoken_to_maths("x equals negative five") == "x = - 5"
    assert maths_kept("How do I add two thirds and one quarter?", "Dumalikaflechor. How do I add two-thirds and one-quarter?")
    assert maths_kept("What is five minus negative two?", "What is 5-negative 2?")
    assert maths_kept("twenty eight square centimetres", "28-square centimeters")
    assert not maths_kept("What is three over four divided by one half?", "example network, what is 304 divided by 1 half?")
    p = {"type": "working", "keys": ["2x+3=11"], "lines": ["2x + 3 = 11", "2x = 11 + 3", "2x = 14", "x = 7"],
         "wrong_line": 2}
    ok = {"problem": "2x + 3 = 11", "working": ["2x = 11 + 3", "2x = 14", "x = 7"], "values": []}
    fixed = {"problem": "2x + 3 = 11", "working": ["2x = 11 - 3", "2x = 8", "x = 4"], "values": []}
    assert score_read(p, ok) == {"usable": 1.0, "problem": 1.0, "working": 1.0, "mistake": 1.0}
    assert score_read(p, fixed)["mistake"] == 0.0
    d = {"type": "diagram", "values": ["(-1;0)", "3,5", "x"]}
    assert score_read(d, {"problem": "points (−1, 0); side 3,5 cm; angle x", "working": [], "values": []})["values"] == 1.0
    assert score_read(d, {"problem": "points (1;0), 3.5, x", "working": [], "values": []})["values"] == 0.0
    print("score.py self-check passed")


if __name__ == "__main__":
    demo()
