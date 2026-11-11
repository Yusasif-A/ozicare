"""
The patient's own page: OziCare's patient app, reached from a link in the
WhatsApp messages (PATIENT_APP_URL/p?t=<token>).

The token is long and random, so the link itself is the key, like a parcel-
tracking link. It only ever shows what the WhatsApp conversation would show:
until the person has confirmed who they are, the page asks them to, and says
nothing about the result. Nothing here needs a staff login.

In a deployment with a national health app, the same data comes out of the
FHIR endpoints instead (see fhir.py); this page is the stand-in for the demo.
"""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import cases, content, guard, referrals
from .config import settings
from .db import db, now

router = APIRouter(prefix="/api/p", tags=["patient"])

# Where the patient is in the loop, in their words.
STEPS = ("result", "referral", "booked", "visit", "done")
STEP_OF_STATUS = {
    "new": "result",
    "contacted": "result",
    "acknowledged": "referral",
    "escalated": "referral",
    "booked": "booked",
    "in_care": "visit",
    "closed_completed": "done",
}


def new_token() -> str:
    return secrets.token_urlsafe(18)


async def ensure_token(case: dict) -> str:
    if case.get("patient_token"):
        return case["patient_token"]
    token = new_token()
    await db().cases.update_one({"_id": case["_id"]}, {"$set": {"patient_token": token}})
    case["patient_token"] = token
    return token


def link_for(case: dict) -> str:
    base = settings.app.patient_app_url
    return f"{base}/p?t={case['patient_token']}" if base and case.get("patient_token") else ""


async def _by_token(token: str) -> dict:
    if not token or len(token) < 16:
        raise HTTPException(404, "link not found")
    case = await db().cases.find_one({"patient_token": token})
    if case is None:
        raise HTTPException(404, "link not found")
    return case


def _view(case: dict, lang: str | None = None) -> dict:
    lang = lang if lang in ("en", "ar") else case.get("language", "en")
    base = {
        "language": lang,
        "first_name": cases.first_name(case["patient_name"]),
        "org": settings.app.org_name,
        "identity_confirmed": bool(case.get("identity_confirmed")),
        "status": case["status"],
        "closed": case["status"] in cases.CLOSED,
    }
    if not case.get("identity_confirmed"):
        return base
    s = content.screening(case["screening_type"], lang)
    ref = case.get("referral") or {}
    clinic = referrals.clinic_for(case, lang)
    svc = referrals.SERVICES.get(ref.get("service", ""))
    appt = case.get("appointment")
    return {
        **base,
        "step": STEP_OF_STATUS.get(case["status"], "referral"),
        "steps": STEPS,
        "screening": s["name"],
        "explain": s["explain"],
        "note": case.get("result_summary") or "",
        "next_steps": s["next_steps"],
        "bring": s["bring"],
        "warning": content.t("warning", lang, warning=s["warning"]),
        "not_diagnosis": content.t("not_diagnosis", lang),
        "urgent": case["urgency"] == "urgent",
        "referral": {"service": svc[1] if svc and lang == "ar" else svc[0] if svc else "", "clinic": clinic["name"], "address": clinic["address"]} if ref else None,
        # Re-labelled in the page's language; stored labels are in the patient's.
        "appointment": {"label": cases.slot_label(datetime.fromisoformat(appt["slot_iso"]), lang), "clinic": clinic["name"], "address": clinic["address"]} if appt else None,
        "slots": cases.next_slots(lang) if case["status"] in ("new", "contacted", "acknowledged", "escalated") else [],
        "attended": bool(case.get("attended_at")),
        "callback_requested": bool(case.get("callback_requested_at")),
    }


@router.get("/{token}")
async def view(token: str, lang: str | None = None) -> dict:
    case = await _by_token(token)
    if not case.get("patient_page_opened_at"):
        await cases.update_case(case["_id"], {"patient_page_opened_at": now()})
        await cases.log_event(case["_id"], "patient", "patient_page_opened", {})
    return _view(case, lang)


