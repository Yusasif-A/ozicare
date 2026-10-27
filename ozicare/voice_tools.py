"""
What a voice agent may do on a call — one implementation, two callers.

  - Bimpe (phone-number calls) reaches these over HTTP: router below, /tools/*
  - the LiveKit agent (WhatsApp calls) imports the functions directly

Call state lives in Mongo (`calls`), not process memory, so the "run one
worker only" limitation of the fraud tool server is gone.

The identity gate from the fraud agent survives in a lighter form: until the
patient confirms their name, the tools return nothing about the result.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import cases, content
from .config import settings
from .db import db, now

logger = logging.getLogger("ozicare.voice_tools")


# --------------------------------------------------------------------------
# Call records
# --------------------------------------------------------------------------


async def open_call(case: dict | None, *, provider: str, direction: str, keys: list[str], phone: str = "") -> dict:
    call = {
        "_id": f"CALL-{secrets.token_hex(4).upper()}",
        "keys": [k for k in keys if k],
        "case_id": case["_id"] if case else None,
        "phone": phone or (case or {}).get("phone", ""),
        "provider": provider,  # bimpe | livekit
        "direction": direction,  # outbound | inbound
        "status": "active",
        "identity_confirmed": False,
        "actions": [],
        "started_at": now(),
        "ended_at": None,
    }
    await db().calls.insert_one(call)
    if case:
        await cases.log_event(case["_id"], "system", "call_started", {"call": call["_id"], "provider": provider, "direction": direction})
    return call


async def add_call_key(call_id: str, key: str) -> None:
    await db().calls.update_one({"_id": call_id}, {"$addToSet": {"keys": key}})


async def _record(call: dict, action: str) -> None:
    await db().calls.update_one({"_id": call["_id"]}, {"$push": {"actions": action}})


async def _case_for(call: dict) -> dict | None:
    return await cases.get_case(call["case_id"]) if call.get("case_id") else None


# --------------------------------------------------------------------------
# The tools. Each returns a short instruction-style string for the model.
# --------------------------------------------------------------------------


async def get_case_briefing(call: dict) -> dict:
    case = await _case_for(call)
    if case is None:
        return {
            "has_case": False,
            "instruction": "There is no open screening follow-up for this caller. Say so politely, suggest they contact the clinic where they were screened, and end the call.",
        }
    lang = case["language"]
    who = "We called the patient." if call["direction"] == "outbound" else "The patient called us."
    return {
        "has_case": True,
        "first_name": cases.first_name(case["patient_name"]),
        "language": "Arabic" if lang == "ar" else "English",
        "organisation": settings.app.org_name,
        "urgency": case["urgency"],
        "identity_confirmed": bool(call.get("identity_confirmed")),
        "status": case["status"],
        "instruction": (
            f"{who} Greet them, say you are an automated assistant from {settings.app.org_name}, "
            f"and ask if you are speaking with {cases.first_name(case['patient_name'])}. "
            "Say nothing about the screening until they confirm, then call confirm_identity."
        ),
    }


async def confirm_identity(call: dict, confirmed: bool) -> str:
    case = await _case_for(call)
    if case is None:
        return "No case. End the call politely."
    if not confirmed:
        await _record(call, "identity_denied")
        await cases.escalate(case, "Person who answered the call says they are not the patient — check the phone number", actor="patient")
        return "Do not share anything. Apologise for the trouble, say the team will check their details, and end the call."
    await db().calls.update_one({"_id": call["_id"]}, {"$set": {"identity_confirmed": True}})
    await db().patients.update_one({"_id": case["patient_id"]}, {"$set": {"consent_at": now()}})
    await cases.update_case(case["_id"], {"identity_confirmed": True})
    await cases.acknowledge(case, channel="voice")
    await _record(call, "identity_confirmed")
    s = content.screening(case["screening_type"], case["language"])
    return f"Identity confirmed. Tell them this call is about their {s['name']}, then call explain_result."


async def explain_result(call: dict) -> str:
    case = await _case_for(call)
    gate = _gate(call, case)
    if gate:
        return gate
    lang = case["language"]
    s = content.screening(case["screening_type"], lang)
    await _record(call, "explained")
    await cases.log_event(case["_id"], "ai", "explained", {"channel": "voice"})
    return (
        "Explain this in your own warm, plain words, one or two sentences at a time, and check they follow. "
        "Do not add any medical facts beyond it.\n"
        f"EXPLANATION: {s['explain']}\n"
        + (f"CASE NOTE: {case['result_summary']}\n" if case.get("result_summary") else "")
        + "NEXT STEPS: " + " ".join(s["next_steps"]) + "\n"
        f"WARNING SIGNS (mention once): if they have {s['warning']}, go to emergency care now.\n"
        "Then offer to book the follow-up appointment."
    )


async def get_available_slots(call: dict) -> str:
    case = await _case_for(call)
    gate = _gate(call, case)
    if gate:
        return gate
    slots = cases.next_slots(case["language"])
    await cases.update_case(case["_id"], {"offered_slots": slots})
    clinic = content.CLINIC[case["language"]]["name"]
    listing = "; ".join(f"option {i}: {s['label']}" for i, s in enumerate(slots, 1))
    return f"Offer these follow-up slots at {clinic}: {listing}. When they choose, call book_slot with the option number (1, 2 or 3)."


async def book_slot(call: dict, option: int) -> str:
    case = await _case_for(call)
    gate = _gate(call, case)
    if gate:
        return gate
    slots = case.get("offered_slots") or cases.next_slots(case["language"])
    if not 1 <= option <= len(slots):
        return f"There is no option {option}. Ask them to choose 1 to {len(slots)}."
    case = await cases.book(case, slots[option - 1], actor="patient", channel="voice")
    await _record(call, f"booked:{slots[option - 1]['label']}")
    appt = case["appointment"]
    s = content.screening(case["screening_type"], case["language"])
    # A written confirmation they can re-read later — best effort. say() logs
    # and swallows delivery failures, so only claim it was sent if it was.
    from . import conversation

    pid = await conversation.say(
        case,
        content.t("booked", case["language"], slot=appt["label"], clinic=appt["clinic"], address=appt["address"], bring=s["bring"]),
        meta={"kind": "booked", "from_call": call["_id"]},
    )
    sent = " A confirmation has been sent to their WhatsApp." if pid else ""
    return f"Booked: {appt['label']} at {appt['clinic']}. Tell them, and that they should bring: {s['bring']}.{sent}"


async def request_human(call: dict, reason: str) -> str:
    case = await _case_for(call)
    if case is None:
        return "Tell them to contact the clinic where they were screened, and end the call."
    from . import conversation

    await _record(call, "human_requested")
    await conversation.escalate_with_summary(case, f"From {call['provider']} call: {reason}", actor="patient", pause_ai=False)
    return "A member of the care team will call them back soon. Tell them that, and that for an emergency they should call emergency services now. Then end the call."


async def report_emergency(call: dict, symptoms: str) -> str:
    case = await _case_for(call)
    if case:
        from . import conversation

        await _record(call, "emergency")
        await conversation.escalate_with_summary(case, f"Possible emergency on call: {symptoms}", actor="patient", pause_ai=False)
    return "Tell them clearly and calmly to go to the nearest emergency department or call emergency services right now. Say the care team has been alerted. Then end the call."


async def record_decline(call: dict, reason: str) -> str:
    case = await _case_for(call)
    gate = _gate(call, case)
    if gate:
        return gate
    await cases.transition(case["_id"], "closed_declined", actor="patient", note=f"Declined on call: {reason}")
    await _record(call, "declined")
    return "Recorded. Tell them you respect their choice and they can message or call back any time if they change their mind. Then end the call."


async def end_call(call: dict, summary: str = "") -> str:
    await db().calls.update_one({"_id": call["_id"]}, {"$set": {"status": "ended", "ended_at": now(), "agent_summary": summary}})
    if call.get("case_id"):
        await cases.log_event(call["case_id"], "system", "call_ended", {"call": call["_id"], "summary": summary})
    return "Say a short goodbye."


def _gate(call: dict, case: dict | None) -> str | None:
    if case is None:
        return "There is no open case for this caller. Do not discuss any results."
    if case["status"] in cases.CLOSED:
        return "This follow-up is already closed. Ask if there is anything else and offer a callback from the team."
    if not call.get("identity_confirmed"):
        return "Identity not confirmed yet. Ask if you are speaking with the patient by first name and call confirm_identity first."
    return None


# --------------------------------------------------------------------------
# HTTP surface for Bimpe
# --------------------------------------------------------------------------

router = APIRouter(prefix="/tools", tags=["bimpe-tools"])


def require_tool_token(authorization: Annotated[str | None, Header()] = None) -> None:
    # Fails closed, like the fraud tool server: no token configured, no tools.
    if not settings.bimpe.tool_token:
        raise HTTPException(503, "BIMPEAI_TOOL_TOKEN is not set; refusing to serve patient tools unauthenticated")
    if authorization != f"Bearer {settings.bimpe.tool_token}":
        raise HTTPException(401, "bad or missing bearer token")


async def resolve_call(session_id: str | None) -> dict:
    """
    Bimpe never substitutes {{session_id}} (lesson from the fraud agent), so a
    missing or literal-template id falls back to the newest active Bimpe call —
    refusing only when the active calls belong to different patients, which is
    the one case where guessing could read one patient's result to another.
    """
    if session_id and "{{" not in session_id:
        call = await db().calls.find_one({"keys": session_id})
        if call:
            return call
    since = now() - timedelta(minutes=30)
    active = [c async for c in db().calls.find({"provider": "bimpe", "status": "active", "started_at": {"$gte": since}}).sort("started_at", -1)]
    if not active:
        raise HTTPException(409, "No call is briefed. Place calls from the OziCare dashboard.")
    if len({c.get("case_id") for c in active}) > 1:
        raise HTTPException(409, "Several patients have calls in flight and no session_id was given; cannot match safely.")
    return active[0]


class SessionBody(BaseModel):
    session_id: str | None = None


class ConfirmBody(SessionBody):
    confirmed: bool = Field(description="True if the person confirmed they are the patient.")


class OptionBody(SessionBody):
    option: int = Field(description="The slot option number the patient chose: 1, 2 or 3.")


class ReasonBody(SessionBody):
    reason: str = Field(default="", description="Short reason, in the patient's words if possible.")


class SymptomsBody(SessionBody):
    symptoms: str = Field(description="What the patient described.")


class SummaryBody(SessionBody):
    summary: str = Field(default="", description="One sentence: what was agreed on this call.")


_dep = [Depends(require_tool_token)]


@router.post("/get_case_briefing", dependencies=_dep)
async def http_briefing(body: SessionBody = SessionBody()) -> dict:
    return await get_case_briefing(await resolve_call(body.session_id))


@router.post("/confirm_identity", dependencies=_dep)
async def http_confirm(body: ConfirmBody) -> dict:
    return {"result": await confirm_identity(await resolve_call(body.session_id), body.confirmed)}


@router.post("/explain_result", dependencies=_dep)
async def http_explain(body: SessionBody = SessionBody()) -> dict:
    return {"result": await explain_result(await resolve_call(body.session_id))}


@router.post("/get_available_slots", dependencies=_dep)
async def http_slots(body: SessionBody = SessionBody()) -> dict:
    return {"result": await get_available_slots(await resolve_call(body.session_id))}


@router.post("/book_slot", dependencies=_dep)
async def http_book(body: OptionBody) -> dict:
    return {"result": await book_slot(await resolve_call(body.session_id), body.option)}


@router.post("/request_human", dependencies=_dep)
async def http_human(body: ReasonBody) -> dict:
    return {"result": await request_human(await resolve_call(body.session_id), body.reason)}


@router.post("/report_emergency", dependencies=_dep)
async def http_emergency(body: SymptomsBody) -> dict:
    return {"result": await report_emergency(await resolve_call(body.session_id), body.symptoms)}


@router.post("/record_decline", dependencies=_dep)
async def http_decline(body: ReasonBody) -> dict:
    return {"result": await record_decline(await resolve_call(body.session_id), body.reason)}


@router.post("/end_call", dependencies=_dep)
async def http_end(body: SummaryBody = SummaryBody()) -> dict:
    return {"result": await end_call(await resolve_call(body.session_id), body.summary)}
