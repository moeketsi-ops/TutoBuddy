"""Generates docs/branch-update-2026-09-26.pdf — run via Docker, see README."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, KeepTogether)

pdfmetrics.registerFont(TTFont("AU", "/fonts/ArialUnicode.ttf"))
GREEN, INK, MUTED, LINE = colors.HexColor("#0b6e4f"), colors.HexColor("#17241d"), colors.HexColor("#55665c"), colors.HexColor("#d8e0d9")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("h1", fontName="AU", fontSize=20, leading=24, textColor=INK, spaceAfter=4)
SUB = ParagraphStyle("sub", fontName="AU", fontSize=10, leading=14, textColor=MUTED, spaceAfter=14)
H2 = ParagraphStyle("h2", fontName="AU", fontSize=13, leading=16, textColor=GREEN, spaceBefore=14, spaceAfter=6)
P = ParagraphStyle("p", fontName="AU", fontSize=9.5, leading=13.5, textColor=INK, spaceAfter=5)
B = ParagraphStyle("b", parent=P, leftIndent=10, bulletIndent=0, spaceAfter=3)
CODE = ParagraphStyle("code", fontName="Courier", fontSize=8.3, leading=11, textColor=INK,
                      backColor=colors.HexColor("#f4f6f2"), borderPadding=(5, 6, 5, 6), leftIndent=4, spaceAfter=8)
TC = ParagraphStyle("tc", fontName="AU", fontSize=8.5, leading=11.5, textColor=INK)
TH = ParagraphStyle("th", fontName="AU", fontSize=8, leading=10, textColor=MUTED)

def p(t, s=P): return Paragraph(t, s)
def bullets(items): return [Paragraph(f"• {t}", B) for t in items]
def code(t): return Paragraph(t.replace(" ", "&nbsp;").replace("\n", "<br/>"), CODE)
def table(rows, widths):
    data = [[Paragraph(c, TH) for c in rows[0]]] + [[Paragraph(c, TC) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE), ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t

story = [
    p("Katlego — branch update for Moeketsi", H1),
    p("Branch <b>moeketsi/household-safety-pedagogy</b> on immanueln98/TutoBuddy · prepared by Immanuel (with Claude) · 26 September 2026", SUB),

    p("Summary", H2),
    p("Your branch was pulled into the shared Docker environment, run end to end, and verified against the database rather than the "
      "progress summary alone. It is good work and is now the working branch. Seven commits sit on top of yours: a router fix that "
      "unblocked the practice loop, tighter tests, Grade 8 tutoring content, an honest POPIA notice, doc updates, and two product "
      "decisions Immanuel has taken (below). The suite is green at <b>27 / 27</b>."),

    p("1. Verification of your branch (as pushed, commit 9db5b34)", H2),
    *bullets([
        "Fresh database (your branch reshapes <b>learners</b>, so the destructive migration was skipped in favour of a reset). Clean boot, no schema errors.",
        "<b>20 / 21 tests passed.</b> The failure: in stub (keyless) mode the intent router never returned <i>quiz</i>, so 'quiz me' hit the smalltalk reply and the practice → grade → mastery loop was unreachable. <b>learner_topic_mastery</b> stayed empty.",
        "<b>test_skip_clears_pending_without_grading</b> passed by accident — the 'no practice question waiting to be skipped' reply contains the word 'skipped'.",
        "Safeguarding verified: flags persist in <b>safeguarding_flags</b>; with no alert number set the CRITICAL log fires as designed. Output sanitiser and PII redaction behave as documented.",
        "DELETE left the phone number in <b>account_channels</b> and six pre-consent chat rows (learner_id NULL) — the consent text's 'delete everything' was not true.",
        "All curriculum, past papers, progress and practice data are Grade 8 only; a Grade 8 learner asking an ordinary homework question got the 'couldn't find that topic' fallback because <b>caps_chunks</b> held only Gr 10–12 notes.",
        "Your test docstring said Term 3 only; topics exist in all four terms (4 / 4 / 6 / 7).",
    ]),

    p("2. Commits added on top of yours", H2),
    table([
        ["Commit", "Change"],
        ["1da4cf2", "Stub intent router recognises quiz / practice / test-me requests."],
        ["f5b40da", "SKIP test asserts the real confirmation; stale docstrings fixed."],
        ["6d3efba", "Grade 8 pilot: 12 CAPS notes using your topic names verbatim, 8 Grade 8 golden eval questions, a Grade 8 tutoring test."],
        ["c6ba628", "POPIA consent notice describes what DELETE actually erases."],
        ["23e3995", "README: four-step onboarding, curriculum / past-paper loaders, the compose-profiles build gotcha. Pitch page updated."],
        ["0ba77c5", "<b>Decision:</b> erasing the last learner drops the whole household (account, channels, guardians, all phone-scoped chat rows, Redis session). Siblings unchanged. Tests check DB row counts."],
        ["efa8ed1", "<b>Router tier:</b> optional ROUTER_PROVIDER=jev (TypeSafe AI) with confidence-threshold fallback, plus a router bake-off harness."],
    ], [22 * mm, 148 * mm]),

    p("3. Decisions taken", H2),
    *bullets([
        "<b>Grade 8 Mathematics is the pilot.</b> The blueprint's Gr 11–12 wedge is deferred. Your curriculum graph and papers are the pilot content.",
        "<b>DELETE on the last learner erases the household.</b> Your idempotent create_household() still means RESET + AGREE lands on the existing household; only DELETE-of-last-learner removes it. safeguarding_flags are kept, as you designed.",
        "<b>Jev for intent routing only</b> (not tutoring, grading or photos). Safety classification via Jev is the natural next candidate but is not built.",
    ]),

    p("4. Router bake-off — how to run it", H2),
    p("Jev is a typed-decision model: it returns a choice with calibrated probabilities, not text, in roughly 70–500 ms at $0.042 per million "
      "input tokens. Access is waitlisted early access (typesafe.ai → console.typesafe.ai). The harness measures every available router on "
      "40 labelled learner messages (SA English, isiZulu/Sepedi code-switching, typos, WhatsApp shorthand) and reports accuracy, per-intent "
      "recall, latency, and for Jev accuracy-by-confidence (the calibration claim) and cost."),
    code("docker compose run --rm evals python -m evals.router_eval"),
    p("Result today with no keys: the keyword stub scores <b>52 %</b> — it never detects admin intent and misses most quiz phrasing. That is the "
      "floor a real router must beat. Add ANTHROPIC/GROQ/OPENROUTER keys to measure an LLM router, TYPESAFE_API_KEY to measure Jev, then set "
      "ROUTER_PROVIDER=jev and JEV_MIN_CONFIDENCE from the confidence table."),

    p("5. Sync your copy", H2),
    p("Your GitHub repo (moeketsi-ops/TutoBuddy) is a standalone copy, not a fork, so there is no link back. Point it at Immanuel's repo, "
      "where you are a collaborator, and reset your branch onto the shared one:"),
    code("git remote add upstream https://github.com/immanueln98/TutoBuddy.git\ngit fetch upstream\ngit checkout moeketsi/household-safety-pedagogy\ngit reset --hard upstream/moeketsi/household-safety-pedagogy"),
    p("Then rebuild — the profiled services are not rebuilt by <b>up --build</b>, exactly the gotcha you documented:"),
    code("docker compose down && docker volume rm tutobuddy_pgdata\ndocker compose up --build -d\ndocker compose build seed tests evals\ndocker compose run --rm seed\ndocker compose run --rm seed python -m seed.load_curriculum\ndocker compose run --rm seed python -m seed.load_past_papers\ndocker compose run --rm tests"),

    KeepTogether([
        p("6. Asks for you", H2),
        *bullets([
            "Commit the design docs your docstrings cite to <b>docs/</b>: household-account-model-phase1-plan, technical-blueprint-reconciliation, database-merge-decision, past-papers-ocr-pipeline, dynamic-pedagogy-engine-design. They are the rationale for half the branch and are not in the repo.",
            "Provider refactor: six LLM functions × four provider branches (~500 lines). Groq, OpenRouter and Ollama are all OpenAI-style chat calls; one shared helper collapses most of it. Yours to do since it is your file.",
            "Per-tier provider split (a REASONER_PROVIDER separate from the router) — the follow-up you already identified; the router tier now exists in app/adapters/router.py to hang it on.",
            "Reconcile question_bank.cognitive_level (free text) with cognitive_level_weights.level_name (enum).",
            "Run <b>docker compose run --rm tests</b> before pushing — the router failure would have shown up immediately.",
        ]),
    ]),
]

doc = SimpleDocTemplate("/w/docs/branch-update-2026-09-26.pdf", pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=18 * mm, bottomMargin=18 * mm, title="Katlego branch update 2026-09-26", author="Immanuel Nanyaro")
doc.build(story)
print("pdf written")
