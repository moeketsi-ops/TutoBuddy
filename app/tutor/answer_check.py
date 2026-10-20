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
    """{"equation", "var", "solutions"} for a checkable working problem."""
    if not problem:
        return None
    eq = extract_equation(problem)
    if not eq:
        return None
    got = _solutions(eq)
    if not got:
        return None
    var, sols = got
    return {"equation": eq, "var": str(var), "solutions": sorted(str(s) for s in sols),
            "_sols": sols}


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
        sols = solved["_sols"]
        answer = ", ".join(solved["solutions"])
        base = {"equation": solved["equation"], "answer": answer}
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
    except Exception:  # noqa: BLE001 -- checking is best-effort, never costs a reply
        return None


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
