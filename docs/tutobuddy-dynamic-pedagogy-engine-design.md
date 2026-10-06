# Dynamic Pedagogy Engine — design note

Status: conceptual design, saved verbatim per founder's request ("keep this for pedagogy"). Build has started — see "Relationship to what's already built" at the end for the current increment.

Note: the source material cites a "SchoolNet" resource ([SchoolNet][1]–[5]) without resolvable URLs — those citations are unverified and should be tracked down (or dropped) before this is used in anything investor- or partner-facing.

## Core framing

Turn TutoBuddy's teaching logic into a **Dynamic Pedagogy Engine**: a system that continuously decides *how Katlego should teach this learner, right now*, based on the learner's knowledge, preferences, behaviour, response to the current method, and the learning objective.

Guiding principle:

> Katlego has an infinitely patient lens, but not an infinitely permissive one.

Katlego never gets frustrated, never labels a learner as incapable, and never abandons an objective — but it also doesn't just keep repeating easier explanations forever. It changes representation, strategy, questioning style, examples, scaffolding and practice until it finds an effective path to understanding.

## 1. Pedagogy as an operating system, not a list

```text
                         TUTOBUDDY
                             │
                    ┌────────┴────────┐
                    │                 │
              WHAT to teach       WHO is learning
                    │                 │
             Curriculum Graph     Learner Model
                    │                 │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ MASTERY ENGINE  │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ PEDAGOGY ENGINE │
                    └────────┬────────┘
                             ↓
                 "HOW should I teach?"
                             │
          ┌──────────────────┼──────────────────┐
          ↓                  ↓                  ↓
     Strategy           Interaction         Difficulty
     selection             style             / pace
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ↓
                         KATLEGO
                             ↓
                        Learner
                             ↓
                    Observe response
                             ↓
                     UPDATE LEARNER
                             ↓
                     RESELECT STRATEGY
```

The closed loop (observe → update learner model → reselect strategy) is the key departure from a static prompt: pedagogy becomes an adaptive system, not a fixed persona instruction.

## 2. Expanded learner model

```text
LEARNER MODEL
│
├── Knowledge
│   ├── mastery
│   ├── prerequisites
│   ├── misconceptions
│   └── knowledge gaps
│
├── Learning preferences
│   ├── prefers examples / explanations / visuals
│   ├── prefers worked examples / questioning / experimentation
│   └── preferred language
│
├── Behaviour
│   ├── persistence, response time, hint dependence
│   ├── independent attempts, abandonment, engagement
│
├── Cognitive signals
│   ├── misconception patterns, reasoning quality
│   ├── transfer ability, explanation ability
│
└── Session state
    ├── current objective / strategy / difficulty / hint level
    └── emotional/engagement signals* (observable conversational
        signals only — "I'm confused", repeated errors,
        disengagement — never inferred mental-state diagnosis)
```

## 3. Learning style is dynamic, not a fixed label

Don't store `learner = visual learner`. Instead track effectiveness per learner × concept × context:

| Strategy             | Fractions | Algebra | Geometry |
| --------------------- | --------: | ------: | -------: |
| Worked example        |       +++ |      ++ |        + |
| Visual diagram         |        ++ |       + |      +++ |
| Socratic questioning   |         + |     +++ |       ++ |
| Real-world example     |        ++ |     +++ |       ++ |
| Independent practice   |       +++ |      ++ |       ++ |

The system learns something like "this learner currently responds well to worked examples for algebra, but conceptual diagrams appear more effective for geometry" — and the preference should shift within a single session (e.g. wants an example at the start of a hard topic, then wants to be left to attempt independently once the concept lands).

## 4. Pedagogical Strategy Library (machine-selectable)

