# TutoBuddy — Technical Blueprint & Build Guide

**A CAPS-aligned AI tutor that lives in WhatsApp**
Version 1.0 · August 2026 · Prepared from the original whiteboard sketch (`TutoBuddy.pdf`) plus independently verified research.

> This document is the single source of truth for what we are building, why it is different, what we need to buy/sign up for (in order), and how the system fits together. It lives in the project root so it can also serve as reference context for AI coding tools (Claude Code etc.) working in this repo.

---

## 1. Product thesis — read this first

Everyone now has "AI on WhatsApp." Maski (100k+ users, R55m funding, Maskew Miller textbook licence), Sammo (CSR-funded, grades 1–12), and **Meta AI itself** — free and pre-installed in every South African learner's WhatsApp — already answer questions. Answering questions is a commodity. We cannot win on it.

**Our bet: a *stateful* tutor.**

- A persistent **per-learner mastery model** ("you struggled with factorisation in March — let's revise it before Friday's quiz").
- **Assessment with real marks**, graded against official NSC marking memos, with PDF report cards.
- Engagement engineered around WhatsApp's **free 24-hour service window**, so the marginal messaging cost of a tutoring session is close to zero.

Positioning sentence: **"Maski answers your question. TutoBuddy knows your marks."**

---

## 2. Verified market facts (and corrections to earlier research)

The AI research brief that inspired the original sketch contained three load-bearing errors. Build decisions below account for them.

### 2.1 Corrections

| Earlier claim | Verified reality (Aug 2026) | What we do instead |
|---|---|---|
| "Add the bot to students' WhatsApp group chats" | The official WhatsApp Business API **cannot** join a user's existing group. Meta's Groups API only covers **groups the business creates programmatically**, is eligibility-gated, and members join via invite link. Unofficial libraries (Baileys, whatsapp-web.js) risk a permanent number ban. | **Study Squads**: TutoBuddy *hosts* the group (Groups API when eligible) or runs squad leaderboards across 1-to-1 chats. Same social loop, zero ban risk. |
| "Partner with MTN/Vodacom to zero-rate your bot's data" | Impossible per-bot: WhatsApp traffic terminates at Meta's servers, so carriers can only zero-rate WhatsApp wholesale. | Data-free access via **Moya Messenger / biNu #datafree** as a second channel (reverse-billed, genuinely free to users), plus a **USSD** formula/definition lookup fallback. |
| Per-conversation pricing assumptions | Since **1 July 2025** Meta charges **per template message**. Free-form replies inside the 24-hour customer-service window (opened whenever the *learner* messages us) are **free**. Utility templates sent as replies inside the window are also free. We pay only for messages **we** initiate outside the window. | Design every engagement loop so the **learner sends the first message** (streak missions, "reply START for today's quiz"). Reserve paid templates for the weekly parent digest. |

### 2.2 Other verified facts that shape the build

- **Maski** (Bytefuse × Maskew Miller, launched Mar 2025, R55m from Novus): grades 7–12, multimodal input, but currently **replies in English only** — the multilingual gap is wide open. Its textbook licence is a moat we legally cannot copy.
- **Textbooks are copyrighted.** Our corpus must be DBE-published material: CAPS statements, ATPs (Annual Teaching Plans), and NSC past papers **with marking memos** — all free downloads from education.gov.za.
- **Adesua** (ETH Zurich / Kwame AI, Ghana) proved timed in-chat assessments with auto-generated PDF report cards work on WhatsApp. We adopt that pattern learner-side.
- **Meta AI is the invisible competitor**: free, zero-friction, generic. Our defence is curriculum grounding + marks + memory, not chat quality.
- **POPIA**: our users are minors. Sections 34–35 require consent from a **"competent person"** (parent/guardian) before processing a child's personal information. This is a launch blocker, not a nice-to-have.

---

## 3. Purchases & sign-ups, in the order we need them

Costs are estimates (Aug 2026) for planning, not quotes. Phase labels match the roadmap in §7.

### Phase 0 — needed before the first line of production code

