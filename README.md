# Katlego (TutoBuddy) — WhatsApp CAPS Tutor · Proof of Concept

> *"Maski answers your question. Katlego knows your marks."*

A runnable local proof-of-concept of the P0 loop from
[TECHNICAL_BLUEPRINT.md](TECHNICAL_BLUEPRINT.md): learner message → safety
filter → POPIA consent gate → intent router → RAG over a tagged CAPS corpus →
Socratic reply — over text, **voice notes** and **homework photos**.

**No API keys are required to run it.** Everything third-party is behind an
adapter with an offline default; real keys drop into `.env` when the accounts
exist.

## Quick start

```bash
cp .env.example .env
docker compose up --build -d
docker compose build seed tests evals                  # profiled services are NOT built by `up --build`
docker compose run --rm seed                           # CAPS corpus (Gr 8–12) + question bank
docker compose run --rm seed python -m seed.load_curriculum   # Gr 8-12 Maths: CAPS topics, weights, assessment model, ATP schedules
docker compose run --rm seed python -m seed.load_past_papers  # OCR'd past papers, Grades 8-12 (seed/past_papers/grade_XX/YYYY/)
open http://localhost:8000/demo                        # WhatsApp-style demo simulator
```

Say **hi** in the simulator, then onboard: a guardian replies **AGREE** with their name (like *AGREE Nomsa Dlamini, mother*), you
give a **name**, then a **grade** (the pilot grade is **8**). Then ask
something like *"How do I collect like terms?"* — or click 🎤 and ask out
loud (local Whisper transcribes it, no key needed). Say **quiz me** for a
practice question, **PROGRESS** for your term mastery, **ADD LEARNER** /
**SWITCH** for siblings on a shared phone.

## Guardian consent

Tutoring starts only after a parent or guardian agrees, and every agreement
is kept as a record (`consent_records`). Four ways in, strongest first: a
sign-up code from the learner's school (`seed/load_enrolment_codes.py`), the
guardian confirming from their own WhatsApp (the learner sends **LINK**), a
voice note or photo of a signed slip (off unless `CONSENT_MEDIA_ENABLED`),
and a typed **AGREE** with the guardian's name. **WITHDRAW** erases a
learner. Research, open legal questions and design:
[docs/guardian-consent-findings.md](docs/guardian-consent-findings.md).

## Run the tests

```bash
docker compose run --rm tests
```

E2E tests drive the real gateway with Meta-format webhook payloads and assert
on what the mock Cloud API captured: onboarding/consent, tutoring + RAG grade
filters, safety referrals, webhook dedupe, Meta handshake, and a **live voice
test** that pushes real spoken audio (`tests/fixtures/voice_factorise.ogg`)
through faster-whisper. Regenerate the fixture with
`scripts/make_voice_fixture.sh` (macOS).

## Eval harness

```bash
docker compose run --rm evals
```

Grades the tutor against a golden set of NSC-style questions with memo answers
(blueprint §4.2 — "the tutor that shows its marks"). Scores are only
meaningful with a real LLM configured; in stub mode it says so loudly.

## Architecture (maps to blueprint §4)

```
simulator UI / real WhatsApp
        │  Meta-format webhooks
        ▼
gateway (:8000)  ── verify · dedupe · fast-ack ──►  Redis stream
                                                        │
                                                    worker
                        STT (voice) · vision (photos) · safety filter ·
                        POPIA consent gate · intent router · RAG (pgvector) ·
                        Socratic LLM reply
                                                        │
                                              WhatsApp adapter
                                                        ▼
                            mockwa (:8001) — mock Graph API, captures sends
```

| Service   | Port | Role |
|-----------|------|------|
| `gateway` | 8000 | Webhook receiver + `/demo` simulator |
| `worker`  | —    | Async pipeline off the webhook path |
| `mockwa`  | 8001 | Mock WhatsApp Cloud API (outbox, media store) |
| `stt`     | 9000 | faster-whisper speech-to-text (no key) |
| `db`      | 5433 | Postgres 16 + pgvector |
| `redis`   | 6380 | Sessions, dedupe, message queue |

## Placeholders — fill when the real accounts exist

All in `.env` (see `.env.example` for guidance). The mock-first design means
**going live is a config change, not a code change**:

| Variable | Where it comes from | Blueprint ref |
|---|---|---|
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `META_APP_SECRET` | Meta Business Manager + Cloud API setup | §3 items 1–3 |
| `GRAPH_API_BASE_URL` | set to `https://graph.facebook.com` to go live | — |
| `ANTHROPIC_API_KEY` + `LLM_PROVIDER=anthropic` | Anthropic console | §3 item 6 |
| `GROQ_API_KEY` + `LLM_PROVIDER=groq` (alternative to Anthropic) | console.groq.com — free/cheap hosted open gpt-oss models | — |
| `LLM_PROVIDER=ollama` (alternative, no key) | a locally running Ollama with a model pulled (`ollama pull <name>`) | — |
| `OPENAI_API_KEY` (optional) | Whisper API / embeddings alternative | §3 item 7 |

Note: homework-photo help only works with `LLM_PROVIDER=anthropic` for now —
groq's gpt-oss models and an arbitrary local Ollama pull aren't assumed to be
vision-capable.

Provider switches: `LLM_PROVIDER=stub|anthropic|groq|ollama`,
`STT_PROVIDER=stub|local|openai`, `EMBEDDINGS_PROVIDER=hash|openai`.

## Going live checklist (beyond keys)

1. Complete Meta business verification; register the dedicated bot number
   (blueprint §3, Phase 0 — starts weeks before launch).
2. Point a public HTTPS domain at the gateway; configure the webhook URL +
   `WHATSAPP_VERIFY_TOKEN` in the Meta app dashboard.
3. Set `META_APP_SECRET` — signature verification switches on automatically.
4. Replace the keyword safety screen with a proper classifier + human review
   queue; legal review of the consent flow (POPIA §34–35).
5. Swap the hash embedder for a real embedding model and run the full content
   pipeline (blueprint §5) over DBE CAPS/ATP + past papers.
6. Deploy to `af-south-1` for the POPIA data-residency story.

## Pilot scope: Grade 8 Mathematics

The curriculum graph, past papers, practice questions and mastery tracking
are loaded for **Grade 8 Mathematics only**. Learners in other grades still
get CAPS-grounded Socratic help from `caps_chunks` (Gr 8–12), but PROGRESS
and quiz report "no topics loaded" until more grades are ingested.

## What's deliberately NOT in the POC

Timed quizzes with PDF report cards, per-child consent capture, PIN-locked
profiles, streaks, Study Squads, isiZulu/Sepedi replies, Moya/USSD channels —
see the roadmap in the blueprint (§7). Mastery tracking here is a transparent
placeholder heuristic (+12/+4/−6 per attempt), not a calibrated model.
