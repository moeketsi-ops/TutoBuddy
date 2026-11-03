"""Code-side answer checking: judge an attempt at the working problem with
SymPy instead of asking the model (spec "Katlego CPA + mastery switching
v0.1", section 5).

Why: in the first real run the model labelled only 56-78% of attempts
correctly, and those labels move mastery scores and trigger strategy
switches. When the working problem is a one-variable equation, code can be
certain:

    problem "Solve 3x + 4 = 19"   reply "x = 5"    -> correct
                                  reply "3x = 15"  -> step_forward (an
                                                      equivalent equation)
                                  reply "x = 7"    -> wrong
                                  reply "minus 5?" -> None (code can't tell;
                                                      the model judges it)

The check runs BEFORE the tutoring call, so the verdict goes into the
prompt ("CODE CHECK: correct") and the model no longer has to guess
whether "x = 10" is an attempt or off-topic.

Safety: learner text never reaches sympy's parser unless it is made only of
digits, operators, brackets and a short whitelist of names, so nothing a
learner types can execute code.
"""

from __future__ import annotations

import re

_ALLOWED_CHARS = re.compile(r"^[0-9a-z+\-*/^().=, ]+$")
_NAMES = {"x", "y", "a", "b", "m", "n", "p", "t", "k", "log", "ln", "sqrt", "sin", "cos",
          "tan", "pi", "e"}
_VARS = {"x", "y", "a", "b", "m", "n", "p", "t", "k"}
_FUNCS = ("log", "ln", "sqrt", "sin", "cos", "tan")
MAX_LEN = 60


def _normalise(text: str) -> str:
    t = text.lower().strip().rstrip("?.!")
    t = t.replace("×", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
    t = t.replace("²", "^2").replace("³", "^3")
    t = re.sub(r"\blog_?\s*(\d+)\s*\(", r"logb\1(", t)  # log2(x), log_2(x)
    return t


def _mathy(token: str) -> bool:
    tok = token.strip("?.!,:;")
    if not tok:
        return False
    if not _ALLOWED_CHARS.match(tok):
        return False
    if re.search(r"[0-9=+\-*/^()]", tok):
        return True
    return tok in _VARS


def extract_equation(text: str) -> str | None:
    """The longest run of maths-looking words that contains one '='.
    "How do I solve 3x + 4 = 19?" -> "3x + 4 = 19"."""
    t = _normalise(text)
    words = t.split()
    best, run = None, []
    for w in words + [""]:
        if w and _mathy(w):
            run.append(w.strip("?.!,:;"))
            continue
        cand = " ".join(run)
        if cand.count("=") == 1 and re.search(r"\d", cand):
            if best is None or len(cand) > len(best):
                best = cand
        run = []
    return best


def _safe(expr: str) -> bool:
    if len(expr) > MAX_LEN or not _ALLOWED_CHARS.match(expr):
        return False
    names = re.findall(r"[a-z]+", re.sub(r"logb\d+", "log", expr))
    for n in names:
        # implicit products like "xy" or "3x" are split by the parser; only
        # allow names that are whole whitelisted words or runs of variables
        if n not in _NAMES and not all(ch in _VARS for ch in n):
            return False
    return True


def _parse(expr: str):
    from sympy import Symbol, log
    from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application,
                                            parse_expr, standard_transformations)

    if not _safe(expr):
        return None
    # logbN(u) -> log(u, N); bare log(u) is log base 10 in SA schools
    expr = re.sub(r"logb(\d+)\(([^()]*)\)", r"log(\2, \1)", expr)
    expr = re.sub(r"\blog\(([^(),]*)\)", r"log(\1, 10)", expr)
    expr = expr.replace("ln(", "log(")
    local = {v: Symbol(v, real=True) for v in _VARS}
    local["log"] = log
    try:
        return parse_expr(expr, local_dict=local, transformations=standard_transformations
                          + (implicit_multiplication_application, convert_xor), evaluate=True)
    except Exception:  # noqa: BLE001 -- any parse failure means "code can't tell"
        return None


