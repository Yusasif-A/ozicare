# CareLoop — Closing the Screening-to-Care Loop
## Developer Specification (MVP → Pilot)

**Challenge:** Future Health Digital Innovation Challenge — *Closing the Screening-to-Care Loop* (Population Health)  
**Channels:** WhatsApp + mobile phone call (voice)  
**Goal:** Every actionable screening result is communicated, understood, acted on, tracked, and documented as closed.

---

## 1. What this product is (and is not)

### Is
- A **case workflow** after an actionable screening result
- Patient contact via **WhatsApp and/or phone call**
- Plain-language explanation + next-step guidance
- Staff dashboard with ownership, overdue cases, and closure
- Human escalation for urgent or out-of-scope situations

### Is not
- A diagnostic AI that replaces clinicians
- A full hospital EHR
- A requirement that the patient is already in hospital
- Genomic / multi-year risk modelling (out of MVP scope)

**Clarification:** Screening often happens in community programs, labs, PHCs, workplaces, or clinics. The patient may be at home. Hospital appears only if referral leads there.

---

## 2. Ideas from real healthcare products (what to copy)

These patterns are public examples of closing gaps after screening or risk flags:

| Organization / product | Relevant pattern | What we can reuse conceptually |
|------------------------|------------------|--------------------------------|
| **Huna** (Brazil; Future Health finalist) | AI risk from routine labs + **patient navigation** to confirmatory care; WhatsApp engagement layer | Separate **risk/result** from **navigation**; automate invite → book → remind |
| **Zuri Health** (Africa) | Mass screening → digital registration → **SMS/WhatsApp follow-up** for continuity | Register every screened person; follow up on the channel people already use |
| **PSI — Jali / Coach Mpilo AI** | WhatsApp health chatbots; info + **referral to clinics** | Scripted + AI chat on WhatsApp; connect to real providers |
| **ThinkMD** | Frontline triage + referral decision support | Clear next action (home / clinic / urgent); human override |
| **Sehhaty / Seha Virtual Hospital** (Saudi) | National digital entry + virtual consult + chronic outreach | Single front door; proactive reminders between visits |

**Product principle to steal:**  
Detection or screening alone is not enough. Value is in **navigation until closure**.

---

## 3. End-to-end process (business flow)

```
[Screening source]
   Lab / PHC / screening camp / demo admin
   marks result as ACTIONABLE (+ urgency)
           │
           ▼
[Case created]
   patient identity, result type, urgency, owner, language
           │
           ▼
[Contact patient]
   WhatsApp template and/or outbound call
   plain-language message + consent reminder
           │
           ▼
[Patient engages]
   reads / replies / requests call / books / declines
           │
     ┌─────┴─────────────────────────┐
     ▼                               ▼
[Routine path]                 [Urgent path]
 explain + book/refer          immediate human escalation
     │                               │
     ▼                               ▼
[Track status]                 [Staff handles]
 acknowledged → booked →       documents outcome
 attended / no-show / declined
           │
           ▼
[Close case]
   only with evidence or authorized staff decision
   reasons logged (completed / declined / lost-to-follow-up / transferred)
```

### Example statuses (state machine)

| Status | Meaning |
|--------|---------|
| `new` | Result imported; not yet contacted |
| `contacted` | WhatsApp and/or call attempted |
| `acknowledged` | Patient confirmed they received/understood |
| `booked` | Appointment or referral slot set |
| `in_care` | Patient attended / under active follow-up |
| `escalated` | Handed to human clinician/staff |
| `closed_completed` | Required care done |
| `closed_declined` | Patient declined after clear explanation |
| `closed_lost` | No response after defined attempts (still reportable) |
| `overdue` | SLA broken; visible on staff board |

---

## 4. System architecture

```
┌──────────────────────────────┐
│  Ingestion                   │
│  - Admin form (MVP)          │
│  - CSV upload                │
│  - Webhook from lab/EHR      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  API + Case Service          │
│  - Create/update cases       │
│  - Status transitions        │
│  - Ownership + SLA timers    │
│  - Audit log                 │
└──────┬───────────┬───────────┘
       │           │
       ▼           ▼
┌────────────┐  ┌─────────────────────────┐
│ Rules      │  │ AI Orchestrator         │
│ - urgency  │  │ - scripted templates    │
│ - channel  │  │ - LLM for Q&A (bounded) │
│ - language │  │ - never invent diagnosis│
│ - escalate │  │ - handoff summary       │
└────────────┘  └───────────┬─────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌────────────┐
        │ WhatsApp │  │ Voice    │  │ Staff Web  │
        │ Cloud API│  │ (Twilio) │  │ Dashboard  │
        └──────────┘  └──────────┘  └────────────┘
```

### Suggested tech stack (flexible)

| Layer | Options |
|-------|---------|
| Backend | Node (Nest/Express) or Python (FastAPI) |
| DB | PostgreSQL |
| Queue | Redis / BullMQ or Celery (reminders, retries) |
| WhatsApp | Meta WhatsApp Cloud API |
| Voice | Twilio Voice / similar (outbound + optional inbound) |
| AI | LLM API with **strict system prompts** + approved FAQ corpus |
| Frontend staff | React / Next.js dashboard |
| Auth | Staff login (email/password or magic link); role-based access |
| Hosting | Any cloud (Render, Railway, AWS, GCP, Azure) |

---

## 5. Data model (minimum)

### `patients`
- `id`, `phone_e164`, `display_name`, `preferred_language`, `consent_at`, `created_at`

### `cases`
- `id`, `patient_id`
- `source` (lab / phc / camp / demo)
- `screening_type` (e.g. blood_pressure, diabetes, cervical, general_abnormal)
- `result_summary` (short, non-raw clinical text approved for patient messaging)
- `urgency` (`routine` | `soon` | `urgent`)
- `status` (see state machine)
- `owner_staff_id` (nullable)
- `next_action_at`
- `closed_reason`, `closed_at`
- timestamps

