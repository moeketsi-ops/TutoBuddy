"""Unit tests for CPA + TMU switching (spec "Katlego CPA + mastery
switching v0.1"). Pure functions only: no database, Redis or model."""

import random

import pytest

from app.tutor import answer_check, memory, pedagogy, representation, tmu
from app.tutor.mastery import evidence_weight
from app.tutor.state import parse_state, parse_turn, turn_schema

P8 = "How do I solve 3x + 4 = 19?"
P12 = "Solve log2(x) = 5"


# ── Code-side answer checking ────────────────────────────────────────────────

@pytest.mark.parametrize("reply,verdict", [
    ("x = 5", "correct"), ("5", "correct"), ("x=5", "correct"),
    ("3x = 15", "step_forward"), ("3x=15", "step_forward"),
    ("x = 7", "wrong"), ("3x = 23", "wrong"),
    ("minus 5?", None), ("I don't get it", None), ("just give me the answer", None),
])
def test_grade8_equation_attempts(reply, verdict):
    got = answer_check.check(P8, reply)
    assert (got or {}).get("verdict") == verdict


@pytest.mark.parametrize("reply,verdict", [
    ("x = 10", "wrong"),      # the first run's misread attempt: wrong, not off-topic
    ("x = 2^5", "correct"),   # an exact form is accepted
    ("x = 32", "correct"), ("32", "correct"), ("x = 2.5", "wrong"),
])
def test_grade12_log_attempts(reply, verdict):
    assert answer_check.check(P12, reply)["verdict"] == verdict


def test_one_root_of_a_quadratic_is_a_step_not_the_answer():
    assert answer_check.check("Solve x^2 - 5x + 6 = 0", "x = 3")["verdict"] == "step_forward"


@pytest.mark.parametrize("reply", ["__import__('os').system('ls')", "x = exec(1)", "lambda: 1",
                                   "x = " + "9" * 200])
def test_learner_text_never_reaches_the_parser_unsafely(reply):
    assert answer_check.check(P8, reply) is None


def test_no_checkable_problem_means_no_verdict():
    assert answer_check.check("What is a function?", "x = 3") is None
    assert answer_check.check(None, "x = 3") is None


def test_prompt_line_tells_the_model_it_is_an_attempt():
    line = answer_check.prompt_line(answer_check.check(P12, "x = 10"))
    assert "IS an attempt" in line and "NOT correct" in line and "Do not reveal" in line


# ── CPA levels ───────────────────────────────────────────────────────────────

def test_start_level_from_mastery_then_from_the_learner():
    assert representation.start_level(30)[0] == "pictorial"   # remediate band
    assert representation.start_level(70)[0] == "abstract"
    lv, why = representation.start_level(70, {"pictorial": (4, 4), "abstract": (3, 0)})
    assert lv == "pictorial" and "4/4" in why
    assert representation.start_level(70, {"concrete": (1, 1)})[0] == "abstract"  # 1 try isn't enough


def test_level_steps_and_instructions():
    assert representation.step_down("abstract") == "pictorial"
    assert representation.step_down("concrete") == "concrete"
    assert "emoji" in representation.instruction("concrete", 8).lower()
    assert "real context" in representation.instruction("concrete", 12)
    assert "Emoji rules" not in representation.instruction("abstract", 8)


# ── The switching rule ───────────────────────────────────────────────────────

def _base(strategy="SOCRATIC_QUESTIONING"):
    return {"strategy": strategy, "why": "keep going", "hint": 1, "reveal": False,
            "require_attempt": True}


def _plan(**kw):
    args = dict(current_strategy="SOCRATIC_QUESTIONING", level="abstract", no_progress=0,
                switches_used=0, asked_other_way=False, tried=["SOCRATIC_QUESTIONING"],
                stats={}, rng=random.Random(1), code_verdict=None)
    args.update(kw)
    return pedagogy.plan_switch(_base(), **args)


def test_no_switch_before_three_turns_without_progress():
    d = _plan(no_progress=1)
    assert d["switch"] is None and d["level"] == "abstract"


def test_first_switch_changes_level_and_keeps_strategy():
    d = _plan(no_progress=3)
    assert d["switch"] == "level" and d["level"] == "pictorial"
    assert d["strategy"] == "SOCRATIC_QUESTIONING" and d["switches_used"] == 1


