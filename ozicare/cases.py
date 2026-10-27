"""
The case engine: state machine, SLA timers, ownership, audit.

Every state change goes through transition(), which refuses illegal moves and
writes an audit event. Nothing else in the codebase sets `status` directly —
that is how "audit every status change" stays true.

`overdue` is a flag, not a status: an overdue case is still `contacted` or
`booked`, and the board needs to know both. The scheduler sets it when
`sla_due_at` passes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from pymongo import ReturnDocument


from .config import settings
from .db import db, new_id, now

logger = logging.getLogger("ozicare.cases")

OPEN = ("new", "contacted", "acknowledged", "booked", "in_care", "escalated")
CLOSED = ("closed_completed", "closed_declined", "closed_lost", "closed_transferred")
STATUSES = OPEN + CLOSED
URGENCIES = ("routine", "soon", "urgent")
CLOSE_REASONS = {
    "closed_completed": "completed",
    "closed_declined": "declined",
    "closed_lost": "lost_to_follow_up",
    "closed_transferred": "transferred",
}

TRANSITIONS: dict[str, set[str]] = {
    "new": {"contacted", "acknowledged", "escalated", *CLOSED},
    "contacted": {"acknowledged", "booked", "escalated", *CLOSED},
    "acknowledged": {"booked", "escalated", *CLOSED},
    "booked": {"in_care", "acknowledged", "escalated", *CLOSED},
    "in_care": {"escalated", *CLOSED},
    "escalated": {"contacted", "acknowledged", "booked", "in_care", *CLOSED},
    # Closed is terminal for the system; staff can reopen (see reopen()).
    **{c: set() for c in CLOSED},
}


class TransitionError(ValueError):
    pass


# --------------------------------------------------------------------------
# Patients
# --------------------------------------------------------------------------


def normalize_phone(raw: str) -> str:
    """E.164 with a leading +. Rejects anything that cannot be a phone number."""
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+"):
        digits = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise ValueError(f"not a valid international phone number: {raw!r}")
    return digits


def first_name(display_name: str) -> str:
    return (display_name or "").split()[0] if display_name else ""


async def upsert_patient(phone: str, display_name: str, language: str) -> dict:
    ts = now()
    return await db().patients.find_one_and_update(
        {"phone_e164": phone},
        {
            "$set": {"display_name": display_name, "preferred_language": language, "updated_at": ts},
            "$setOnInsert": {"_id": new_id("PT"), "phone_e164": phone, "consent_at": None, "created_at": ts},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


async def log_event(case_id: str, actor: str, type_: str, payload: dict | None = None, actor_id: str | None = None) -> None:
    await db().events.insert_one(
        {
            "_id": new_id("EV"),
            "case_id": case_id,
            "actor": actor,  # system | patient | staff | ai
            "actor_id": actor_id,
            "type": type_,
            "payload": payload or {},
            "created_at": now(),
        }
    )


async def log_message(
    case_id: str | None,
    channel: str,
    direction: str,
    body: str,
    *,
    provider_message_id: str | None = None,
    meta: dict | None = None,
    phone: str | None = None,
) -> str:
    mid = new_id("MS")
    await db().messages.insert_one(
        {
            "_id": mid,
            "case_id": case_id,
            "channel": channel,  # whatsapp | voice | system
            "direction": direction,  # outbound | inbound
            "body": body,
            "phone": phone,
            "provider_message_id": provider_message_id,
            "delivery": "sent" if direction == "outbound" else None,
            "meta": meta or {},
            "created_at": now(),
        }
    )
    return mid


# --------------------------------------------------------------------------
# SLA
# --------------------------------------------------------------------------


def contact_window(urgency: str) -> timedelta:
    s = settings.sla
    return timedelta(minutes={"urgent": s.urgent_contact_min, "soon": s.soon_contact_min}.get(urgency, s.routine_contact_min))


def ack_window(urgency: str) -> timedelta:
    s = settings.sla
    return timedelta(minutes={"urgent": s.urgent_ack_min, "soon": s.soon_ack_min}.get(urgency, s.routine_ack_min))


# --------------------------------------------------------------------------
# Ownership — the "simple rule table" from the spec
# --------------------------------------------------------------------------


async def pick_owner(urgency: str) -> dict | None:
    """
    Urgent goes to the least-loaded clinician, everything else to the
    least-loaded navigator. Falls back to anyone who can own cases.
    """
    roles = ["clinician"] if urgency == "urgent" else ["navigator"]
    for pool in (roles, ["navigator", "clinician", "admin"]):
        staff = [s async for s in db().staff_users.find({"role": {"$in": pool}, "active": {"$ne": False}})]
        if not staff:
            continue
        loads = {
            row["_id"]: row["n"]
            async for row in await db().cases.aggregate(
                [{"$match": {"status": {"$in": list(OPEN)}}}, {"$group": {"_id": "$owner_staff_id", "n": {"$sum": 1}}}]
            )
        }
        return min(staff, key=lambda s: loads.get(s["_id"], 0))
    return None


# --------------------------------------------------------------------------
# Case lifecycle
# --------------------------------------------------------------------------


async def create_case(
    *,
    phone: str,
    display_name: str,
    language: str,
    screening_type: str,
    urgency: str,
    result_summary: str = "",
    source: str = "demo",
    location: str = "",
    external_ref: str = "",
    actor: str = "staff",
    actor_id: str | None = None,
) -> dict:
    phone = normalize_phone(phone)
    if urgency not in URGENCIES:
        raise ValueError(f"urgency must be one of {URGENCIES}")
    from .content import SCREENING_TYPES

    if screening_type not in SCREENING_TYPES:
        raise ValueError(f"screening_type must be one of {SCREENING_TYPES}")
    language = language if language in ("en", "ar") else "en"

    patient = await upsert_patient(phone, display_name.strip(), language)
    owner = await pick_owner(urgency)
    ts = now()
    case = {
        "_id": new_id("OC"),
        "patient_id": patient["_id"],
        "phone": phone,
        "patient_name": display_name.strip(),
        "language": language,
        "source": source,
        "location": location,
        "external_ref": external_ref,
        "screening_type": screening_type,
        "result_summary": result_summary.strip(),
        "urgency": urgency,
        "status": "new",
        "owner_staff_id": owner["_id"] if owner else None,
        "owner_name": owner["name"] if owner else None,
        # Contact now. The scheduler picks this up within one tick, and the
        # API also fires it immediately so the happy path is under a minute.
        "next_action_at": ts,
        "sla_due_at": ts + contact_window(urgency),
        "attempts": 0,
        "overdue": False,
        "identity_confirmed": False,
        "conv_state": None,
        "appointment": None,
        "offered_slots": [],
        "escalation": None,
        "first_contact_at": None,
        "acknowledged_at": None,
        "booked_at": None,
        "closed_reason": None,
        "closed_at": None,
        "created_at": ts,
        "updated_at": ts,
    }
    await db().cases.insert_one(case)
    await log_event(
        case["_id"],
        actor,
        "created",
        {"source": source, "urgency": urgency, "screening_type": screening_type, "owner": case["owner_name"]},
        actor_id,
    )
    logger.info("Case %s created (%s, %s) owner=%s", case["_id"], screening_type, urgency, case["owner_name"])
    return case


async def get_case(case_id: str) -> dict | None:
    return await db().cases.find_one({"_id": case_id})


async def update_case(case_id: str, fields: dict) -> dict | None:
    fields = {**fields, "updated_at": now()}
    return await db().cases.find_one_and_update({"_id": case_id}, {"$set": fields}, return_document=ReturnDocument.AFTER)


async def transition(
    case_id: str,
    to: str,
    *,
    actor: str,
    actor_id: str | None = None,
    note: str = "",
    extra: dict | None = None,
) -> dict:
    """
    Move a case to a new status, or raise TransitionError.

    Moving to the status it is already in is a no-op rather than an error: a
    patient pressing "Help me book" twice must not 500 the webhook.
    """
    case = await get_case(case_id)
    if case is None:
        raise TransitionError(f"no case {case_id}")
    frm = case["status"]
    if to == frm:
        if extra:
            case = await update_case(case_id, extra)
        return case
    if to not in TRANSITIONS.get(frm, set()):
        raise TransitionError(f"cannot move {case_id} from {frm} to {to}")

    ts = now()
    fields: dict = {"status": to, **(extra or {})}
    if to == "contacted" and not case.get("first_contact_at"):
        fields["first_contact_at"] = ts
    if to == "acknowledged" and not case.get("acknowledged_at"):
        fields["acknowledged_at"] = ts
    if to == "booked":
        fields["booked_at"] = ts
    if to in CLOSED:
        fields.update(closed_reason=CLOSE_REASONS[to], closed_at=ts, next_action_at=None, overdue=False, conv_state=None)
    # Every forward move resets the SLA clock for whatever is due next.
    if to in ("contacted", "acknowledged"):
        fields.setdefault("sla_due_at", ts + ack_window(case["urgency"]))
        fields["overdue"] = False
    if to in ("booked", "in_care", "escalated"):
        fields["overdue"] = False

    updated = await update_case(case_id, fields)
    await log_event(case_id, actor, "status_changed", {"from": frm, "to": to, "note": note}, actor_id)
    logger.info("Case %s: %s -> %s (%s)", case_id, frm, to, actor)
    return updated


async def reopen(case_id: str, *, actor_id: str, note: str) -> dict:
    case = await get_case(case_id)
    if case is None or case["status"] not in CLOSED:
        raise TransitionError("only a closed case can be reopened")
    updated = await update_case(
        case_id,
        {"status": "contacted", "closed_reason": None, "closed_at": None, "next_action_at": now(), "sla_due_at": now() + ack_window(case["urgency"])},
    )
    await log_event(case_id, "staff", "reopened", {"from": case["status"], "note": note}, actor_id)
    return updated


async def active_case_for_phone(phone: str) -> dict | None:
    """The newest open case for this number — that is the one a reply is about."""
    try:
        phone = normalize_phone(phone)
    except ValueError:
        return None
    return await db().cases.find_one({"phone": phone, "status": {"$in": list(OPEN)}}, sort=[("created_at", -1)])


async def latest_case_for_phone(phone: str) -> dict | None:
    try:
        phone = normalize_phone(phone)
    except ValueError:
        return None
    return await db().cases.find_one({"phone": phone}, sort=[("created_at", -1)])


# --------------------------------------------------------------------------
# Shared actions — called by WhatsApp, the LiveKit agent and the Bimpe tools
# --------------------------------------------------------------------------


async def acknowledge(case: dict, actor: str = "patient", channel: str = "whatsapp") -> dict:
    if case["status"] in ("new", "contacted", "escalated"):
        return await transition(case["_id"], "acknowledged", actor=actor, note=f"patient engaged on {channel}")
    return case


async def book(case: dict, slot: dict, actor: str = "patient", channel: str = "whatsapp") -> dict:
    from .content import CLINIC

    lang = case.get("language", "en")
    appt = {"slot_iso": slot["iso"], "label": slot["label"], "clinic": CLINIC[lang]["name"], "address": CLINIC[lang]["address"], "channel": channel}
    if case["status"] in ("new", "contacted", "escalated"):
        case = await transition(case["_id"], "acknowledged", actor=actor, note=f"booked on {channel}")
    # Day-before reminder; for a slot booked less than a day ahead, a
    # same-day reminder two hours before instead of one sent straight away.
    slot_at = datetime.fromisoformat(slot["iso"])
    reminder_at = slot_at - timedelta(hours=24)
    if reminder_at < now() + timedelta(hours=1):
        reminder_at = slot_at - timedelta(hours=2)
    case = await transition(
        case["_id"],
        "booked",
        actor=actor,
        note=f"{slot['label']} via {channel}",
        extra={
            "appointment": appt,
            "conv_state": None,
            "offered_slots": [],
            "next_action_at": max(reminder_at, now() + timedelta(minutes=30)),
            "next_action": "appointment_reminder",
            # Attendance is due by the end of the appointment day.
            "sla_due_at": datetime.fromisoformat(slot["iso"]) + timedelta(hours=12),
        },
    )
    await log_event(case["_id"], actor, "booked", appt)
    return case


async def escalate(case: dict, reason: str, *, actor: str = "system", actor_id: str | None = None, summary: str = "") -> dict:
    """
    Hand the case to a human. Urgent escalations go to a clinician even if a
    navigator owns the case.
    """
    owner_fields = {}
    if case["urgency"] == "urgent" or "emergency" in reason.lower():
        clin = await db().staff_users.find_one({"role": "clinician", "active": {"$ne": False}})
        if clin:
            owner_fields = {"owner_staff_id": clin["_id"], "owner_name": clin["name"]}
    esc = {"reason": reason, "summary": summary, "at": now(), "by": actor}
    if case["status"] in CLOSED:
        return case
    case = await transition(case["_id"], "escalated", actor=actor, actor_id=actor_id, note=reason, extra={"escalation": esc, "conv_state": None, **owner_fields})
    await log_event(case["_id"], actor, "escalated", {"reason": reason, "summary": summary, "owner": case.get("owner_name")}, actor_id)
    return case


def next_slots(lang: str, n: int = 3) -> list[dict]:
    """
    Simulated clinic availability: the next n weekday slots from tomorrow.
    A pilot swaps this for the clinic's booking system.
    """
    days_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days_ar = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    # One slot per weekday, rotating the time, reads like real availability.
    times = [(9, 30), (11, 0), (14, 0)]
    out: list[dict] = []
    day = now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
    while len(out) < n:
        if day.weekday() < 5:
            h, m = times[len(out) % len(times)]
            slot = day.replace(hour=h, minute=m)
            if lang == "ar":
                label = f"{days_ar[slot.weekday()]} {slot.day}/{slot.month} الساعة {slot:%H:%M}"
            else:
                label = f"{days_en[slot.weekday()]} {slot.day} {slot:%b} {slot:%H:%M}"
            out.append({"iso": slot.isoformat(), "label": label})
        day += timedelta(days=1)
    return out


def public(case: dict) -> dict:
    """Case as JSON for the dashboard."""
    out = {k: v for k, v in case.items() if k != "_id"}
    out["id"] = case["_id"]
    for k, v in list(out.items()):
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    if isinstance(out.get("escalation"), dict) and isinstance(out["escalation"].get("at"), datetime):
        out["escalation"] = {**out["escalation"], "at": out["escalation"]["at"].isoformat()}
    return out



