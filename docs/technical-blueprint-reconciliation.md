# Technical Blueprint Reconciliation — CTO Blueprint vs. MVP Build Roadmap (1 Sep 2026)

## Sources compared
1. **`TutoBuddy — Technical Blueprint & Build Guide` (v1.0, Aug 2026)** — written by the CTO co-founder, "prepared from the original whiteboard sketch (`TutoBuddy.pdf`) plus independently verified research." Post-rebrand (TutoBuddy/Katlego branding), so this is the more recent of the two documents.
2. **`StudyBuddy_MVP_Build_Roadmap.pptx` (32 slides, 14 Aug 2026)** — built in an earlier session of this project, pre-rebrand (StudyBuddy branding), synthesized from this project's own feasibility research.

Founder decisions so far (updated 2 Sep 2026, presentation pass):
- **Scope: Grade 8–12, Maths + English/Science.**
- **Model routing: RESOLVED 2 Sep 2026, refined same day.** Three-tier router — Tier 1 default GPT-OSS-20B (Groq), Tier 2 vision (any vision-capable provider — Qwen 3.6-27B or Claude), Tier 3 escalation Claude Sonnet 5. **Governor superseded the earlier R34-based version**: the founder set a flat **30% of a student's monthly turns on a vision-capable model (any provider), 70% on text/reasoning models** — a volume cap, not a spend cap tied to a price point. Within the 70%, this document's working split is ≈60% of total turns on the cheap default tier, ≈10% on escalation — labelled explicitly as an assumption, not the founder's own number. **R34/month is explicitly NOT used as a cost baseline going forward** — the founder will determine pricing separately; all cost figures from 2 Sep 2026 onward are presented as absolute $ (R) costs, not as a % of any price point.
- **Infrastructure: DECIDED 2 Sep 2026 — Supabase (managed Postgres + pgvector) + Render (compute host).** This supersedes the AWS af-south-1/DigitalOcean line in the CTO blueprint's original Phase 0 purchase list (item 5) and confirms the lean-stack recommendation from `claude/cloud-infra-big3-comparison.md` as final, not just "current best option."
- **Deliverables produced 2 Sep 2026:** `TutoBuddy_LLM_Cost_Blueprint.docx` (the CTO-facing cost/routing blueprint, R34-based) and `TutoBuddy_Blueprint_Deck.pptx` (14-slide presentation — router decision, cost-per-turn by tier, a concrete "5x/week homework" learner persona, the 30/70 governor, the Supabase+Render decision, the full Phase 0 / Phase 1-2 purchases & sign-ups roadmap, and a condensed child-safety architecture). **The presentation deck deliberately excludes OceanHub Africa company branding/attribution per the founder's explicit instruction** — it is framed as a TutoBuddy/Katlego document, not an OceanHub Africa one. Apply the same framing to any future founder-facing or external deliverable unless told otherwise.

## The tension that has to be named before anything else
Both documents' own numbers say the same thing: **the wide Grade 8–12 / multi-subject scope and a true 3-month lean MVP are in direct conflict.** This isn't a judgment call between the two documents — it's what each one's own math shows independently:
- The roadmap deck's timeline check (Slide 25), built specifically against this wide scope, says 8–10 weeks is "optimistic — tight, assumes clean WhatsApp verification and no major content-digitization surprises," and calls 4–5 months "realistic." Its own verdict: "the original Month-3 MVP milestone was sized for a single grade-band, single-subject scope... plan the MVP milestone closer to Month 4–5 unless subjects/grades are launched in a staggered sequence."
- The CTO blueprint's Phase 0 window (Weeks 1–6, i.e. closer to 3 months total once P1 is added) is explicitly sized against its *narrower* wedge: "Gr 11–12 Maths + Accounting, English, text + photo." It was never sized against the full Grade 8–12 breadth.

**Recommended resolution (unconfirmed):** keep Grade 8–12 breadth as the target, sequence subjects not grades — ship **Maths across all of Grade 8–12** as the 3-month MVP, layer English/Science from Month 4.