```text
01 PRIOR_KNOWLEDGE_ACTIVATION      12 ERROR_ANALYSIS
02 SOCRATIC_QUESTIONING            13 GUIDED_PRACTICE
03 CLARIFICATION_QUESTION          14 INDEPENDENT_PRACTICE
04 ELABORATION                     15 RETRIEVAL_PRACTICE
05 WORKED_EXAMPLE                  16 PEER_EXPLANATION
06 THINK_ALOUD                     17 PEER_FEEDBACK
07 SCAFFOLDED_EXAMPLE              18 SELF_EXPLANATION
08 CONCEPT_MAP                     19 REFLECTION
09 SEQUENCING                      20 SPACED_REVIEW
10 ANALOGY                         21 RECOGNITION
11 COUNTEREXAMPLE                  22 MISCONCEPTION_REMEDIATION
```

Each strategy carries metadata, e.g.:

```json
{
  "strategy": "SOCRATIC_QUESTIONING",
  "best_for": ["conceptual_reasoning", "misconception_detection", "independent_thinking"],
  "avoid_when": ["learner_has_no_prerequisite_knowledge", "learner_requests_direct_explanation"],
  "requires": ["minimum_prior_knowledge"],
  "learner_effort": "high",
  "scaffolding": "low_to_medium"
}
```

This makes pedagogy programmable rather than left to LLM improvisation.

## 5. The Infinitely Patient Lens (proposed TutoBuddy principle)

> Every incorrect response is treated as information about the learner's current understanding, not as evidence of inability.

Katlego should never: get frustrated, shame the learner, repeatedly restate the same explanation, assume lack of intelligence, rush unnecessarily, reveal the answer merely because the learner struggled, or permanently label a learner from one interaction.

Instead:

```text
WRONG ANSWER → What did the learner understand? → Where did reasoning
diverge? → Is prerequisite knowledge missing? → Has this strategy
already failed? → Try a different representation → Check
understanding → Try again
```

Key distinction: **patience ≠ repetition**. If an explanation fails twice, don't give a near-identical fourth attempt — change the approach.

## 6. Strategy-failure detector

If a strategy has been tried with negligible improvement over N attempts, stop repeating it and switch representation:

```text
Explanation → Worked example → Visual representation → Analogy →
Guided question → Learner attempt
```

The engine should continuously ask "is this teaching strategy working?", not just "did the learner get the question right?"

## 7. Separate objective from strategy

```text
                    OBJECTIVE
              Solve simultaneous equations
        ┌───────────────┼────────────────┐
        ↓               ↓                ↓
   Worked example   Graphical        Real-world
                    method            problem
        └───────────────┼────────────────┘
                  Guided practice → Independent task
```

Curriculum determines the destination. Pedagogy determines the route. Learner feedback determines whether the route changes.

## 8. Multiple paths to mastery

For objectives that permit it, don't require reproduction of one canonical method — accept multiple valid routes to the same solution (e.g. solving `2x + 5 = 17` algebraically, via inverse operations, via a balance model, or mentally). The mastery engine should ask "can the learner reliably reason to a valid solution?", not "did they reproduce Katlego's method?" — this supports genuine understanding over procedural mimicry.

## 9. Bounded exploration budget

To avoid infinite wandering when a learner struggles:

```text
Objective → Primary strategy → struggle → Alternative #1 → response →
Alternative #2 → response → identify effective strategy → consolidate
```

Track `strategy_effectiveness` per learner × objective, e.g.:

```json
{
  "learner": "L1024",
  "objective": "ALG-EQUATIONS-001",
  "strategies": {
    "worked_example": 0.82,
    "socratic": 0.63,
    "visual_balance": 0.91,
    "analogy": 0.54
  }
}
```

## 10. Prior knowledge before intervention

Before teaching a new topic, diagnose what the learner already knows (e.g. "before we start, what do you remember about linear functions?") and use that to pick the entry point:

```text
PRIOR KNOWLEDGE → DIAGNOSE → SELECT ENTRY POINT → TEACH → PRACTICE →
OBSERVE → ADAPT
```

## 11. Questioning hierarchy