def _solutions(equation: str):
    """(variable, set of real solutions) or None."""
    from sympy import Eq, S, solveset

    if equation.count("=") != 1:
        return None
    left, right = (s.strip() for s in equation.split("="))
    if not left or not right:
        return None
    lhs, rhs = _parse(left), _parse(right)
    if lhs is None or rhs is None:
        return None
    free = (lhs - rhs).free_symbols
    if len(free) != 1:
        return None
    var = next(iter(free))
    try:
        sol = solveset(Eq(lhs, rhs), var, domain=S.Reals)
    except Exception:  # noqa: BLE001
        return None
    if not sol.is_FiniteSet or len(sol) == 0 or len(sol) > 4:
        return None
    return var, set(sol)


def _same(a, b) -> bool:
    try:
        return abs(complex(a.evalf() - b.evalf())) < 1e-9
    except Exception:  # noqa: BLE001
        return False


def _same_set(xs, ys) -> bool:
    return len(xs) == len(ys) and all(any(_same(x, y) for y in ys) for x in xs)


def solve_problem(problem: str | None) -> dict | None:
    """What code knows about the working problem, or None.

    kind "equation":   {"equation", "var", "solutions", "_sols"}
    kind "value":      a number to reach ("What is -8 + 3?", "add 1/3 and
                       1/6", "3 squared", a rectangle's area, a geometric
                       sum to infinity) -> {"answer", "_val"}
    kind "derivative": "derivative of f(x) = x^3 - 6x" -> {"answer", "_expr"}
    kind "simplify":   "simplify 3a + 2b + 5a" -> {"answer", "_expr", "_terms"}
    """
    if not problem:
        return None
    for finder in (_derivative_problem, _equation_problem, _value_problem, _simplify_problem):
        try:
            got = finder(problem)
        except Exception:  # noqa: BLE001 -- a problem code can't read is the model's to judge
            got = None
        if got:
            return got
    return None


def _equation_problem(problem: str) -> dict | None:
    eq = extract_equation(problem)
    if not eq:
        return None
    got = _solutions(eq)
    if not got:
        return None
    var, sols = got
    return {"kind": "equation", "equation": eq, "var": str(var),
            "solutions": sorted(str(s) for s in sols), "_sols": sols}


# ── Problems whose answer is one number ──────────────────────────────────────

_NUM = r"-?\d+(?:\.\d+)?(?:/\d+)?"
_SIMPLE = re.compile(rf"^\(?{_NUM}\)?$")
_PURE = re.compile(r"^[0-9+\-*/^(). ]+$")
_ASK = re.compile(r"^(?:how do i |can you help me |help me )?(?:what is|what's|whats|calculate|"
                  r"work out|evaluate|find the value of|find|simplify|compute)\s+(.+)$")
_UNITS = re.compile(r"\b(?:square|sq|cm\^?2|m\^?2|mm\^?2|km\^?2|cm|mm|km|m|units?|kg|g|ml|l|"
                    r"rand|degrees|metres|meters|centimetres|centimeters)\b")


def _num(text: str):
    """A purely numeric expression -> sympy number, else None."""
    t = text.strip()
    if not t or not _PURE.match(t) or not re.search(r"\d", t):
        return None
    val = _parse(t)
    if val is None or val.free_symbols:
        return None
    return val


def _value_problem(problem: str) -> dict | None:
    from sympy import Abs, Rational, sqrt

    t = _normalise(problem)
    t = re.sub(r"\s+", " ", t)
    val = None
    m = re.search(rf"sum to infinity of ({_NUM}) ?\+ ?({_NUM}) ?\+ ?({_NUM})", t)
    if m:
        a, b, c = (_num(g) for g in m.groups())
        if a and b and c is not None and b != 0:
            r = b / a
            if c / b == r and Abs(r) < 1:
                val = a / (1 - r)
    if val is None:
        m = re.search(rf"area of (?:a|the) (?:rectangle|square)\D*?({_NUM}) ?[a-z]* (?:by|x|×) ({_NUM})", t)
        if m:
            val = _num(m.group(1)) * _num(m.group(2))
    if val is None:
        m = re.search(rf"\badd ({_NUM}) (?:and|to) ({_NUM})\b", t)
        if m:
            val = _num(m.group(1)) + _num(m.group(2))
    if val is None:
        m = re.search(rf"\bsubtract ({_NUM}) from ({_NUM})\b", t)
        if m:
            val = _num(m.group(2)) - _num(m.group(1))
    if val is None:
        m = re.search(rf"\bmultiply ({_NUM}) (?:by|and) ({_NUM})\b", t)
        if m:
            val = _num(m.group(1)) * _num(m.group(2))
    if val is None:
        m = re.search(rf"\b({_NUM}) (squared|cubed)\b", t)
        if m:
            val = _num(m.group(1)) ** (2 if m.group(2) == "squared" else 3)
    if val is None:
        m = re.search(rf"\bsquare root of ({_NUM})\b", t)
        if m:
            val = sqrt(_num(m.group(1)))
    if val is None:
        m = _ASK.match(t.rstrip("?. "))
        if m and "=" not in m.group(1):
            expr = m.group(1).strip()
            # one operator at least: "what is 7" is not a sum to work out
            if re.search(r"\d\s*[+\-*/^]\s*\(?-?\d", expr):
                val = _num(expr)
    if val is None or not getattr(val, "is_real", False):
        return None
    val = Rational(val) if val.is_Rational else val
    return {"kind": "value", "equation": problem.strip()[:80], "answer": _show(val), "_val": val}