| # | Item | Provider / where | Est. cost | Notes |
|---|---|---|---|---|
| 1 | Company Meta Business Manager account + **business verification** | business.facebook.com | Free | Verification takes days–weeks; start immediately. Needs company registration docs. |
| 2 | **Dedicated phone number** for the bot | Any SA SIM / virtual number | ~R100 once + airtime | Must NOT be attached to an existing personal/business WhatsApp. This number becomes the product's identity — guard it. |
| 3 | **WhatsApp Business Platform (Cloud API)** access + payment method on the Meta account | developers.facebook.com | Free platform; pay per template message only | Direct Cloud API for P0 — skip BSP fees. New numbers start at ~1k business-initiated conversations/day and scale up with quality rating. |
| 4 | **Domain name** + TLS | Any registrar | ~R150–300/yr | Needed for the webhook endpoint (Meta requires HTTPS) and later for a zero-ratable companion web app. |
| 5 | **Cloud hosting** | AWS `af-south-1` (Cape Town) or DigitalOcean | ~R400–1,000/mo to start | One VM/container host + managed Postgres. `af-south-1` gives the clean POPIA data-residency story for school/government conversations. |
| 6 | **LLM API account(s)** | Anthropic and/or OpenAI | Usage-based; budget ~R2,000–5,000/mo for pilot | Two tiers: a small/cheap model for intent routing, a frontier model for maths reasoning. No GPU purchases, no fine-tuning at this stage. |
| 7 | **Speech-to-text API** | OpenAI (Whisper) or equivalent | Usage-based (cents per audio minute) | Voice notes are a P1 feature but sign-up is free; benchmark early on real code-switched audio. |
| 8 | **Postgres + Redis** | Managed add-ons on the host above | Included / ~R200–400/mo | Postgres with the **pgvector** extension — we do NOT buy Pinecone/Weaviate at this stage. |
| 9 | **POPIA basics** | Information Regulator portal + legal review | Registration free; budget ~R10–20k once for legal review | Register an Information Officer; review the guardian-consent onboarding flow and privacy notice. |

### Phase 1–2 — buy only when the loop is proven

| # | Item | Provider | Est. cost | Trigger to buy |
|---|---|---|---|---|
| 10 | Error tracking / observability | Sentry + basic dashboards | Free tier → ~R500/mo | First 100 weekly-active learners. |
| 11 | **Airtime/data micro-rewards API** | e.g. Reloadly, Flickswitch or aggregator | Per-voucher cost (R5–10 each) + small fees | When streak mechanics ship (P2 gamification). |
| 12 | **Turn.io** subscription (optional) | turn.io | Nonprofit/social-impact pricing | If we want their journey tooling & analytics instead of maintaining our own template/flow ops. |
| 13 | **Moya / biNu #datafree** partnership | moya.app (biNu) | Negotiated reverse-billing (we pay the data) | P2 — the real "data ran out at 10pm" lifeline. |
| 14 | **USSD code + aggregator** | e.g. Africa's Talking or SA aggregator | Setup + per-session fees | P3 — formula/definition lookup fallback. |

**Explicitly NOT purchasing now:** BSP platform fees (Twilio/Infobip/MessageBird), a dedicated vector database (Pinecone/Weaviate), GPUs or model fine-tuning, native app development. Each has a revisit trigger noted above or in §8.

---

## 4. Architecture

### 4.1 Overview