def test_second_switch_changes_strategy_at_the_new_level():
    d = _plan(no_progress=3, switches_used=1, level="pictorial")
    assert d["switch"] == "strategy" and d["level"] == "pictorial"
    assert d["strategy"] != "SOCRATIC_QUESTIONING" and d["switches_used"] == 2


def test_after_two_switches_a_worked_example_on_a_similar_problem():
    d = _plan(no_progress=3, switches_used=2, level="pictorial")
    assert d["switch"] == "worked_example" and d["strategy"] == "WORKED_EXAMPLE"
    assert d["reveal"] is False and d["restart"] is True
    assert "SIMILAR problem" in pedagogy.decision_line(d, 8)


def test_a_code_checked_wrong_answer_counts_this_turn():
    assert _plan(no_progress=2, code_verdict="wrong")["switch"] == "level"
    assert _plan(no_progress=2, code_verdict="step_forward")["switch"] is None


def test_asking_for_another_way_switches_at_once():
    d = _plan(no_progress=0, asked_other_way=True)
    assert d["switch"] == "level" and d["trigger"] == "asked_other_way"


def test_one_turn_before_the_threshold_the_model_gets_a_fallback():
    d = _plan(no_progress=2)
    assert d["switch"] is None and d["fallback_level"] == "pictorial"
    assert "switch to level=pictorial" in pedagogy.decision_line(d, 8)


def test_a_correct_answer_closes_instead_of_switching():
    d = _plan(no_progress=5, code_verdict="correct")
    assert d.get("close") is True and d["switch"] is None


def test_about_one_in_ten_first_switches_explore():
    picks = [pedagogy.plan_switch(_base(), current_strategy="SOCRATIC_QUESTIONING", level="abstract",
                                  no_progress=3, switches_used=0, asked_other_way=False,
                                  tried=[], stats={}, rng=random.Random(i))["chosen_by"]
             for i in range(2000)]
    share = picks.count("random") / len(picks)
    assert 0.07 < share < 0.13


def test_decision_line_carries_level_bridge_and_methods():
    d = {**_plan(), "bridge": True,
         "methods": tmu.methods_line(tmu.find_methods(P8, 8))}
    line = pedagogy.decision_line(d, 8)
    assert "level=abstract" in line and "BRIDGE" in line and "METHODS" in line


# ── Working memory: the no-progress count ───────────────────────────────────

def _turn(mem, text, ev, progress=None, step=None):
    st = {"ev": ev, "lo": None, "misc": None, "hint": 0, "step": step, "progress": progress,
          "level": None}
    memory.record_turn(mem, text, "ok?", st, {"id": 1, "name": "Equations"}, "SOCRATIC_QUESTIONING")


def test_no_progress_counts_resets_and_closes():
    mem = memory._new(7)
    memory.record_turn(mem, P8, "What first?", {"ev": "none"}, {"id": 1, "name": "Equations"},
                       "SOCRATIC_QUESTIONING", new_problem=True)
    _turn(mem, "x = 7", "attempt_wrong")
    _turn(mem, "I don't get it", "none")
    assert mem["working"]["no_progress"] == 2
    _turn(mem, "3x = 15", "attempt_partial", "step_forward")
    assert mem["working"]["no_progress"] == 0
    _turn(mem, "x = 5", "attempt_correct", "solved")
    # solved: open one more turn for the learner's echo (870fc2b), then closed
    assert mem["working"]["problem"] == P8 and mem["working"]["closing"]
    _turn(mem, "x = 5 yes", "attempt_correct")
    assert mem["working"]["problem"] is None


def test_old_memory_gets_the_new_fields():
    mem = memory._new(7)
    for k in ("level", "no_progress", "switches", "bridge"):
        mem["working"].pop(k)
    w = memory.ensure_working(mem)
    assert w["no_progress"] == 0 and w["level"] is None


def test_learner_signals():
    assert memory.asks_other_way("can you show me another way?")
    assert memory.asks_other_way("Explain it differently please")
    assert not memory.asks_other_way("x = 4")
    assert memory.is_confused("I still don't understand")


# ── TMU strands and methods ──────────────────────────────────────────────────

