"""Real past papers on WhatsApp: set a question (or a whole paper), mark the
learner's answer against the official memo, and turn the marks into
mastery evidence and a paper report.

Papers come from seed/papers/grade_XX/*.json (built by
seed/papers/build_papers.py from the OCR'd papers + memos). Every paper is
"unverified" until the founder checks it against the PDF.

Marking: code checks the final answer where it can (value, roots,
expression, point); the model marks the working against the memo points
with that check as a fact it must trust. Without a model (stub), code alone
awards the answer marks for a correct final answer. Code also bounds the
model: a wrong final answer can't get the answer marks, a correct one
always gets them.

Study squads: a few learners in the same grade share a code and a paper;
each works in their own chat and SQUAD RESULTS shows the scoreboard.
"""

from __future__ import annotations

import json
import random
import re
import string
from functools import lru_cache
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parents[2] / "seed" / "papers"


# ── Data ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _all() -> dict[str, dict]:
    out = {}
    for f in sorted(PAPER_DIR.glob("grade_*/*.json")):
        p = json.loads(f.read_text())
        out[p["id"]] = p
    return out


def get(paper_id: str) -> dict | None:
    return _all().get(paper_id)


def for_grade(grade: int) -> list[dict]:
    return [p for p in _all().values() if p["grade"] == grade]


def questions_on(grade: int, topics: list[str]) -> list[tuple[str, int]]:
    """(paper_id, question index) for every question on any of `topics`."""
    want = {t.lower() for t in topics}
    return [(p["id"], i) for p in for_grade(grade) for i, q in enumerate(p["questions"])
            if (q["topic"] or "").lower() in want]


def topics_with_questions(grade: int) -> list[str]:
    return sorted({q["topic"] for p in for_grade(grade) for q in p["questions"] if q["topic"]})


def menu(grade: int) -> str:
    papers = for_grade(grade)
    if not papers:
        return (f"I don't have Grade {grade} past papers ready yet 📚 Say \"quiz me\" for practice "
                "questions instead.")
    lines = [f"📝 *Grade {grade} past papers* (marked against the official memo)\n"]
    for i, p in enumerate(papers, 1):
        lines.append(f"{i}. {p['title']}: {len(p['questions'])} questions, {p['marks']} marks")
    lines.append("\nReply with a number to start a paper, or send PAPER and a topic "
                 f"(e.g. PAPER {topics_with_questions(grade)[0]}) for questions on one topic.")
    return "\n".join(lines)


def question_text(paper: dict, idx: int, *, number: int | None = None, total: int | None = None) -> str:
    q = paper["questions"][idx]
    head = f"*Question {q['n']}* ({q['marks']} mark{'s' if q['marks'] > 1 else ''})"
    if q["topic"]:
        head += f" · {q['topic']}"
    if number and total:
        head = f"[{number}/{total}] " + head
    body = (f"_{q['context']}_\n\n" if q.get("context") else "") + q["text"]
    return (f"{head}\n\n{body}\n\nSend your answer with your working (working earns marks). "
            "HELP = work through it step by step with me (no marks for this one) · SKIP · STOP")


# ── Checking the final answer in code ────────────────────────────────────────

_NUM = r"-?\d+(?:[.,]\d+)?(?:/\d+)?"


def _clean(text: str) -> str:
    t = text.replace("−", "-").replace("–", "-").replace("×", "*").replace("·", "*")
    t = t.replace("²", "^2").replace("³", "^3").replace("½", "1/2")
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)  # decimal comma
    t = re.sub(r"(?<=\d)[ \u00a0](?=\d{3}(?!\d))", "", t)  # thousands space: 73 350
    return t


def _sym(expr: str, var: str | None = None):
    from app.tutor.answer_check import _parse
    return _parse(_clean(expr).lower().strip().rstrip(".!? "))


def _trusted(expr: str):
    """Parse an expression from OUR paper files (never learner text)."""
    from sympy import Rational, Symbol, sqrt, sympify
    names = {v: Symbol(v, real=True) for v in "xyabmnptk"}
    return sympify(expr, locals={**names, "Rational": Rational, "sqrt": sqrt}, rational=True)