Don't just instruct the LLM to "use Socratic questioning" — give it typed question categories to select from based on learner state: Recall, Clarification, Connection, Prediction, Justification, Comparison, Transfer, Metacognition.

## 12. Wait time on WhatsApp

An AI can respond instantly, but instant isn't always pedagogically optimal. After asking a thinking question, Katlego shouldn't immediately hint if the learner hasn't replied yet. Proposed interaction modes: "Thinking mode" (take your time, send your first idea when ready), "Hint mode" (want a small hint?), "Explain mode" (I can walk through it with you) — makes "infinitely patient" tangible rather than just stated.

## 13. Structured feedback object

Rather than letting the LLM improvise feedback each time, enforce a structure:

```json
{
  "feedback": {
    "acknowledge": true,
    "identify_correct": ["correctly identified the variable"],
    "identify_error": ["incorrect application of distributive law"],
    "next_action": "attempt_correction",
    "reveal_answer": false
  }
}
```

Pattern: correct → explain what was correct → identify improvement → next attempt.

## 14. Specific recognition over generic praise

Avoid generic "Great job! 🎉". Recognise specific learning behaviours instead: "You caught your own mistake before I pointed it out," "You changed your approach when the first method didn't work," "Your explanation shows you understand *why* the answer works, not just what the answer is."

## 15. Study Rooms as an extension of the same engine

```text
INDIVIDUAL PEDAGOGY + PEER PEDAGOGY + KATLEGO FACILITATION → STUDY ROOM
```

Rather than "high-mastery learner teaches low-mastery learner" directly, a phased structure: (1) everyone attempts independently, (2) compare approaches across learners who used different methods, (3) a learner explains their reasoning to peers, (4) another learner attempts a new problem, (5) Katlego synthesizes the underlying principle. This is closer to reciprocal/cooperative learning than broadcast tutoring.

Note: Study Rooms remain blocked on WhatsApp Official Business Account Groups API access per `tutobuddy-account-model-household-learners.md` — this section is the pedagogical design to build toward once that access exists, not a near-term build item.

## 16. Adaptive intervention threshold

Replace a fixed rule like "Katlego intervenes after 2 uncorrected turns" with a weighted score:

```text
INTERVENTION SCORE =
  error severity + misconception confidence + learner confusion signal
  + peer correction quality + time/stagnation + safety relevance

LOW → observe
MEDIUM → probing question
HIGH → hint
VERY HIGH → structured explanation
```

## 17. Pedagogy Decision Object

Proposed shape for what the backend hands the LLM each turn, so the LLM executes a pedagogical decision rather than inventing one:

```json
{
  "learner": {
    "mastery": 0.46,
    "confidence": 0.71,
    "independence": 0.38,
    "misconception": "distribution_law"
  },
  "objective": {
    "id": "ALG-08-003",
    "required_mastery": 0.80
  },
  "session": {
    "attempt": 4,
    "strategy": "worked_example",
    "strategy_effectiveness": 0.32,
    "engagement": 0.74
  },
  "preferences": {
    "visual": 0.82,
    "examples": 0.77,
    "questioning": 0.51
  },
  "pedagogy": {
    "action": "CHANGE_REPRESENTATION",
    "strategy": "VISUAL_MODEL",
    "hint_level": 1,
    "require_learner_attempt": true,
    "reveal_solution": false
  }
}
```

## 18. Full loop, end to end

```text
CURRICULUM OBJECTIVE → PRIOR KNOWLEDGE → DIAGNOSE → SELECT ENTRY POINT
→ SELECT TEACHING METHOD → MODEL / QUESTION / EXAMPLE → LEARNER ATTEMPT
→ OBSERVE →
   UNDERSTANDING → INCREASE COMPLEXITY  \
   MISCONCEPTION  → CHANGE STRATEGY      >→ NEW ATTEMPT → MICRO-CHECK
                                         /
→ MASTERY? → NO → REMEDIATE ─┐
           → YES → CONSOLIDATE ┴→ TRANSFER / APPLY → SPACED REVIEW
```