class Confirm(BaseModel):
    is_me: bool


@router.post("/{token}/confirm")
async def confirm(token: str, body: Confirm) -> dict:
    case = await _by_token(token)
    if case["status"] in cases.CLOSED:
        return _view(case)
    if not body.is_me:
        from . import conversation

        await conversation.escalate_with_summary(case, "Person who opened the patient link says they are not the patient — check the phone number", actor="patient")
        return {**_view(case), "wrong_person": True}
    if not case.get("identity_confirmed"):
        await cases.update_case(case["_id"], {"identity_confirmed": True})
        await db().patients.update_one({"_id": case["patient_id"]}, {"$set": {"consent_at": now()}})
        await cases.log_event(case["_id"], "patient", "identity_confirmed", {"consent": True, "channel": "patient_app"})
    case = await cases.acknowledge(await cases.get_case(case["_id"]), channel="patient_app")
    return _view(case)


class Book(BaseModel):
    slot_iso: str


def _require_identity(case: dict) -> None:
    if not case.get("identity_confirmed"):
        raise HTTPException(403, "confirm who you are first")
    if case["status"] in cases.CLOSED:
        raise HTTPException(409, "this follow-up is closed")


@router.post("/{token}/book")
async def book(token: str, body: Book) -> dict:
    case = await _by_token(token)
    _require_identity(case)
    slot = next((s for s in cases.next_slots(case["language"]) if s["iso"] == body.slot_iso), None)
    if slot is None:
        raise HTTPException(409, "that time is no longer available, please pick another")
    if case["status"] == "booked":
        raise HTTPException(409, "you already have an appointment")
    from . import conversation

    case = await cases.book(case, slot, actor="patient", channel="patient_app")
    await conversation.say(case, conversation.booked_text(case), meta={"kind": "booked", "from": "patient_app"})
    return _view(case)


@router.post("/{token}/call")
async def call_me(token: str) -> dict:
    case = await _by_token(token)
    _require_identity(case)
    await cases.update_case(case["_id"], {"callback_requested_at": now()})
    await cases.log_event(case["_id"], "patient", "callback_requested", {"channel": "patient_app"})
    return _view(await cases.get_case(case["_id"]))


class Question(BaseModel):
    text: str
    lang: str | None = None


@router.post("/{token}/ask")
async def ask(token: str, body: Question) -> dict:
    """A free-text question, answered by the same guarded LLM as WhatsApp."""
    case = await _by_token(token)
    _require_identity(case)
    text = body.text.strip()[:500]
    if not text:
        raise HTTPException(400, "empty question")
    # Answer in the language the page is showing, not just the case default.
    lang = body.lang if body.lang in ("en", "ar") else case["language"]
    await cases.log_message(case["_id"], "patient_app", "inbound", text, phone=case["phone"])
    if guard.is_emergency(text):
        from . import conversation

        await conversation.escalate_with_summary(case, f"Possible emergency (patient app): {text[:200]}", actor="patient")
        reply = content.t("emergency", lang)
        await cases.log_message(case["_id"], "patient_app", "outbound", reply, meta={"kind": "emergency"}, phone=case["phone"])
        return {"reply": reply, "emergency": True}
    from . import llm

    reply, audit = await llm.answer_question(text, lang=lang, screening_type=case["screening_type"], result_summary=case.get("result_summary", ""), clinic=referrals.clinic_for(case, lang))
    failed = reply is None
    if failed:
        reply = content.t("app_fallback", lang)
    kind = "fallback" if failed else "ai_answer"
    await cases.log_message(case["_id"], "patient_app", "outbound", reply, meta={"kind": kind, "ai": audit, "by": "system" if failed else "ai"}, phone=case["phone"])
    if audit.get("blocked"):
        await cases.log_event(case["_id"], "ai", "ai_reply_blocked", audit)
    return {"reply": reply}
