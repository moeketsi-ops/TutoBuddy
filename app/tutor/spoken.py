"""Spoken maths -> symbols, for voice-note transcripts.

Whisper writes what it hears: "x equals negative five", "three over four
divided by one half". The code answer check (app.tutor.answer_check) and the
working problem only read symbols, so on the media bench (10 Nov 2026) code
checked 1 of 12 spoken answers against 11 of 12 typed. to_symbols() rewrites
the maths phrases and leaves ordinary words alone:

    "How do I solve 3x plus 4 equals 19?"   -> "How do I solve 3x + 4 = 19?"
    "x equals negative five"                -> "x = -5"
    "Solve two bracket x minus one bracket equals ten" -> "Solve 2(x - 1) = 10"
    "Can you go over this one more time?"   -> unchanged

Words that are maths only in context ("over", "times", "plus", "minus",
"one".."ten") are changed only when they sit next to a number, a variable or
another maths word. Pure text in, text out; never raises.
"""

import re

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_WORD = "|".join(list(_ONES) + list(_TENS) + ["hundred"])
_NUMBER = re.compile(rf"\b(?:{_WORD})(?:[ -](?:and )?(?:{_WORD}))*\b", re.IGNORECASE)
_FRACTION = {"half": 2, "halves": 2, "third": 3, "thirds": 3, "quarter": 4, "quarters": 4,
             "fifth": 5, "fifths": 5, "sixth": 6, "sixths": 6, "eighth": 8, "eighths": 8,
             "tenth": 10, "tenths": 10}
# A small number word ("one".."ten") becomes a digit only beside one of these.
_AFTER = re.compile(r"^(?: and a half\b|[ -](?:plus|minus|times|over|divided|multiplied|equals?|squared|cubed|"
                    r"to the power|point|per ?cent|bracket|[a-z]\b|" + "|".join(_FRACTION) + r")\b)", re.IGNORECASE)
_BEFORE = re.compile(r"(?:plus|minus|negative|times|over|by|equals?|power|power of|per ?cent of|point|bracket|[=+\-*/×÷(^])\s*$",
                     re.IGNORECASE)
_VARS = set("xybcdkmnpqtz")
_ATOM = re.compile(r"-?\(*(?:\d+(?:[.,]\d+)?(?:/\d+)?[a-z]?|\d*[a-z])(?:\^-?\w+)?%?\)*|[()]")
_TRAIL = ".,?!;:"


def _numbers(text: str) -> str:
    def digits(m: re.Match) -> str:
        words = re.findall(r"[a-z]+", m.group(0).lower())
        total = 0
        for w in words:
            if w == "hundred":
                total = max(total, 1) * 100
            elif w != "and":
                total += _ONES.get(w, 0) + _TENS.get(w, 0)
        before, after = text[:m.start()], text[m.end():]
        sure = (len(words) > 1 or total > 10                       # "twenty eight", "nineteen"
                or not (before.strip() or after.strip(_TRAIL + " "))  # the whole message: "five"
                or _AFTER.match(after) or _BEFORE.search(before))
        return str(total) if sure else m.group(0)
    return _NUMBER.sub(digits, text)


def _is_atom(token: str | None) -> bool:
    """A number, a variable or a bracketed bit: something an operator can sit beside."""
    if not token:
        return False
    core = token.strip(_TRAIL).lower()
    if not _ATOM.fullmatch(core):
        return False
    return bool(re.search(r"\d|[()^]", core)) or core.lstrip("-") in _VARS


def to_symbols(text: str) -> str:
    try:
        return _to_symbols(text)
    except Exception:  # noqa: BLE001 -- a transcript we can't tidy goes through as heard
        return text