def test_methods_follow_topic_and_grade():
    assert tmu.find_methods(P8, 8)["id"] == "linear-equations"
    assert tmu.find_methods(P12, 12)["id"] == "logarithms"
    assert tmu.find_methods("complete the square x^2 + 6x", 10)["id"] == "completing-the-square"
    assert tmu.find_methods("complete the square x^2 + 6x", 8) is None or \
        tmu.find_methods("complete the square x^2 + 6x", 8)["id"] != "completing-the-square"
    for e in tmu.library():
        assert e["methods"] and e["source"] and e["strand"] in tmu.STRANDS


def test_strand_tagging():
    assert tmu.strand_for("SOCRATIC_QUESTIONING", "attempt_correct", "abstract") == "procedural_fluency"
    assert tmu.strand_for("SOCRATIC_QUESTIONING", "attempt_correct", "pictorial") == "conceptual_understanding"
    assert tmu.strand_for("JUSTIFY_AND_CHECK", "attempt_correct", "abstract") == "reasoning"
    assert tmu.strand_for("MULTIPLE_METHODS", "attempt_partial", "abstract") == "strategic_competence"
    assert tmu.strand_for("WORKED_EXAMPLE", "none", "abstract") is None
    assert set(tmu.STRATEGY_STRAND) >= set(pedagogy.STRATEGIES)


# ── Mastery weights by level ─────────────────────────────────────────────────

def test_success_below_abstract_counts_for_less():
    _, full = evidence_weight("chat", "attempt_correct", 0, "abstract")
    _, pic = evidence_weight("chat", "attempt_correct", 0, "pictorial")
    _, con = evidence_weight("chat", "attempt_correct", 0, "concrete")
    assert full > pic > con > 0
    assert evidence_weight("chat", "attempt_wrong", 0, "concrete") == evidence_weight("chat", "attempt_wrong", 0)


# ── State record ─────────────────────────────────────────────────────────────

def test_state_carries_level_and_progress():
    st = parse_state({"ev": "attempt_partial", "lo": "none", "misc": "none",
                      "strat": "VISUAL_MODEL", "hint": "1", "step": "2/3",
                      "level": "pictorial", "progress": "step_forward"},
                     lo_codes=set(), misconception_codes=set(), strategies=set(pedagogy.STRATEGIES))
    assert st["level"] == "pictorial" and st["progress"] == "step_forward" and st["valid"]
    bad = parse_state({"ev": "none", "strat": "VISUAL_MODEL", "level": "telepathy"},
                      lo_codes=set(), misconception_codes=set(), strategies=set(pedagogy.STRATEGIES))
    assert bad["level"] is None


def test_schema_requires_the_new_fields():
    sch = turn_schema([], [], list(pedagogy.STRATEGIES))["properties"]["state"]
    assert {"level", "progress"} <= set(sch["required"])


def test_broken_json_reply_never_shows_backslash_n():
    reply, _, _ = parse_turn('{"state": {"ev": "none"}, "reply": "Nice!\\n\\nNow try \\q"')
    assert "\\n" not in reply and "Nice!\n\nNow try" in reply


def test_both_roots_named_is_correct_one_is_a_step():
    q = "Solve x^2 - 7x + 12 = 0"
    assert answer_check.check(q, "x = 3 or x = 4")["verdict"] == "correct"
    assert answer_check.check(q, "x = 3")["verdict"] == "step_forward"
    assert answer_check.check(q, "x = 3, x = 5")["verdict"] == "wrong"


def test_explanations_in_words_are_left_to_the_model():
    assert answer_check.check("Solve 6x = 42", "6 times 7 is 42 so x = 42 divided by 6") is None


def test_another_way_and_confusion_stay_on_the_problem():
    mem = memory._new(7)
    memory.record_turn(mem, P8, "What first?", {"ev": "none"}, {"id": 1, "name": "Equations"},
                       "SOCRATIC_QUESTIONING", new_problem=True)
    assert memory.continues_problem(mem, "can you show me another way?")
    assert memory.continues_problem(mem, "Can you explain it differently?")
    assert memory.continues_problem(mem, "I still don't understand")
    assert not memory.continues_problem(mem, "How do I add 1/3 and 1/6?")