def _close(a, b, tol: float) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _numbers(text: str) -> list:
    out = []
    for tok in re.findall(_NUM, _clean(text)):
        v = _sym(tok)
        if v is not None and not v.free_symbols:
            out.append(v)
    return out


def check(question: dict, learner_text: str) -> str | None:
    """"correct" / "wrong" for the learner's final answer, or None when
    code can't tell (no check, or nothing it can read)."""
    c = question.get("check")
    if not c:
        return None
    try:
        t = _clean(learner_text)
        last = [ln for ln in t.strip().splitlines() if ln.strip()]
        final = last[-1] if last else t
        if c["type"] == "value":
            target = _trusted(c["value"])
            nums = _numbers(final.split("=")[-1])
            if not nums:
                return None
            return "correct" if any(_close(n, target, 1e-6) for n in nums[-1:]) else "wrong"
        if c["type"] == "solutions":
            tol = c.get("tolerance", 1e-9)
            want = [_trusted(v) for v in c["values"]]
            # the last line, or the whole message if the roots are spread out
            got = _numbers(re.sub(rf"\b{c['var']}\s*=", " ", final))
            if len(got) < len(want):
                got = _numbers(re.sub(rf"\b{c['var']}\s*=", " ", t))[-len(want) - 2:]
            if not got:
                return None
            hit = all(any(_close(g, w, tol) for g in got) for w in want)
            extra = [g for g in got if not any(_close(g, w, tol) for w in want)]
            return "correct" if hit and not extra[: max(0, len(got) - len(want))] else "wrong"
        if c["type"] == "point":
            nums = _numbers(final)
            if len(nums) < 2:
                return None
            x, y = nums[-2], nums[-1]
            return "correct" if _close(x, _trusted(c["point"][0]), 1e-6) and \
                _close(y, _trusted(c["point"][1]), 1e-6) else "wrong"
        if c["type"] == "expression":
            body = final.split("=")[-1]
            got = _sym(body)
            want = _trusted(c["expr"])
            if got is None or want is None:
                return None
            from sympy import simplify
            if simplify(got - want) != 0:
                return "wrong"
            form = c.get("form")
            if form == "factorised" and "(" not in body:
                return "wrong"  # equivalent but not factorised
            if form == "expanded" and "(" in body:
                return "wrong"
            return "correct"
    except Exception:  # noqa: BLE001 -- code checking is best-effort
        return None
    return None


def answer_marks(question: dict) -> int:
    return sum(p["m"] for p in question["memo"] if p.get("a"))


async def mark(question: dict, learner_text: str, grade: int) -> dict:
    """{"awarded", "of", "feedback", "code"}. The model marks against the
    memo; code bounds it."""
    from app.adapters import llm

    verdict = check(question, learner_text)
    fact = None
    if verdict == "correct":
        fact = f"the learner's final answer is CORRECT ({question['answer']})."
    elif verdict == "wrong":
        fact = f"the learner's final answer is NOT correct (the memo's answer is {question['answer']})."
    text = (f"{question['context']}\n" if question.get("context") else "") + question["text"]
    res = await llm.mark_against_memo(text, question["marks"], question["memo"], learner_text,
                                      grade, fact)
    marks, ans = question["marks"], answer_marks(question)
    if res is None:  # no model: code marks what it can
        if verdict == "correct":
            awarded = marks if ans == marks else ans
            fb = ("Correct final answer ✅" + ("" if ans == marks else
                  " Answer marks awarded; the method marks need your working checked."))
        elif verdict == "wrong":
            awarded, fb = 0, "Not the memo's final answer."
        else:
            awarded, fb = 0, "I can't mark this one offline. Compare with the memo below."
        res = {"awarded": awarded, "feedback": fb}
    awarded = res["awarded"]
    if verdict == "wrong":
        awarded = min(awarded, marks - ans)
    elif verdict == "correct":
        awarded = max(awarded, ans)
    return {"awarded": awarded, "of": marks, "feedback": res["feedback"], "code": verdict}


def memo_text(question: dict) -> str:
    pts = "; ".join(p["p"] for p in question["memo"])
    return f"📘 Memo: {pts}"