def _show(val) -> str:
    from sympy import Rational
    if isinstance(val, Rational) and val.q != 1:
        return f"{val.p}/{val.q}"
    return str(val)


def _check_value(solved: dict, text: str) -> str | None:
    """'-5', '28 square cm', '3/6 which is 1/2', 'x = 32'."""
    t = re.sub(r"(\d)\s*([a-z])", r"\1 \2", text)  # "28cm^2" -> "28 cm^2"
    t = _UNITS.sub(" ", t)
    t = re.sub(r"\b(?:the answer is|answer|it's|its|it is|i got|i think)\b", " ", t)
    t = re.sub(r"^\s*[a-z]\s*=", " ", t)  # "x = 32"
    segments = [s.strip() for s in re.split(r"\b(?:which is|that is|so|is|equals|or)\b|=|,", t)]
    segments = [s for s in segments if s]
    if not segments:
        return None
    vals = []
    for seg in segments:
        v = _num(seg)
        if v is None:
            return None  # words or symbols code can't read: the model judges
        vals.append((seg, v))
    target = solved["_val"]
    hits = [_same(v, target) for _, v in vals]
    simple_hit = any(h and _SIMPLE.match(seg.replace(" ", "")) for (seg, _), h in zip(vals, hits))
    if simple_hit and all(_same(v, vals[0][1]) for _, v in vals):
        return "correct"
    if any(hits):
        # the right value, but as an unworked expression ("16/(1 - 1/2)", "2^5");
        # the problem's own expression typed back ("-8 + 3") is no step at all
        if all(_flat(seg) in _flat(solved["equation"]) for seg, _ in vals):
            return None
        return "step_forward" if all(hits) else "wrong"
    if len(vals) > 1 and all(_same(v, vals[0][1]) for _, v in vals):
        return "step_forward"  # a true rewrite that isn't the answer yet ("1/3 is 2/6")
    return "wrong"


# ── Derivatives and simplifying ──────────────────────────────────────────────

def _derivative_problem(problem: str) -> dict | None:
    from sympy import Symbol, diff

    t = _normalise(problem)
    if not re.search(r"\b(derivative|differentiate|d/dx)\b", t):
        return None
    m = re.search(r"(?:[fgh]\s*\(\s*x\s*\)|y)\s*=\s*([0-9a-z+\-*/^(). ]+)", t) or \
        re.search(r"differentiate\s+([0-9a-z+\-*/^(). ]+)", t)
    if not m:
        return None
    expr = _parse(m.group(1).strip().rstrip("?. "))
    x = Symbol("x", real=True)
    if expr is None or expr.free_symbols != {x}:
        return None
    d = diff(expr, x)
    return {"kind": "derivative", "equation": m.group(0).strip()[:80],
            "answer": _pretty(d), "_expr": d}


def _pretty(expr) -> str:
    s = str(expr).replace("**", "^").replace("*", "")
    return s