```
┌─────────────────────────── CHANNELS ────────────────────────────┐
│  WhatsApp Cloud API   ·   Moya #datafree (P2)   ·   USSD/SMS (P3) │
└──────────────────────────────┬──────────────────────────────────┘
                               │ webhooks (must ACK < ~3s)
┌──────────────────────────────▼──────────────────────────────────┐
│ GATEWAY: webhook receiver (verify, dedupe, fast-ack)             │
│          message queue (ordering, retries, back-pressure)        │
│          template manager (paid sends, quality-rating watch)     │
└──────────────────────────────┬──────────────────────────────────┘
┌──────────────────────────────▼──────────────────────────────────┐
│ ORCHESTRATOR:                                                    │
│   1. safety filter  → self-harm/abuse disclosure → referral path │
│   2. intent router (cheap LLM): homework · quiz · past-paper ·   │
│      admin · smalltalk                                           │
│   3. session manager (Redis): active profile, mid-quiz state,    │
│      awaiting-photo state                                        │
└──────────────────────────────┬──────────────────────────────────┘
┌──────────────────────────────▼──────────────────────────────────┐
│ PROCESSING WORKERS (async, off the webhook path):                │
│   STT worker (voice notes)  ·  Vision worker (homework photos)   │
│   TUTOR ENGINE: tiered LLMs — small router model + frontier      │
│   reasoner for maths; Socratic policy; versioned prompts         │
└───────────────┬───────────────────────────────┬─────────────────┘
                │ RAG                           │ read/write
┌───────────────▼────────────────┐  ┌───────────▼─────────────────┐
│ KNOWLEDGE (Postgres+pgvector): │  │ LEARNER DATA (Postgres):    │
│  CAPS/ATP corpus, chunked +    │  │  profiles (multi-learner    │
│  tagged grade·subject·term·    │  │  per phone number!)         │
│  topic                         │  │  mastery graph (per-topic,  │
│  NSC question bank: past       │  │  time-decayed)              │
│  papers + marking memos as     │  │  POPIA: consent records,    │
│  STRUCTURED data               │  │  minimisation, af-south-1   │
└────────────────────────────────┘  └─────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ QUALITY: eval harness (golden set graded vs NSC memos, runs on   │
│ every prompt/model change) · analytics (mastery, funnel, cost    │
│ per learner) · weekly parent/teacher digest (the one paid send)  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Why each layer exists

- **Gateway.** WhatsApp webhooks are stateless and must be acknowledged within seconds, while a full voice-note → STT → RAG → frontier-model response can take 10–30s. Fast-ack + queue + workers is non-negotiable. Send typing indicators while workers run. Dedupe on WhatsApp message IDs (Meta redelivers).
- **Safety filter first, always.** A learner disclosing abuse or a self-harm crisis at 23:00 must hit a referral script (Childline SA 116) — never a maths prompt. This runs before intent routing.
- **Intent router = cost control.** A cheap model classifies each message; only genuine reasoning work reaches the expensive model. This single decision roughly halves LLM spend.
- **Session manager.** One phone number ≠ one learner in our market — **family phones are shared**. Profile switching ("Who's studying? Thabo Gr 11 / Lerato Gr 9") with per-profile mastery is cheap to build and no competitor handles it.
- **Knowledge = structure, not just embeddings.** Raw PDF embeddings give mushy answers. CAPS/ATP content is chunked and tagged (grade, subject, term, topic). Past papers are parsed into a structured question bank with memo-linked marking guidance — this powers real quizzes and real marks.
- **Mastery graph.** Per-topic strength scores, decaying over time, drive daily revision missions and the parent digest. This layer *is* the moat; everything else is plumbing around it.
- **Eval harness from day one.** Golden set of ~50+ past-paper questions with official memos as ground truth; auto-grade on every prompt/model change; publish the accuracy number. "The tutor that shows its marks" is also the trust story for schools and sponsors.

### 4.3 Recommended stack (P0)

| Concern | Choice | Rationale |
|---|---|---|
| Language/runtime | Python (FastAPI) or Node/TypeScript — team's call | Both have mature WhatsApp Cloud API + LLM SDKs. Pick one, document it here. |
| Queue | Redis Streams (or BullMQ if Node) | Already running Redis for sessions; no new infra. |
| DB | Postgres 16 + pgvector | One database for profiles, mastery, embeddings, question bank. |
| Cache/session | Redis | Live session state, rate limiting. |
| LLMs | Managed APIs, two-tier | Router: small/cheap model. Reasoner: frontier model. Wrap behind an internal interface so providers are swappable. |
| STT | Whisper API (benchmark first) | Measure word-error-rate on real code-switched voice notes before considering anything custom. |
| Hosting | AWS af-south-1 or DO | Data residency + latency. Single region, containerised. |
| WhatsApp | Meta Cloud API direct | Free platform access; revisit Turn.io at P2 for journey tooling. |

---

## 5. Content pipeline (a product in itself, not a setup step)

1. **Acquire**: download CAPS statements + ATPs per subject/grade, and 5 years of NSC papers + marking memos from education.gov.za. All public. **Do not ingest textbooks** — copyrighted (that's Maski's licensed moat).
2. **Parse & tag**: chunk documents with metadata `{grade, subject, term, topic, doc_type}`. Parse past papers into structured records: question text, sub-parts, marks, memo answer, cognitive level.
3. **Embed**: pgvector, per-chunk, with metadata filters applied *before* similarity search (a Grade 9 question must never retrieve Grade 12 content).
4. **Author**: our own worked examples for high-frequency topics (legally clean, quality-controlled).
5. **Version**: corpus versions are tagged; the eval harness runs against every corpus update, same as prompt updates.

## 6. Compliance, safety & platform ops (launch blockers)

- **POPIA**: guardian ("competent person") consent captured at onboarding before any profiling; privacy notice in plain language; data minimisation (no names required — a nickname works); Information Officer registered; data stored in af-south-1; deletion on request.
- **Safeguarding**: classifier + referral scripts (Childline SA 116, SADAG); log and human-review flagged conversations under strict access control.
- **Age-appropriate design**: no dark patterns in streaks; rewards capped; no shame mechanics on low marks.
- **WhatsApp number ops** (someone must own this): business verification, display-name approval, messaging-tier limits (~1k/day initially, scales with quality rating), quality score monitoring — user blocks can throttle the number and stall growth at the platform layer.

## 7. Roadmap

| Phase | Window | Goal | Ships |
|---|---|---|---|
| **P0** | Weeks 1–6 | Prove: learner asks → CAPS-correct Socratic help → returns tomorrow | Cloud API direct; wedge = **Gr 11–12 Maths + Accounting**, English, text + photo; RAG over tagged CAPS/NSC corpus; Socratic prompt policy; POPIA consent flow + safety filter **in the first build**; 50-question eval harness. |
| **P1** | Months 2–4 | Become a tutor, not a chatbot | Voice notes (STT); timed quizzes marked vs memos + PDF report card; mastery graph → daily revision missions; shared-phone multi-profiles; learner-initiated streak mechanics (free-window-native). |
| **P2** | Months 4–8 | Widen the moat | Code-switched voice pipeline (measure WER first; fine-tune only if data demands); isiZulu/Sepedi replies; Study Squads; airtime micro-rewards; Moya channel; weekly parent digest (paid template). |
| **P3** | Months 8+ | Distribution & revenue | USSD lookup; teacher dashboards; CSR/B-BBEE sponsorship packages; school licensing. |

## 8. Decisions already made (don't relitigate without new data)

1. **LLM: API, tiered — not custom.** Fine-tuning is a P2+ decision driven by measured vernacular performance. Prompted frontier models + RAG beat a fine-tune on curriculum accuracy per rand.
2. **Direct Cloud API, not a BSP,** for P0. Revisit Turn.io when journey tooling outweighs its fees.
3. **pgvector, not Pinecone/Weaviate,** until retrieval scale actually hurts.
4. **af-south-1 hosting** for the POPIA residency story.
5. **Voice calls: parked.** Voice *notes* cover the real use case at a fraction of the complexity.
6. **Biggest cost risk is LLM tokens, not WhatsApp fees.** The intent router + free service window keep marginal session cost in the cents; the parent digest is the only meaningful template spend. Maintain a live cost-per-weekly-active-learner number from week one.

## 9. Differentiation summary (vs the field)

| Capability | Meta AI | Maski | Sammo | **TutoBuddy** |
|---|---|---|---|---|
| CAPS-grounded answers (RAG) | ✗ | ✓ | ✓ | ✓ |
| Persistent mastery memory | ✗ | thin | thin | **core bet** |
| Timed assessments marked vs NSC memos + PDF report | ✗ | teacher-side only | ✗ | **learner-side** |
| Multi-learner profiles per phone | ✗ | ✗ | ✗ | **✓** |
| Code-switched voice notes | generic | English replies | partial | **measured, then invested** |
| Data-free path (Moya + USSD) | ✗ | ✗ | ✗ | **P2–P3** |
| Bot-hosted Study Squads | ✗ | ✗ | ✗ | **P2** |
| Niche-subject wedge (Accounting, EMS, IT, setworks) | ✗ | maths/science-led | broad | **wedge strategy** |

## 10. Sources / verification trail

- Meta — WhatsApp Business Platform pricing (per-message since 1 Jul 2025; free service window): https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- Groups API limitations (no joining existing groups): https://botpenguin.com/blogs/how-to-add-whatsapp-bot-to-group-chat
- TechCentral on Maski (funding, users, English replies): https://techcentral.co.za/whatsapp-ai-tutor-a-big-hit-in-south-african-schools/272096/
- Sammo: https://sammo.co.za/
- Adesua feasibility study (ETH Zurich/Kwame AI): https://arxiv.org/html/2605.15376v1
- Moya Messenger / biNu #datafree: https://techcentral.co.za/moya-messenger-app-rival-whatsapp/200622/ · DGMT zero-rating analysis: https://dgmt.co.za/wp-content/uploads/2021/06/Zero-Rating-Opportunity-2.pdf
- POPIA & children's data (competent-person consent): https://www.ppmattorneys.co.za/personal-information-of-children-popia/
- DBE CAPS documents: https://www.education.gov.za/Curriculum/CurriculumAssessmentPolicyStatements(CAPS).aspx · NSC past papers & memos: https://www.education.gov.za/Curriculum/NationalSeniorCertificate(NSC)Examinations.aspx
- Turn.io pricing: https://www.turn.io/pricing · ICTworks on Meta charging social-impact senders: https://www.ictworks.org/meta-wants-to-charge-for-whatsapp-messages/

---

*Companion to the original whiteboard sketch (`TutoBuddy.pdf`). When implementation starts in this folder, keep this file updated — it is the reference context for both humans and AI coding tools.*
