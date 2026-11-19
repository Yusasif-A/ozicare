"""
The patient's own page: OziCare's patient app.

Patients sign in with their phone number and a password. The link in their
WhatsApp messages (PATIENT_APP_URL/p?t=<token>) opens the sign-in screen with
the phone filled in; the token alone shows nothing. After sign-in the page is
the same loop as WhatsApp: progress, the result explained, the referral, the
appointment, and book / call me / ask.

A patient's password is set by the care team. For the demo, the patient on
DEMO_PATIENT_PHONE gets DEMO_PATIENT_PASSWORD. Signing in with the right
password confirms the patient's identity, like replying YES on WhatsApp.

In a deployment with a national health app, the same data comes out of the
FHIR endpoints instead (see fhir.py), behind that app's own login.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import auth, cases, content, guard, referrals
from .config import settings
from .db import db, now

router = APIRouter(prefix="/api/p", tags=["patient"])

SESSION_HOURS = 12

# Where the patient is in the loop, in their words.
STEPS = ("result", "referral", "booked", "visit", "done")
STEP_OF_STATUS = {
    "new": "result",
    "contacted": "result",
    "acknowledged": "referral",
    "escalated": "referral",
    "booked": "booked",
    "in_care": "visit",
    "follow_up": "visit",
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


# --------------------------------------------------------------------------
# Accounts and sessions
# --------------------------------------------------------------------------


async def set_password(patient_id: str, password: str) -> None:
    await db().patients.update_one({"_id": patient_id}, {"$set": {"password_hash": auth.hash_password(password), "password_set_at": now()}})


async def ensure_demo_account() -> None:
    """The presenter's demo patient always has the known demo password."""
    phone, pw = settings.app.demo_patient_phone, settings.app.demo_patient_password
    if not phone or not pw:
        return
    try:
        phone = cases.normalize_phone(phone)
    except ValueError:
        return
    patient = await db().patients.find_one({"phone_e164": phone})
    if patient and not (patient.get("password_hash") and auth.check_password(pw, patient["password_hash"])):
        await set_password(patient["_id"], pw)


def _issue(patient: dict) -> str:
    if not settings.app.jwt_secret:
        raise HTTPException(503, "JWT_SECRET is not set")
    payload = {"sub": patient["_id"], "kind": "patient", "exp": now() + timedelta(hours=SESSION_HOURS)}
    return jwt.encode(payload, settings.app.jwt_secret, algorithm="HS256")


async def _patient_case(authorization: str | None) -> dict:
    """The signed-in patient's current case: the open one, else the latest."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "sign in first")
    try:
        data = jwt.decode(authorization[7:], settings.app.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "session expired, sign in again") from None
    if data.get("kind") != "patient":
        raise HTTPException(401, "sign in first")
    patient = await db().patients.find_one({"_id": data["sub"]})
    if patient is None:
        raise HTTPException(401, "account not found")
    case = await cases.active_case_for_phone(patient["phone_e164"]) or await cases.latest_case_for_phone(patient["phone_e164"])
    if case is None:
        raise HTTPException(404, "no follow-up for this account")
    return case


PatientAuth = Annotated[str | None, Header()]


class Login(BaseModel):
    phone: str
    password: str


@router.get("/link/{token}")
async def link_info(token: str) -> dict:
    """What the sign-in screen may show for a WhatsApp link: phone, masked."""
    if not token or len(token) < 16:
        raise HTTPException(404, "link not found")
    case = await db().cases.find_one({"patient_token": token})
    if case is None:
        raise HTTPException(404, "link not found")
    phone = case["phone"]
    return {"phone": phone, "phone_masked": f"{phone[:4]} ••• {phone[-4:]}", "language": case.get("language", "en")}


@router.post("/login")
async def login(body: Login) -> dict:
    try:
        phone = cases.normalize_phone(body.phone)
    except ValueError:
        raise HTTPException(401, "wrong phone number or password") from None
    patient = await db().patients.find_one({"phone_e164": phone})
    if not patient or not patient.get("password_hash") or not auth.check_password(body.password, patient["password_hash"]):
        raise HTTPException(401, "wrong phone number or password")
    case = await cases.active_case_for_phone(phone) or await cases.latest_case_for_phone(phone)
    # The right password proves who they are: the same consent as YES on WhatsApp.
    if case and not case.get("identity_confirmed") and case["status"] not in cases.CLOSED:
        await cases.update_case(case["_id"], {"identity_confirmed": True})
        await db().patients.update_one({"_id": patient["_id"]}, {"$set": {"consent_at": now()}})
        await cases.log_event(case["_id"], "patient", "identity_confirmed", {"consent": True, "channel": "patient_app"})
        case = await cases.acknowledge(await cases.get_case(case["_id"]), channel="patient_app")
    if case:
        await cases.log_event(case["_id"], "patient", "patient_signed_in", {})
    return {"token": _issue(patient), "language": (case or {}).get("language", patient.get("preferred_language", "en"))}


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------


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


@router.get("/me")
async def view(authorization: PatientAuth = None, lang: str | None = None) -> dict:
    case = await _patient_case(authorization)
    if not case.get("patient_page_opened_at"):
        await cases.update_case(case["_id"], {"patient_page_opened_at": now()})
        await cases.log_event(case["_id"], "patient", "patient_page_opened", {})
    return _view(case, lang)


def _require_open(case: dict) -> None:
    if case["status"] in cases.CLOSED:
        raise HTTPException(409, "this follow-up is closed")


class Book(BaseModel):
    slot_iso: str


@router.post("/me/book")
async def book(body: Book, authorization: PatientAuth = None) -> dict:
    case = await _patient_case(authorization)
    _require_open(case)
    slot = next((s for s in cases.next_slots(case["language"]) if s["iso"] == body.slot_iso), None)
    if slot is None:
        raise HTTPException(409, "that time is no longer available, please pick another")
    if case["status"] == "booked":
        raise HTTPException(409, "you already have an appointment")
    from . import conversation

    case = await cases.book(case, slot, actor="patient", channel="patient_app")
    await conversation.say(case, conversation.booked_text(case), meta={"kind": "booked", "from": "patient_app"})
    return _view(case)


@router.post("/me/call")
async def call_me(authorization: PatientAuth = None) -> dict:
    case = await _patient_case(authorization)
    _require_open(case)
    await cases.update_case(case["_id"], {"callback_requested_at": now()})
    await cases.log_event(case["_id"], "patient", "callback_requested", {"channel": "patient_app"})
    return _view(await cases.get_case(case["_id"]))


class Question(BaseModel):
    text: str
    lang: str | None = None


@router.post("/me/ask")
async def ask(body: Question, authorization: PatientAuth = None) -> dict:
    """A free-text question, answered by the same guarded LLM as WhatsApp."""
    case = await _patient_case(authorization)
    _require_open(case)
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
