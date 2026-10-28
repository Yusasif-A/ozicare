# OziCare — closing the screening-to-care loop

Every actionable screening result is communicated on WhatsApp or by phone, guided to the right next step, owned by a staff member, and closed with evidence.

## How it fits together

```
 Staff dashboard (Next.js, English)        Lab / EHR ──POST /api/ingest──┐
        │  /api/*                                                         │
        ▼                                                                 ▼
 ┌──────────────────────── ozicare API (FastAPI) ─────────────────────────────┐
 │ cases.py      state machine, SLA, owner rules, audit                        │
 │ scheduler.py  first contact, reminders, overdue, urgent auto-escalation     │
 │ conversation  WhatsApp router: emergency → language → identity → intents    │
 │ llm.py        Gemma, grounded on content.py only, every reply guard-checked │
 │ voice_tools   case tools shared by both voice paths (/tools/* for Bimpe)    │
 └─────┬──────────────────────┬────────────────────────────┬──────────────────┘
       │ Meta Cloud API        │ Bimpe calls.make            │ LiveKit connector
       ▼                       ▼                             ▼
  WhatsApp text (EN/AR)   Phone-number calls          WhatsApp voice calls
                          (Bimpe's own voice)         voice_agent.py:
                                                      ElevenLabs STT + TTS (EN/AR), Gemma
```

| Channel | Transport | Speech |
|---|---|---|
| WhatsApp text | Meta Cloud API direct | — |
| Phone-number call | BimpeAI hosted agent | Bimpe (set in Bimpe Console) |
| WhatsApp voice call | LiveKit WhatsApp connector | ElevenLabs Scribe v2 realtime + Flash v2.5 |

Breeze TTS was measured and dropped: ~11 s to first audio per sentence vs ~0.4 s for ElevenLabs Flash.

## Run it

```bash
# API + scheduler + webhooks
.venv/Scripts/python -m uvicorn ozicare.main:app --port 8010

# LiveKit voice agent (WhatsApp calls)
.venv/Scripts/python -m ozicare.voice_agent dev

# Dashboard
cd dashboard && npm run dev        # http://localhost:3000

# Rehearse without texting anyone: WhatsApp sends are logged, not sent
WHATSAPP_DRY_RUN=1 .venv/Scripts/python -m uvicorn ozicare.main:app --port 8010

# Tests (throwaway ozicare_test DB, WhatsApp captured not sent)
.venv/Scripts/python -m pytest tests -q
```

Sign in as `admin@ozicare.demo` with `ADMIN_PASSWORD` from `.env`. Demo staff `navigator@ozicare.demo` and `clinician@ozicare.demo` share the same password.

## Run it with Docker

One image, two services: `api` (API, scheduler, webhooks) and `voice-agent` (LiveKit WhatsApp calls). Ports come from `.env` (`APP_PORT`, default 8010; `AGENT_HTTP_PORT`, default 8091). Host networking, so `APP_PORT` binds directly on the host. Secrets are passed in at run time and never baked into the image. The dashboard isn't part of the image; it's on Firebase.

```bash
docker compose up -d --build
docker compose logs -f api
docker compose logs -f voice-agent
```

`requirements.lock` is the exact package set from the working venv and is installed with `--no-deps`. Regenerate it after changing packages: `.venv/Scripts/python -m pip freeze > requirements.lock` (drop pytest).

## Dashboard on Firebase (project `ozi-care`)

Live at **https://ozi-care.web.app**. It is a static export (`out/`), same pattern as the avalio dashboard.

```bash
cd dashboard
npm run build
firebase deploy --only hosting      # .firebaserc already points at ozi-care
```

The dashboard calls the API from the browser. The default is `http://localhost:8010`. To use another backend (e.g. an ngrok URL), click **"Server: … · change"** on the login page; it is remembered in that browser, so a new ngrok URL needs no redeploy. When the site talks to a backend on your own laptop, Chrome/Edge asks once to **allow access to the local network**: click Allow.

## Going live — what still needs a human

1. **Public URL.** `ngrok http 8010`, set `PUBLIC_BASE_URL`, and point the Meta webhook at `<url>/webhook/whatsapp` (subscribe `messages` and `calls`).
2. **WhatsApp templates.** Meta only delivers business-initiated messages from approved templates. Submit `ozicare_followup` in English and Arabic (body below), then set `WHATSAPP_TEMPLATE_EN` / `WHATSAPP_TEMPLATE_AR`. Until then, first contact only reaches patients who messaged the number in the last 24 h.
   > Hello {{1}}, this is {{2}}. You have a follow-up from your recent health screening that needs your attention. Reply 1 to explain, 2 for booking help, 3 for a call.
3. **Bimpe.** Create a *new* OziCare agent in the Bimpe Console (do not reuse the fraud agent), set `BIMPEAI_AGENT_ID`, then `python -m ozicare.bimpe setup --tools-base-url <PUBLIC_BASE_URL>`. Pick the voice under Settings → Voice, and a number under Deploy → Telephony.

## Safety rules (spec §8)

- Critical paths (first contact, explanation, booking, escalation, decline) are approved templates in `content.py`, EN + AR.
- The LLM answers free-text only, from approved knowledge + the case summary; every reply is checked by `guard.py` (diagnosis, dosing, "skip care") and replaced with template text if it fails. The voice agent vets every sentence before it is spoken.
- Emergency symptoms are caught by pattern before the LLM sees them → emergency advice + escalation to a clinician.
- Nothing about the result is shared until the patient confirms their identity.
- Every status change, contact, AI answer, block and staff action is in the audit log (`/api/audit/export`).

## Out of scope for the MVP

Full EHR sync, genomic risk models, insurance, multi-country compliance packs, a native patient app. The clinic directory and appointment slots are simulated (`content.CLINIC`, `cases.next_slots`); a pilot plugs in the clinic's booking system there.