# ── A paper session (lives in the Redis session: sess.data["paper"]) ─────────

def start(paper_id: str | None, learner_id: int, *, items: list[tuple[str, int]] | None = None,
          squad: str | None = None, label: str | None = None) -> dict:
    if items is None:
        p = get(paper_id)
        items = [(paper_id, i) for i in range(len(p["questions"]))]
    return {"items": items, "i": 0, "results": [], "learner_id": learner_id, "squad": squad,
            "label": label or (get(paper_id)["title"] if paper_id else "Topic practice"),
            "paper_id": paper_id, "help": False}


def current(state: dict) -> tuple[dict, dict] | None:
    if state["i"] >= len(state["items"]):
        return None
    pid, idx = state["items"][state["i"]]
    p = get(pid)
    return p, p["questions"][idx]


def current_text(state: dict) -> str:
    p, _ = current(state)
    pid, idx = state["items"][state["i"]]
    return question_text(p, idx, number=state["i"] + 1, total=len(state["items"]))


def record(state: dict, result: dict | None, *, helped: bool = False, skipped: bool = False) -> None:
    p, q = current(state)
    state["results"].append({"paper": p["id"], "n": q["n"], "topic": q["topic"], "of": q["marks"],
                             "awarded": (result or {}).get("awarded", 0), "helped": helped,
                             "skipped": skipped})
    state["i"] += 1
    state["help"] = False


def finished(state: dict) -> bool:
    return state["i"] >= len(state["items"])


def summary(state: dict, name: str) -> str:
    rs = [r for r in state["results"] if not r["helped"] and not r["skipped"]]
    got, of = sum(r["awarded"] for r in rs), sum(r["of"] for r in rs)
    lines = [f"📊 *{state['label']}* done, {name}!"]
    if of:
        lines.append(f"Marks: *{got}/{of}* ({round(100 * got / of)}%) on the questions you answered.")
    helped = [r["n"] for r in state["results"] if r["helped"]]
    skipped = [r["n"] for r in state["results"] if r["skipped"]]
    if helped:
        lines.append(f"Worked through with me (not counted): {', '.join(helped)}")
    if skipped:
        lines.append(f"Skipped: {', '.join(skipped)}")
    by_topic: dict[str, list[int]] = {}
    for r in rs:
        if r["topic"]:
            a = by_topic.setdefault(r["topic"], [0, 0])
            a[0] += r["awarded"]
            a[1] += r["of"]
    if by_topic:
        lines.append("")
        for t, (a, o) in sorted(by_topic.items(), key=lambda kv: kv[1][0] / kv[1][1]):
            lines.append(f"• {t}: {a}/{o}")
        weakest = min(by_topic, key=lambda t: by_topic[t][0] / by_topic[t][1])
        if by_topic[weakest][0] < by_topic[weakest][1]:
            lines.append(f"\nNext: let's work on *{weakest}*. Send PAPER {weakest} for more "
                         "questions on it, or ask me anything about it.")
    if state.get("squad"):
        lines.append("\nSend SQUAD RESULTS to see how your squad did.")
    return "\n".join(lines)


def evidence(result: dict) -> str | None:
    """The mastery evidence a marked question gives (source "quiz")."""
    if result["helped"] or result["skipped"]:
        return None
    share = result["awarded"] / result["of"] if result["of"] else 0
    return "attempt_correct" if share >= 0.99 else ("attempt_partial" if share >= 0.5 else "attempt_wrong")


# ── Database side ────────────────────────────────────────────────────────────

async def save_attempt(conn, learner_id: int, state: dict) -> None:
    from app.tutor import mastery

    rows = await conn.fetch(
        "SELECT t.id, t.name FROM topics t JOIN grades g ON g.id = t.grade_id "
        "JOIN learners l ON l.grade = g.grade_number WHERE l.id = $1", learner_id)
    ids = {r["name"]: r["id"] for r in rows}
    for r in state["results"]:
        ev = evidence(r)
        if ev and r["topic"] in ids:
            await mastery.record_event(conn, learner_id, ids[r["topic"]], source="quiz", evidence=ev)
    rs = [r for r in state["results"] if not r["helped"] and not r["skipped"]]
    await conn.execute(
        """
        INSERT INTO paper_attempts (learner_id, paper_id, label, squad_code, awarded, out_of, results)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        """, learner_id, state.get("paper_id"), state["label"][:120], state.get("squad"),
        sum(r["awarded"] for r in rs), sum(r["of"] for r in rs), json.dumps(state["results"]))


