# Guardian consent: findings, open questions and build record

Written 10 November 2026 for two readers: the privacy lawyer TutoBuddy will
engage, and Moeketsi reviewing the `consent/guardian-consent` branch.

**This is not legal advice.** It is research by an AI assistant, checked
against the sources named in the full report, plus a record of what was built
from it. The full report, with the comparison of every option and the source
list, is a private page: https://claude.ai/artifact/GPiAcBZqABbGVVs4PWg6ir
(Immanuel must share it before anyone else can open it).

## 1. The problem

At sign-up Katlego asked a parent or guardian to reply AGREE. The reply came
from the learner's own chat, so nothing showed that an adult took part. The
system also kept almost no proof: no guardian name, no WhatsApp message ID, no
note of which wording was shown, and a consent time that was really the time
the learner profile was created.

## 2. What the law says (read from the official texts)

- POPIA section 34: a responsible party may not process personal information
  concerning a child, subject to section 35.
- Section 35(1)(a): the ban does not apply if processing is "carried out with
  the prior consent of a competent person".
- Section 1: a child is a person under 18 who is not legally competent to act
  without the assistance of a competent person. A competent person is "any
  person who is legally competent to consent to any action or decision being
  taken in respect of any matter concerning a child".
- Section 11(2)(a): "The responsible party bears the burden of proof for the
  data subject's or competent person's consent". Section 11(2)(b): consent
  may be withdrawn at any time.
- **Neither the Act, the POPIA Regulations (as amended 17 April 2025), nor the
  Information Regulator's 2021 guidance note on children says how consent
  must be collected or checked.** The practical test is evidence.
- No school consent route was found in POPIA. Section 35 has no education
  exception.
- Children's Act section 17: a child becomes a major at 18. Section 32 lets a
  caregiver exercise parental responsibilities "reasonably necessary" to care
  for the child.

Other regimes (US COPPA, EU GDPR Article 8, UK ICO and others) scale the
check to the risk. A confirmation through a second channel is the accepted
light method for data that stays inside the service. None treats a tap on
the child's own device as verification.

## 3. Recommendation (as adopted)

| Route | Method |
|---|---|
| School pilot | The school collects a signed slip from each parent. Each learner signs up with a one-time code. |
| Sign-up from home | Tiers. Everyone: a consent record, the guardian's name, follow-up notices and an easy way to withdraw. Guardian has own WhatsApp: they confirm from it with a code. Shared phone: a voice note (or a photo of a signed slip). |

No free method inside WhatsApp can prove an adult agreed when a family shares
one phone. Those sign-ups are recorded as `declared`, the lowest level.

## 4. Questions for the lawyer or the Information Regulator

1. **Is the method enough?** For data this modest, is a named declaration
   with a full record defensible, or is a second-channel confirmation
   expected?
2. **Who is a competent person?** Can a grandmother, aunt or other caregiver
   who is not the legal guardian consent under POPIA, given section 32 of the
   Children's Act? Stats SA's household survey, as reported, puts about one
   child in five with neither biological parent.
3. **The school route.** Can the school be the responsible party with
   TutoBuddy as its operator under a section 21 contract? If so, what is the
   school's own ground for the processing, and must each parent still consent
   to Katlego by name? Can a school or governing body ever consent in place
   of parents?
4. **Learners aged 18.** Can they consent for themselves, what proof of age
   is reasonable, and does a learner who turns 18 need to give fresh consent?
5. **One consent per household.** Is one guardian's consent enough for
   siblings added later, or must it be given per child? (The build now asks
   per child.)
6. **Processing before consent.** Katlego logs the first messages and runs
   its safety filter before the consent gate, and keeps safeguarding flags
   after erasure. Which ground in section 35 covers this?
7. **Proof after erasure.** When a household is erased, may TutoBuddy keep a
   minimal record that consent was given and withdrawn, and for how long?
   (The build erases the consent record with the learner, as before.)
8. **The notice wording.** Does the consent message meet section 18? It does
   not give TutoBuddy's name and address, who receives the data, or the right
   to complain to the Regulator. Is "No data is sold or shared" accurate when
   messages pass to outside AI model and transcription providers?
9. **Transfers abroad.** Section 57(1)(d) requires the Regulator's prior
   authorisation before a child's personal information is transferred to a
   third party in a country without adequate protection. Katlego's model
   providers are outside South Africa. Does this apply, and does section 72
   need the guardian's consent to the transfer?