def _simplify_problem(problem: str) -> dict | None:
    t = _normalise(problem).rstrip("?. ")
    m = re.search(r"\bsimplify\s+([0-9a-z+\-*/^(). ]+)$", t)
    if not m:
        return None
    raw = m.group(1).strip()
    expr = _parse(raw)
    if expr is None or not expr.free_symbols or "(" in raw or "/" in raw:
        return None  # only like-term collecting; brackets and fractions are the model's
    return {"kind": "simplify", "equation": raw[:80], "answer": _pretty(expr), "_expr": expr,
            "_terms": _term_count(_pretty(expr))}


def _term_count(text: str) -> int:
    return len([p for p in re.split(r"(?<=[\w)])\s*[+-]\s*", text.strip().lstrip("+-")) if p])


def _strip_lhs(text: str) -> str:
    return re.sub(r"^\s*(?:[fgh]'\s*\(\s*x\s*\)|dy/dx|y'|f'|d/dx[^=]*)\s*=\s*", "", text)


def _check_expression(solved: dict, text: str) -> str | None:
    from sympy import simplify

    body = _strip_lhs(text).strip().rstrip("?.!")
    if "=" in body or not body:
        return None
    got = _parse(body)
    if got is None:
        return None
    try:
        same = simplify(got - solved["_expr"]) == 0
    except Exception:  # noqa: BLE001
        return None
    if solved["kind"] == "simplify":
        if not same:
            return "wrong"
        # equivalent but not simpler (the learner echoed the problem) is no answer yet
        return "correct" if _term_count(body) <= solved["_terms"] else None
    return "correct" if same else "wrong"


def check(problem: str | None, reply: str) -> dict | None:
    """Verdict on the learner's reply to the working problem:
    {"verdict": "correct" | "step_forward" | "wrong", "equation", "answer"}
    or None when code cannot judge it (words, a question, an unrelated
    expression). Never raises."""
    try:
        solved = solve_problem(problem)
        if not solved:
            return None
        text = _normalise(reply)
        if len(text) > MAX_LEN * 2:
            return None
        base = {"equation": solved["equation"], "answer": solved.get("answer")
                or ", ".join(solved["solutions"]), "kind": solved["kind"]}
        if solved["kind"] == "value":
            v = _check_value(solved, text)
            return {**base, "verdict": v} if v else None
        if solved["kind"] in ("derivative", "simplify"):
            words = [w for w in text.split() if not _mathy(w)]
            if len(words) > 1:
                return None
            v = _check_expression(solved, text)
            return {**base, "verdict": v} if v else None
        return _check_equation(solved, text, reply, base)
    except Exception:  # noqa: BLE001 -- checking is best-effort, never costs a reply
        return None


def _check_equation(solved: dict, text: str, reply: str, base: dict) -> dict | None:
    sols = solved["_sols"]
    # An explanation in words ("6 times 7 is 42 so x = 42 divided by 6")
    # is for the model to judge, not code.
    words = [w for w in text.split() if not _mathy(w) and w not in ("or", "and")]
    if len(words) > 2:
        return None
    # "x = 3 or x = 4": every root named
    var = solved["var"]
    named = re.findall(rf"(?<![a-z]){var}\s*=\s*([^=]+?)(?=\s+(?:or|and)\b|[,;]|$)", text)
    if len(named) > 1:
        vals = [_parse(v.strip()) for v in named]
        if any(v is None or v.free_symbols for v in vals):
            return None
        if not all(any(_same(v, s_) for s_ in sols) for v in vals):
            return {**base, "verdict": "wrong"}
        covered = all(any(_same(v, s_) for v in vals) for s_ in sols)
        return {**base, "verdict": "correct" if covered else "step_forward"}
    eq = extract_equation(reply)
    if eq:
        left, right = (s.strip() for s in eq.split("="))
        # "x = 32" / "x = 2^5": the variable alone on one side
        for lone, other in ((left, right), (right, left)):
            if lone == solved["var"]:
                val = _parse(other)
                if val is None or val.free_symbols:
                    break
                ok = any(_same(val, s) for s in sols)
                # one root of a quadratic is progress, not the whole answer
                v = ("step_forward" if len(sols) > 1 else "correct") if ok else "wrong"
                return {**base, "verdict": v}
        got = _solutions(eq)
        if not got or str(got[0]) != solved["var"]:
            return None
        return {**base, "verdict": "step_forward" if _same_set(got[1], sols) else "wrong"}
    # a bare value: "32", "2^5"
    bare = text.strip()
    if not re.fullmatch(r"[0-9+\-*/^(). ]+", bare) or not re.search(r"\d", bare):
        return None
    val = _parse(bare)
    if val is None or val.free_symbols:
        return None
    ok = any(_same(val, s) for s in sols)
    return {**base, "verdict": ("step_forward" if len(sols) > 1 else "correct") if ok else "wrong"}