## Where the two documents already agree (adopt without debate)
- **Core loop and differentiation thesis:** a *stateful* per-learner mastery tutor beats a generic chatbot on memory and curriculum grounding, not raw chat quality.
- **Data architecture:** Postgres + pgvector (now concretely Supabase) for curriculum and learner/mastery data, Redis for session/cache state, single-region hosting in `af-south-1` (or equivalent) for the POPIA data-residency story.
- **Content pipeline sourcing:** CAPS statements, ATPs, NSC past papers + marking memos from education.gov.za only — no textbook ingestion (copyright risk, Maski's moat).
- **Explicitly-not-buying-yet list:** no dedicated vector database, no GPUs/fine-tuning, no WhatsApp BSP fees until multi-tenant scale demands it, no native app.
- **WhatsApp channel phasing:** direct Meta Cloud API first, BSP only once multi-tenant WABA management is a real burden. No unofficial libraries (Baileys/Evolution API).
- **Mastery-band logic:** <40% remediate, 40–70% practice, 70–85% challenge, >85% advance — locked.

## Where the CTO blueprint corrects or supersedes the roadmap deck (adopt — newer, independently verified)
- **WhatsApp Groups API cannot join a user's existing group chat** — only business-created, invite-link groups. **Fix: "Study Squads"** — TutoBuddy hosts its own groups / leaderboards across 1-to-1 chats.
- **Per-message pricing changed 1 July 2025** to per-template-message; free-form replies inside the 24h service window (learner messages first) are free. **Design implication: engineer every engagement loop so the learner sends the first message.**
- **No carrier can zero-rate a bot's WhatsApp data specifically.** CTO blueprint's alternative — Moya Messenger/biNu `#datafree` (now in the Phase 1-2 purchase list, item 13) with USSD as a P3 fallback (item 14).
- **Multi-learner-per-phone-number design** — one WhatsApp number ≠ one learner; in-chat profile switching is P0, not a nicety, now that pricing is confirmed per-student not per-phone.
- **Assessment with real marks, as a P0 differentiator** — timed quizzes auto-graded against NSC marking memos, PDF report card.
- **Safety filter ordering** — the safety/self-harm classifier runs before intent routing, every message, no exceptions. **This is now formalized as the "Input safety" layer (layer 1 of 4) in the child-safety architecture presented 2 Sep 2026 — see below.**
- **Eval harness, made concrete** — 50+ real past-paper questions with official memos as ground truth, auto-graded on every prompt/model change.

## Where the roadmap deck adds value the CTO blueprint doesn't cover
- **Competitive landscape detail** (Maski, Luma Learn, Study Mate SA, Rori reach numbers) — keep for investor/positioning material.
- **Full three-way cloud cost comparison** — now moot for the infra decision (Supabase+Render decided), but the comparison itself remains the sourced justification if that decision is ever questioned.
- **Payment-rail research** — WhatsApp Pay not live in SA; every workable B2C route is a mid-chat payment link (Paystack/PayFast) or manual voucher. **Still unresolved**: direct billing vs. institutional sponsorship, independent of whatever price point the founder lands on.
- **Org chart / build-vs-partner matrix** — orthogonal to technical architecture.

## Model-routing strategy — RESOLVED, refined 2 Sep 2026
Final design: Tier 1 GPT-OSS-20B (Groq, default), Tier 2 any vision-capable provider (Qwen 3.6-27B or Claude, capped at 30% of monthly turns), Tier 3 Claude Sonnet 5 (escalation, part of the 70% text/reasoning share). This is Option A (open-weight for volume) with Claude retained at the top, governed by turn volume rather than spend. Pros/cons of the original Option A/B framing are preserved in the full cost blueprint (`TutoBuddy_LLM_Cost_Blueprint.docx`) and are no longer duplicated here to keep this document current rather than growing without bound.

## Unit economics — see the two delivered documents, not this file, for current numbers
Two cost analyses now exist and should not be confused:
1. **`TutoBuddy_LLM_Cost_Blueprint.docx`** (2 Sep 2026, morning) — the CTO-facing document, built against the R34/month price point (% of revenue framing). Still valid as the router/architecture decision record.
2. **`TutoBuddy_Blueprint_Deck.pptx`** (2 Sep 2026, afternoon) — the presentation version, deliberately rebuilt **without** the R34 baseline per the founder's instruction ("I will determine the cost later"), using the 30/70 governor and $ (R) absolute figures throughout, plus a concrete 5x/week-homework learner persona (≈130 turns/month, ≈R4.68/$0.29 LLM cost/month at that mix).

Headline figures common to both (re-verified 2 Sep 2026): Sonnet 5 $2/$10, Haiku 4.5 $1/$5 per M tokens (Anthropic, permanent pricing); Qwen 3.6-27B $0.60/$3.00, Qwen 3.8-27B $0.80/$4.00 (Groq Preview); GPT-OSS-120B $0.15/$0.60, GPT-OSS-20B $0.075/$0.30 (Groq Production). Only Qwen 3.6/3.8-27B carry vision on the Groq shortlist — confirmed directly against console.groq.com/home. FX ≈R16.20/$1.

**SMS-fallback assumption flagged for review (still unconfirmed):** the founder's working assumption (reasoning-tier model for SMS "simple questions") was challenged in the first cost blueprint — SMS carries a real per-message business cost (~R0.23/part) WhatsApp doesn't, so the cheapest model plus a reply-length cap is the numbers-backed recommendation for that channel, not the reasoning tier.

## Child-safety architecture — added 2 Sep 2026
A four-layer model now sits in the presentation deck (§8 there): input safety (age-band/risk/PII detection before intent routing) → AI tutor (curriculum-grounded RAG) → output safety (content/tone/link checks) → safeguarding (defined human escalation; the AI is never the final authority on a risk case). Twelve non-negotiable product requirements condensed from a founder-supplied framework, cross-checked against real UNICEF sources this session: **UNICEF Innocenti's "Guidance on AI and Children" (v3, 2025 checklist)** — ten pillars covering regulatory frameworks, safety, data/privacy, fairness, transparency, human rights, child well-being, inclusion, AI literacy, and enabling environment — and **"When AI Becomes a Friend" (2026 policy brief on AI chatbots/companions)**. Some granular claims in the founder's source material (specific grooming-phrase lists, exact UNICEF quote attributions) could not be independently verified this session and were deliberately summarized at the category/principle level rather than reproduced verbatim — treat the presentation's 4-layer architecture and 12 principles as this project's own engineering translation of real UNICEF guidance, not as direct UNICEF quotations. Not yet reconciled against the CTO blueprint's own safety section in detail — worth a direct comparison pass before this becomes final.

## Purchases & sign-ups roadmap — captured 2 Sep 2026
Phase 0 (pre-code, 9 items) and Phase 1-2 (buy-on-trigger, 5 items) now live in the presentation deck (§9-10), sourced from the CTO blueprint's own purchase list with two corrections applied: item 5 (cloud hosting) updated from AWS/DigitalOcean to Supabase+Render, and item 6 (LLM API accounts) updated from "Anthropic and/or OpenAI" to "Groq + Anthropic" to match the resolved router. Items 8 (Postgres+Redis) annotated to note Supabase provides managed Postgres+pgvector directly. All other items (Meta Business Manager, dedicated number, WhatsApp Cloud API, domain+TLS, POPIA basics, observability, airtime rewards, Turn.io, Moya/biNu, USSD) carried forward as originally specified.

## Suggested next step
(1) Confirm the subject-staggering resolution (Maths-first, English/Science from Month 4) or specify an alternative; (2) decide whether Study Squads, multi-profile-per-number, and PDF-report-card assessment are all P0 or defer any to P1; (3) confirm payment-rail recommendation (institutional sponsorship vs. direct billing) once the founder sets the actual price point; (4) sign off on the 30/70 governor split and the ≈60/10 sub-split within the 70% text bucket as the pilot's starting assumption; (5) resolve the SMS-fallback model/length policy; (6) confirm Qwen's exact Groq model ID and test vision quality on real CAPS content; (7) reconcile the presentation's child-safety architecture against the CTO blueprint's own safety section in detail — not yet done.