10. **Voice notes.** Is a stored recording of a guardian's voice biometric
    information under section 26? What retention period is reasonable?
11. **The guardian's own data.** What notice does the guardian need about
    their name, number and recording being stored?
12. **Withdrawal.** When a guardian withdraws, what must be erased and how
    quickly?
13. **Regulator authorisation.** Would a section 35(2) authorisation be
    available or useful for a public-interest tutoring service?
14. **WhatsApp's own rules** (for Meta or a WhatsApp business partner). Does
    a chat that the guardian starts count as their opt-in under the Business
    Messaging Policy, and may Katlego later send that guardian reminders?

## 5. Wider findings that affect Katlego beyond consent

- **Children's data sent abroad.** See question 9. This may need action
  whatever consent method is used.
- **Meta's rules on AI services.** Since 15 January 2026 Meta allows "AI
  Providers" to offer general-purpose AI assistants on the WhatsApp Business
  Platform only where the law requires Meta to permit it. South Africa is not
  on Meta's list. Katlego is a subject tutor and may fall outside this. Nobody
  has read the terms against what Katlego does.
- **Replies now cost money.** Since 1 October 2026 each business number gets
  1,000 free service messages (replies) a month, then Meta charges per
  message. The South African rate was reported as USD 0.0095. The investor
  cost sheet should be checked against this.

## 6. Limits of the research

- POPIA, the regulations and the Children's Act were read from the official
  PDF files. Everything else was gathered by research assistants.
- The UK regulator's site blocked automated reading, so its wording comes
  from search excerpts.
- The Regulator's children's guidance note was read on a mirror site.
- Most WhatsApp rules are a summary of Meta's pages. Two were checked
  directly: service message pricing and the AI Providers page. Meta's full
  terms page did not load.
- FoondaMate, the closest South African peer, could not be read.
- The living-arrangements figure and the matric results enforcement matter
  come from secondary reports.

## 7. Build record

Branch `consent/guardian-consent`, cut from `moeketsi/bakeoff-fixes`
(085ed08). Each milestone was tested before the next began. The baseline was
368 passing tests on a fresh database. Everything ran against the mock
WhatsApp API and the stub model; nothing has been tried against Meta's real
API.

| # | Milestone | What it does | Full suite after it |
|---|---|---|---|
| 1 | Consent record | Every consent event is a `consent_records` row: the wording shown (stored once per version in `consent_notices`), WhatsApp's ID for the notice and for the reply, the reply as sent, the account it came from, the guardian's message time, the method and the level. A bare YES or ACCEPT no longer passes. ADD LEARNER asks for consent again; CANCEL backs out. | 372 passed |
| 2 | School sign-up codes | `seed/load_enrolment_codes.py` reads a class list and issues one `SCH-XXXXXX` code per returned slip. A learner sends the code in place of AGREE. Codes work once. A draft slip is in `seed/school/consent_slip.md`; the loader requires `--slip` and refuses wording still marked DRAFT. | 375 passed |
| 3 | Guardian's name, follow-up, WITHDRAW | AGREE must come with the guardian's name and relationship. About 7 days after a consent that rests on the learner's own chat, Katlego adds a note asking the guardian to CONFIRM, then reminds them every 30 days how to withdraw. WITHDRAW does what DELETE does. | 378 passed |
| 4 | Guardian's own WhatsApp | The learner sends LINK and gets a 6-character code valid for 48 hours. The guardian sends `CONSENT <code>` from their own phone, reads the notice there and agrees there. The learner's own number is refused. The guardian can WITHDRAW from their own phone. | 385 passed |
| 5 | Voice note and signed-slip photo | The learner sends VOICE or SLIP, then the guardian's voice note or a photo of a signed note is stored as the record. **Switched off by default** (`CONSENT_MEDIA_ENABLED`) until questions 10 and 11 are answered. | 388 passed with the switch on; 386 passed and 2 skipped with it off |

Moeketsi's full learner journey (`evals/journey/full.py`, stub model) also
passes after the changes: 43 pass, 0 fail.

A review after milestone 5 led to three fixes, tested with the full suite
(387 passed, 2 skipped with the voice and slip switch off): the stored
wording of the guardian's notice no longer contains the last digits of the
learner's number, the loader refuses the draft slip, and a code waiting on a
guardian's phone is dropped when the sibling step is cancelled or the
household is erased.