# ── Did a reply give the answer away? ────────────────────────────────────────

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


def _flat(text: str) -> str:
    t = text.lower()
    t = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+", lambda m: "^" + m.group(0).translate(_SUP), t)
    t = t.replace("−", "-").replace("–", "-").replace("÷", "/")
    t = re.sub(r"\\d?frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", t)
    t = re.sub(r"[$*_`\\]", "", t)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = re.sub(r"\s*([=+\-/^])\s*", r"\1", t)
    return re.sub(r"\s+", " ", t)


def answer_forms(problem: str | None) -> list[str]:
    """The ways a reply could state the final answer, for the leak guard.
    Empty when code doesn't know the answer, or when the answer already
    appears in the problem itself (it can't be "given away")."""
    solved = solve_problem(problem)
    if not solved or solved["kind"] in ("derivative", "simplify"):
        return []
    if solved["kind"] == "equation":
        if len(solved["_sols"]) != 1:
            return []
        val = next(iter(solved["_sols"]))
        forms = [f"{solved['var']}={_show(val)}"]
        if not val.is_Integer or abs(int(val)) >= 2:
            forms.append(_show(val))
    else:
        val = solved["_val"]
        forms = [_show(val)]
    if not val.is_Integer:
        try:
            forms.append(f"{float(val):.4g}")
        except TypeError:
            pass
    flat_problem = _flat(problem)
    return [f for f in dict.fromkeys(forms) if not _contains(flat_problem, f)]


def _contains(flat: str, form: str) -> bool:
    if "=" in form:
        return form in flat
    lead = r"(?<![\d./^])" if form.startswith("-") else r"(?<![\d./^-])"
    # a full stop after the number ends the sentence; "5.5" or "5/6" is another number
    return re.search(lead + re.escape(form) + r"(?!\d|[./]\d|\^)", flat) is not None


def gives_away(reply: str, forms: list[str]) -> bool:
    flat = _flat(reply)
    return any(_contains(flat, f) for f in forms)


EVIDENCE = {"correct": ("attempt_correct", "solved"),
            "step_forward": ("attempt_partial", "step_forward"),
            "wrong": ("attempt_wrong", "none")}


def prompt_line(result: dict | None) -> str | None:
    """One line for the prompt so the model doesn't have to judge it."""
    if not result:
        return None
    v = result["verdict"]
    if v == "correct":
        return ("CODE CHECK: the learner's latest message is a CORRECT final answer to the working "
                f"problem ({result['equation']}). Confirm it with specific praise and close this "
                "problem. Do not start a new topic yourself.")
    if v == "step_forward":
        return ("CODE CHECK: the learner's latest message is a VALID STEP (an equivalent equation) "
                "towards the working problem, not the final answer yet. Recognise the step and ask "
                "for the next one.")
    return ("CODE CHECK: the learner's latest message IS an attempt at the working problem "
            f"({result['equation']}) and it is NOT correct. Treat it as an attempt, not off-topic. "
            "Do not reveal the answer.")


def _loose(form: str) -> str:
    """A regex for `form` as a model might write it: spaces round '=',
    a unicode minus, a superscript-free power."""
    out = []
    for ch in form:
        if ch == "-":
            out.append(r"[-\u2212\u2013]\s*")
        elif ch == "=":
            out.append(r"\s*=\s*")
        elif ch in "/^":
            out.append(r"\s*" + re.escape(ch) + r"\s*")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def mask(reply: str, forms: list[str]) -> str:
    """Hide the answer in a reply that kept stating it after a rewrite:
    "you land at -5" -> "you land at …". Last resort; logged."""
    for f in sorted(forms, key=len, reverse=True):
        lead = r"(?<![\d./^])" if f.startswith("-") else r"(?<![\d./^\u2212-])"
        reply = re.sub(lead + _loose(f) + r"(?!\d|[./]\d|\^)", "…", reply)
    return reply