def _to_symbols(text: str) -> str:
    t = " ".join(text.split())
    t = _numbers(t)
    # phrases that are only ever maths
    t = re.sub(r"\b(\d+) and a half\b", r"\1.5", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=\d) point (?=\d)", ".", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(\d+)[ -](" + "|".join(_FRACTION) + r")\b",
               lambda m: f"{m.group(1)}/{_FRACTION[m.group(2).lower()]}", t, flags=re.IGNORECASE)
    t = re.sub(r"\b([fgh]) of ([a-z])\b", r"\1(\2)", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*,?\s*\b(?:raised )?to the power(?: of)?\b,?\s*", " ^ ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+squared\b", "^2", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+cubed\b", "^3", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:is )?equal(?:s| to)\b", "=", t, flags=re.IGNORECASE)
    t = re.sub(r"\bdivided by\b", "÷", t, flags=re.IGNORECASE)
    t = re.sub(r"\bmultiplied by\b", "×", t, flags=re.IGNORECASE)
    t = re.sub(r"(?<=\d) ?per ?cent\b", "%", t, flags=re.IGNORECASE)
    # brackets said aloud: "open bracket ... close bracket", or a bare "bracket ... bracket"
    t = re.sub(r",?\s*\bopen(?:ing)? brackets?\b,?", " (", t, flags=re.IGNORECASE)
    t = re.sub(r",?\s*\bclos(?:e|ed|ing) brackets?\b", " )", t, flags=re.IGNORECASE)
    # only in pairs: one stray "bracket" (a misheard note) is left as the word
    if len(re.findall(r"\bbracket\b", t, flags=re.IGNORECASE)) % 2 == 0:
        side = iter("()" * 20)
        t = re.sub(r",?\s*\bbracket\b,?", lambda _m: " " + next(side, ")"), t, flags=re.IGNORECASE)

    tokens = t.split()
    # "3 a plus 2 b": a lone letter after a number is its variable
    out: list[str] = []
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1].strip(_TRAIL).lower() if i + 1 < len(tokens) else ""
        if (out and re.fullmatch(r"-?\d+(?:[.,]\d+)?", out[-1]) and re.fullmatch(r"[a-z]", tok.strip(_TRAIL), re.IGNORECASE)
                and (not nxt or nxt in ("plus", "minus", "times", "over", "=", "÷", "×", ")", "^"))):
            out[-1] += tok
        else:
            out.append(tok)
    tokens = out
    # "negative 5", and a "minus" with nothing to subtract from, are signs
    out = []
    i = 0
    while i < len(tokens):
        word = tokens[i].lower()
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if word in ("negative", "minus") and _is_atom(nxt) and (word == "negative" or not _is_atom(out[-1] if out else None)):
            out.append("-" + nxt)
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    tokens = out
    # the rest need maths on both sides: "x plus 4", "3 over 4", "5x times 2"
    for i in range(1, len(tokens) - 1):
        word = tokens[i].lower()
        if word in ("plus", "minus", "times", "over") and _is_atom(tokens[i - 1]) and _is_atom(tokens[i + 1]):
            tokens[i] = {"plus": "+", "minus": "-", "times": "×", "over": "/"}[word]
    t = " ".join(tokens)
    t = re.sub(r"(?<=[\w)]) / (?=[\w(-])", "/", t)     # 3 / 4 -> 3/4
    t = re.sub(r" \^ ", "^", t)                         # x ^ 5 -> x^5
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"(?<=[\d)]) \(", "(", t)               # 2 (x - 1) -> 2(x - 1)
    return t


# ponytail: a clause counts as "understood" when it has maths in it or opens like
# a question. Real language detection if the real recordings show this drops
# things learners want to see.
_STARTS = re.compile(r"^(how|what|why|when|which|where|solve|simplify|find|calculate|work out|factor|"
                     r"factorise|factorize|expand|can you|could you|help me|i need help|teach me|is|does|do)\b",
                     re.IGNORECASE)


def echo(text: str) -> str:
    """What to show after "I heard": the transcript from its first clause
    that has maths in it or starts like a question. Whisper turns a greeting
    in isiZulu, Sesotho or Afrikaans into nonsense ("Sarubornaka Flethor,
    Angisala Angisais, how do I solve ..."); echoing that back reads as if
    Katlego mocked the learner. Only the echo is trimmed: the tutor still
    gets the whole transcript."""
    clauses = re.split(r"(?<=[.?!,;])\s+", text.strip())
    for i, clause in enumerate(clauses):
        if re.search(r"\d|[=+×÷^]", clause) or _STARTS.match(clause.strip()):
            kept = " ".join(clauses[i:])
            return kept[:1].upper() + kept[1:] if i else kept
    return text.strip()


UNCLEAR_REPLY = ("I'm not sure I heard the maths in that one right 🙈 Could you say it again a bit slower, "
                 "or type it? Tip: say \"open bracket\" and \"close bracket\", and \"times\" only when you mean multiply.")


def unclear(text: str) -> bool:
    """Is this transcript (after to_symbols) probably misheard maths? True
    when maths words are left over that to_symbols could not place: a
    "bracket" without its pair, or "plus/minus/times" stranded inside an
    equation ("two brackets times -1 bracket = 10", a real recording, 15 Nov
    2026). Then Katlego asks the learner to repeat instead of tutoring on a
    problem nobody set.
    # ponytail: catches leftovers only. A mishearing that is still valid maths
    # ("six equals" heard as "6x equals") passes; the "I heard" line is the
    # learner's check for those. A model-based check if real use shows it matters.
    """
    words = set(re.findall(r"[a-z]+", text.lower()))
    return bool(words & {"bracket", "brackets"}) or ("=" in text and bool(words & {"plus", "minus", "times"}))