def new_code(rng: random.Random | None = None) -> str:
    rng = rng or random.SystemRandom()
    alphabet = "".join(ch for ch in string.ascii_uppercase + string.digits if ch not in "O0I1L")
    return "".join(rng.choice(alphabet) for _ in range(6))


async def squad_of(conn, learner_id: int) -> dict | None:
    row = await conn.fetchrow(
        "SELECT s.code, s.grade, s.paper_id, s.host_learner_id FROM squads s "
        "JOIN squad_members m ON m.squad_code = s.code WHERE m.learner_id = $1", learner_id)
    return dict(row) if row else None


async def create_squad(conn, learner_id: int, grade: int) -> str:
    for _ in range(5):
        code = new_code()
        done = await conn.fetchval(
            "INSERT INTO squads (code, grade, host_learner_id) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING RETURNING code", code, grade, learner_id)
        if done:
            await conn.execute("DELETE FROM squad_members WHERE learner_id = $1", learner_id)
            await conn.execute("INSERT INTO squad_members (squad_code, learner_id) VALUES ($1, $2)",
                               code, learner_id)
            return code
    raise RuntimeError("could not allocate a squad code")


async def join_squad(conn, learner_id: int, grade: int, code: str) -> str | None:
    """None on success, else the reason it failed."""
    sq = await conn.fetchrow("SELECT code, grade FROM squads WHERE code = $1", code.upper())
    if not sq:
        return "I couldn't find that squad code. Check it with your friend and try again."
    if sq["grade"] != grade:
        return f"That squad is for Grade {sq['grade']}, and squads are one grade each."
    n = await conn.fetchval("SELECT count(*) FROM squad_members WHERE squad_code = $1", sq["code"])
    if n >= 8:
        return "That squad is full (8 learners)."
    await conn.execute("DELETE FROM squad_members WHERE learner_id = $1", learner_id)
    await conn.execute("INSERT INTO squad_members (squad_code, learner_id) VALUES ($1, $2)",
                       sq["code"], learner_id)
    return None


async def squad_results(conn, code: str, paper_id: str | None) -> str:
    rows = await conn.fetch(
        """
        SELECT l.nickname, a.awarded, a.out_of, a.results
        FROM squad_members m JOIN learners l ON l.id = m.learner_id
        LEFT JOIN LATERAL (
            SELECT awarded, out_of, results FROM paper_attempts
            WHERE learner_id = m.learner_id AND squad_code = $1
              AND ($2::text IS NULL OR paper_id = $2) ORDER BY finished_at DESC LIMIT 1
        ) a ON true
        WHERE m.squad_code = $1 ORDER BY a.awarded DESC NULLS LAST, l.nickname
        """, code, paper_id)
    title = get(paper_id)["title"] if paper_id and get(paper_id) else "squad paper"
    lines = [f"👥 *Squad {code}* · {title}"]
    hard: dict[str, list[int]] = {}
    for r in rows:
        if r["out_of"]:
            lines.append(f"• {r['nickname']}: {r['awarded']}/{r['out_of']}")
            for x in json.loads(r["results"]):
                if x["topic"] and not x["helped"] and not x["skipped"]:
                    h = hard.setdefault(x["topic"], [0, 0])
                    h[0] += x["awarded"]
                    h[1] += x["of"]
        else:
            lines.append(f"• {r['nickname']}: not finished yet")
    if hard:
        t = min(hard, key=lambda k: hard[k][0] / hard[k][1])
        lines.append(f"\nHardest topic for the squad: *{t}* ({hard[t][0]}/{hard[t][1]}). "
                     f"Work on it together, or send PAPER {t}.")
    return "\n".join(lines)