### `messages`
- `id`, `case_id`, `channel` (`whatsapp` | `voice` | `system`)
- `direction` (`outbound` | `inbound`)
- `body` / `transcript`
- `provider_message_id`
- `created_at`

### `events` (audit)
- `id`, `case_id`, `actor` (`system` | `patient` | `staff`)
- `type` (created, contacted, status_changed, escalated, closed…)
- `payload_json`, `created_at`

### `staff_users`
- `id`, `name`, `email`, `role` (`viewer` | `navigator` | `clinician` | `admin`)

**Privacy rules**
- Store minimum data needed for contact and closure
- Do not put full raw lab PDFs in WhatsApp by default
- Explicit consent before sensitive detail sharing
- Access control on staff dashboard
- Audit every status change and outbound contact

---

## 6. Backend modules to build

### 6.1 Ingestion API
- `POST /api/cases` — create actionable result (admin/demo)
- `POST /api/cases/import` — CSV bulk (optional MVP+)
- Validate phone, urgency, screening_type
- On create → enqueue `notify_patient` job

### 6.2 Case engine
- Allowed status transitions only
- SLA:
  - `urgent`: contact within X minutes; escalate if no ack
  - `routine`: contact within Y hours; reminder after Z hours
- Assign default owner by location/team (simple rule table for MVP)

### 6.3 Notification service
- WhatsApp template: “You have a screening follow-up. Reply 1 explain, 2 book help, 3 call me.”
- Outbound call script (TTS or live agent later)
- Log delivery status (sent / delivered / failed)

### 6.4 Conversation handler (WhatsApp webhook)
- Map inbound phone → active case
- Intent routing:
  - explain result
  - booking help
  - request human
  - decline
  - FAQ
- AI answers only from approved knowledge + case summary
- Hard refusals: no prescribing, no “you definitely have X”

### 6.5 Voice flow (optional same day as WhatsApp)
- Outbound call plays short message + keypress or speech
- Or: patient requests call from WhatsApp → queue callback
- Store short transcript/summary on case

### 6.6 Staff actions API
- List/filter cases (`overdue`, `urgent`, `mine`)
- Update status, add note, assign owner
- Close with reason
- Escalate

### 6.7 Metrics endpoints (for demo + challenge evidence)
- Time to first contact
- Acknowledgement rate
- Booking rate
- Closure rate by reason
- Open overdue count

---

## 7. Frontend to build

### 7.1 Staff dashboard (required)
Pages:
1. **Login**
2. **Case board** — table/kanban by status; filters urgency/overdue
3. **Case detail** — timeline, messages, buttons (contact again, book, escalate, close)
4. **Create case** — demo form (patient phone, type, urgency, summary)
5. **Metrics** — simple cards for the 4–5 KPIs above

UI priorities:
- Overdue and urgent visually loud
- One-click “Mark contacted / Booked / Closed”
- Show full audit timeline

### 7.2 Patient experience (no custom app required for MVP)
- WhatsApp thread is the patient UI
- Optional lightweight web page behind a link: “Your next step” (clinic address, map link, what to bring)

### 7.3 Images
- **Not required** for core loop
- Optional later: patient uploads photo of paper result (OCR) — do not block MVP on this

---

## 8. AI behaviour rules (must implement)

**Allowed**
- Explain what “actionable screening result” means in plain language
- List approved next steps for that screening type
- Help choose channel (message vs call)
- Summarize conversation for staff on escalate

**Forbidden**
- Definitive diagnosis statements
- Medication dosing
- Telling patient to ignore clinical advice
- Requesting unnecessary sensitive data

**Implementation tip:**  
Hybrid model = **templates for critical paths** + LLM only for paraphrasing FAQs. Log every model reply.

---

## 9. Demo script (for judges)

1. Staff creates case: “Adult screening – abnormal result – urgency: soon”  
2. System sends WhatsApp  
3. Patient replies “1” → plain-language explanation  
4. Patient replies “2” → booking guidance / simulated slot  
5. Staff dashboard moves case `booked` → later `closed_completed`  
6. Second case: urgency `urgent` → auto-escalate banner + human assignment  
7. Show metrics: contact time, open vs closed  

---

## 10. Build phases

### Phase A — Core (first working slice)
- DB + create case
- WhatsApp send + inbound webhook
- Status updates
- Staff case list + detail

### Phase B — Loop quality
- Reminders / overdue
- AI FAQ layer with guardrails
- Escalation + staff notes
- Metrics page

### Phase C — Voice
- Outbound or callback voice
- Same intents as WhatsApp

### Phase D — Integration readiness
- Webhook auth for external lab
- CSV import
- Role-based access + export audit log

---

## 11. Acceptance criteria (MVP done when)

- [ ] Staff can create an actionable case without code
- [ ] Patient receives WhatsApp within 1 minute of create (happy path)
- [ ] Patient can get explanation and next-step guidance in chat
- [ ] Staff can see status timeline and close with reason
- [ ] Urgent case is visually distinct and assignable
- [ ] No AI reply claims a diagnosis beyond approved text
- [ ] Demo runs end-to-end in under 5 minutes

---

## 12. Out of scope for MVP (say so in docs)

- Full EHR bidirectional sync
- Genomic risk models
- Insurance claims
- Multi-country compliance packs (document assumptions)
- Patient-facing native mobile app

---

## 13. One-sentence product definition

**CareLoop ensures every actionable screening result is communicated on WhatsApp or phone, guided to the right next step, owned by a staff member, and closed with evidence — so early detection becomes actual care.**

---

*Document version: 1.0 — for internal build / hackathon prototype*