Consent levels, weakest first: `declared` (typed AGREE with a name on the
learner's phone), `slip`, `voice`, `second_account` (the guardian's own
WhatsApp), `school`.

Not built, by design: WhatsApp Flows, reply buttons, a limited mode, the 18+
self-consent branch, the knowledge check, ID checks and card payments.

### Files

- New: `app/orchestrator/consent.py`, `seed/load_enrolment_codes.py`,
  `seed/school/consent_slip.md`, `tests/test_consent.py`,
  `tests/test_school_codes.py`, `tests/test_guardian_link.py`,
  `tests/test_consent_media.py`.
- Changed: `app/worker.py` (the consent gate, the guardian's turn, CONFIRM,
  follow-up notes), `app/orchestrator/session.py` (consent texts moved out,
  `erase_learner` moved in from the worker), `app/db.py` (four new tables),
  `app/config.py`, `app/orchestrator/safety.py` (Katlego's own `wa.me` link
  is no longer stripped), `app/orchestrator/practice.py`, `mockwa/main.py`
  (a one-shot delivery failure for tests), `.env.example`, `README.md`.
- Moeketsi's files touched: the sign-up steps in eight test files now use
  one shared `AGREE` constant from `tests/conftest.py`, and
  `evals/journey/full.py` and `evals/journey/week.py` send the guardian's
  name with AGREE.

## 8. Choices made during the build that need sign-off

Each line is a choice an engineer made that Immanuel, Moeketsi or the lawyer
should confirm.

**Wording (question 8)**

1. The consent notice now adds: "It also keeps a record of this agreement,
   including the parent or guardian's name", "Send WITHDRAW or DELETE any
   time", and the list of ways to agree. "No data is sold or shared" was left
   exactly as it was, pending the lawyer.
2. The notice a guardian sees on their own phone is new text. It names
   TutoBuddy and shows the last four digits of the learner's number so the
   guardian can tell which child asked.
3. The school slip is a draft with placeholders. Do not send it to parents.

**Behaviour**

0. **The school pilot is not codes-only.** The report says a learner whose
   slip has not come back should not get in on a typed AGREE. The build
   accepts a typed AGREE (and LINK) on every number, because the same
   Katlego number serves both routes. A setting that accepts school codes
   only is a small addition if the pilot needs it.
4. The guardian's name is free text and is not checked. "AGREE to nothing"
   would be stored with "to nothing" as the name.
5. The one-week CONFIRM is a request, not a gate. If the guardian never
   confirms, tutoring carries on and the record simply shows no confirmation.
   Consents backed by a school or a second WhatsApp account get no follow-up
   notes.
6. A guardian's WITHDRAW from their own phone erases at once, with no "are
   you sure" step, like DELETE. It covers only learners that account
   confirmed.
7. A guardian whose own phone also has an active learner cannot WITHDRAW
   there for a child on another phone; they use the child's phone. Marked in
   the code.
8. Link codes are 6 characters, last 48 hours and work once.

**What is stored and erased**

9. Consent records are erased with the learner, as the old consent link was
   (question 7). After erasure TutoBuddy holds no proof that consent existed.
10. A spent school code keeps its row (school, the school's reference, the
    date on the slip) after the learner is erased, so a withdrawn consent
    cannot be reused without a new slip. It holds no name or phone number.
11. The guardian's WhatsApp number and name are stored on the consent record.
    Their chat with Katlego is not written to the chat log, and their phone
    keeps no session, so erasing the learner leaves nothing under the
    guardian's number.
12. Voice notes and slip photos (milestone 5) are stored as bytes in
    Postgres with no retention period, and a voice note is transcribed
    before the gate like any other voice note. `needs_review` flags every
    slip and any voice note whose transcript lacks "agree"; there is no
    review screen yet, only a database query.
13. Learners who signed up before this branch have no consent record. There
    is no backfill. A fresh database for the pilot avoids the question.

**Platform**

14. With WhatsApp usernames, the account identifier Katlego receives may not
    be a phone number. The code stores whatever WhatsApp sends as the sender.
    Untested against the real API.
15. The `wa.me` link is only built when `WHATSAPP_PUBLIC_NUMBER` is set.
    Without it the learner is told to pass on the code by hand.
