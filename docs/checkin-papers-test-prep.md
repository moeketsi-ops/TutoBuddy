# Sign-up check-in, real past papers, test prep and study squads (5 Nov 2026)

Founder decisions for this round: the check-in covers every topic in the
grade and scores every topic the same; its questions come from a fixed bank
that a maths teacher reviews before the pilot; a starter set of past papers
is converted by hand for checking; a coming test is known from what the
learner says, with the ATP as the fallback.

## 1. Sign-up check-in (`app/tutor/diagnostic.py`)

- Starts in the same message as the welcome, straight after the grade.
- One multiple-choice "core" question per CAPS topic (Grade 8: 22, Grade 10: 13,
  Grade 11: 12, Grade 12: 12). A miss or "?" brings that topic's "easier"
  question next, so one slip doesn't mark a topic weak.
- Score per topic: core right 80, easier right 50, both missed 20. These seed
  `learner_topic_mastery` where the learner has no evidence yet; the tutor then
  pitches a new objective from the topic score instead of a flat 50.
- Wrong options name a misconception (`SIGN_ERR`, `FRAC_ADD_ACROSS`, ...). A
  misconception seen twice is named in the report.
- Report: strong / getting there / needs work, one pattern to fix, and the
  first three topics to work on (lowest score first, then more CAPS teaching
  time). REPORT shows it again, for the learner or a parent.
- Baseline: every completed check-in is a row in `diagnostic_results`. The
  first is the pilot baseline; CHECK-IN later gives an end-line.
- A real question mid check-in pauses it (the question is answered as usual);
  CHECK-IN resumes, PAUSE pauses.
- Bank: `seed/diagnostic/grade_XX.json`, built by `seed/diagnostic/build_bank.py`.
  118 items, 73 with a SymPy-checked answer (`tests/test_diagnostic_bank_unit.py`).
  **Not reviewed by a maths teacher yet.** No Grade 9 bank.

## 2. Real past papers (`app/tutor/papers.py`, `seed/papers/`)

- PAPER lists the grade's papers; a number starts one. PAPER <topic> gives the
  questions on one topic across papers.
- Each answer is marked against the memo points. Code checks the final answer
  where it can (a value, every root, an equivalent expression in the asked
  form, a point) and the model marks the working, with the code check as a fact.
  Code bounds the model: a wrong final answer never gets the answer mark, a
  correct one always does. Without a model, code awards the answer marks only.
- HELP hands the question to the tutor (step by step, CPA switching, leak guard
  with the memo answer); it doesn't count towards the marks. NEXT goes back to
  the paper. SKIP, STOP.
- The report gives marks, a per-topic breakdown and the weakest topic. Marks
  become mastery evidence (`quiz` source); `paper_attempts` keeps every attempt.
- Starter set (hand-converted, **unverified**, check against the PDFs):

| Paper | Questions | Marks kept |
|---|---|---|
| KZN Gr 10 June 2024 Common Test P1 | 16 | 41 of 50 |
| Provincial Gr 10 June 2023 Exam P1 | 20 | 44 of 50 |
| Provincial Gr 11 June 2024 Exam P1 | 26 | 74 of 100 |
| Free State Gr 11 March 2022 Test (Q1) | 6 | 23 of 50 |
| Gauteng JW Gr 12 March 2023 Test | 14 | 34 of 50 |
| KZN Gr 12 March 2022 Common Test (sequences) | 6 | 27 of 100 |

  Questions that need a diagram or a sketch, or whose text OCR destroyed, are
  left out and listed per paper in `left_out`.
- Copyright: these are provincial and district tests, mostly downloaded via
  third-party sites. Accepted as a testing risk (10 Sep); legal advice before
  live use.

## 3. Test prep (`app/tutor/test_prep.py`)

- "I'm writing a test on Friday on functions" is noted (`learner_tests`) with a
  date and topics; if no topic is named, Katlego asks which. The reply is a short
  plan.
- PREP: questions from the papers on the test's topics. With no test noted, the
  ATP decides: the 2026 calendar gives the term and week, and
  `atp_topic_schedule` says whether a topic block just ended (a test is likely)
  or the exam/revision block is on (a full paper). Always worded as a
  suggestion: school dates vary.

## 4. Study squads

- SQUAD NEW gives a 6-character code; friends in the same grade SQUAD JOIN it
  (8 at most). SQUAD PAPER chooses the paper, SQUAD START does it in your own
  chat, SQUAD RESULTS shows nicknames and marks plus the squad's hardest topic.
- Members are told on joining that nickname and marks are shared. POPIA review
  should confirm guardian consent covers this.

## Open

- Teacher review of the check-in bank; founder check of the six papers.
- More papers (OCR is the bottleneck; a model-assisted converter with human
  checking is the next step).
- Grade 9 bank; Grade 8 papers.
- Proactive test reminders need WhatsApp template messages (outside the 24-hour
  window), not built.