Wrapped around all of it: the Infinitely Patient Lens — observe → understand → adapt → try again (never wrong → answer → next question).

## 19. Proposed Pedagogical Constitution (11 principles)

- **P1 — Curriculum fidelity**: teach toward a defined curriculum objective.
- **P2 — Prior knowledge first**: determine what the learner already knows before selecting the entry point.
- **P3 — Learner-adaptive**: adapt method, representation, pace and scaffolding based on observed behaviour.
- **P4 — Multiple pathways**: allow multiple valid reasoning/problem-solving approaches where the discipline permits.
- **P5 — Productive struggle**: don't remove all difficulty; scaffold enough for the learner to keep thinking.
- **P6 — Anti-offloading**: prefer learner thinking, prediction, explanation and attempts over immediate answers.
- **P7 — Infinitely patient**: failure is information; change the approach rather than blaming the learner.
- **P8 — Explicit feedback**: identify what's correct, what needs improvement, and what to try next.
- **P9 — Metacognition**: regularly ask the learner to explain *how* they thought, not just what answer they got.
- **P10 — Mastery before progression**: progress on demonstrated understanding and independent performance, not completion.
- **P11 — The learner can teach Katlego**: invert the relationship sometimes — "pretend I'm a learner who doesn't understand X, teach me how you'd solve this" — a different, useful mastery signal, and a natural fit with Study Room orchestration where learners explain to each other while Katlego facilitates.

## Summary framing

> TutoBuddy does not have one way of teaching. It has a curriculum destination, a model of the learner, a library of pedagogical strategies, and a continuous decision loop that discovers the most effective path to mastery for that learner.

> Katlego is infinitely patient: when a learner struggles, Katlego does not simply repeat the answer. It changes the question, representation, example, explanation, pace, scaffold or learning activity until the learner can make the connection themselves.

## Relationship to what's already built

**Increment 1 (shipped, commit `8c9985b`): closing the mastery loop.** Before this, mastery scores in `learner_topic_mastery` were permanently empty — nothing wrote to them, only read from them (`get_term_progress`, band-based practice difficulty). That's now fixed: a learner's answer to a practice question ("quiz me") is graded (correct/partial/incorrect, against a ground-truth answer the LLM captures when it writes the question) and updates that learner's mastery score for the topic, with every attempt logged to a new `learner_practice_attempts` table. Full detail in `tutobuddy-pedagogy-mastery-pace-step.md`'s "Mastery loop closed" section.

This was deliberately chosen as the first increment, ahead of anything else in this document, because sections 8, 9, 13 and 16 below all assume mastery moves in response to real performance — building strategy-effectiveness tracking or an intervention score against permanently-empty mastery data would have been new plumbing with nothing flowing through it.

**Still not built**: the strategy library (section 4) and any strategy selection logic — `tutor_reply` still has no notion of "which pedagogical strategy is this reply using"; per-strategy effectiveness tracking (section 9) — there's no mechanism yet recording which strategy was tried, only whether the final answer was right; the learner preference model (section 2/3); the pedagogy decision object (section 17); the adaptive intervention threshold (section 16); wait-time/interaction modes (section 12); the richer structured feedback object (section 13 — what shipped in increment 1 is a minimal correct/partial/incorrect + one-line feedback, not the full acknowledge/identify_correct/identify_error/next_action shape); and Study Room facilitation (section 15, separately blocked on WhatsApp Groups API access).

Natural next increment candidates, in roughly the order they'd unlock further pieces: (a) tag which strategy a given `tutor_reply`/practice question used, so effectiveness can be tracked per learner × topic × strategy once there's enough attempt volume; (b) the structured feedback object, since the plumbing for grading is now in place and this only touches `grade_practice_system`'s output shape; (c) the intervention-score threshold, which needs the strategy tag from (a) as one of its inputs. Not yet asked which to build next — flagging for that decision when it comes up.
