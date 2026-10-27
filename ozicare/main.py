"""
OziCare API.

    uvicorn ozicare.main:app --port 8000          # API + scheduler + webhooks
    python -m ozicare.voice_agent dev             # LiveKit WhatsApp-call agent

Surfaces:
  /api/*            staff dashboard (JWT)
  /api/ingest       lab / EHR webhook (INGEST_API_KEY)
  /webhook/whatsapp Meta webhook: patient messages, delivery receipts, calls
  /tools/*          Bimpe voice tools (BIMPEAI_TOOL_TOKEN)
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import auth, bimpe, cases, content, conversation, scheduler, voice_tools, wa_calls, whatsapp
from .config import settings
from .db import close, db, ensure_indexes, now

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ozicare.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    for problem in settings.validate():
        logger.warning("CONFIG: %s", problem)
    settings.log_summary()
    await ensure_indexes()
    await auth.seed_staff()
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler.run_forever(stop))
    yield
    stop.set()
    await task
    await close()


app = FastAPI(title="OziCare", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.app.dashboard_origin.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the dashboard on ozi-care.web.app reach an API on the presenter's
    # laptop (http://localhost:8010); Chrome preflights that and Starlette
    # refuses it unless this is on.
    allow_private_network=True,
)
app.include_router(voice_tools.router)


Staff = Annotated[dict, Depends(auth.require("viewer"))]
Navigator = Annotated[dict, Depends(auth.require("navigator"))]
Admin = Annotated[dict, Depends(auth.require("admin"))]


def _iso(doc: dict) -> dict:
    out = {}
    for k, v in doc.items():
        key = "id" if k == "_id" else k
        out[key] = v.isoformat() if isinstance(v, datetime) else v
    return out


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class Login(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
async def login(body: Login) -> dict:
    user = await db().staff_users.find_one({"email": body.email.lower().strip()})
    if not user or not auth.check_password(body.password, user["password_hash"]) or user.get("active") is False:
        raise HTTPException(401, "wrong email or password")
    return {"token": auth.issue_token(user), "user": auth.public_user(user)}


@app.get("/api/auth/me")
async def me(user: Staff) -> dict:
    return auth.public_user(user)


@app.get("/api/staff")
async def list_staff(_: Staff) -> list[dict]:
    return [auth.public_user(u) async for u in db().staff_users.find().sort("name", 1)]


class NewStaff(BaseModel):
    name: str
    email: str
    role: str = "navigator"
    password: str = Field(min_length=8)


@app.post("/api/staff")
async def create_staff(body: NewStaff, user: Admin) -> dict:
    if body.role not in auth.ROLES:
        raise HTTPException(400, f"role must be one of {auth.ROLES}")
    from .db import new_id

    doc = {"_id": new_id("ST"), "name": body.name, "email": body.email.lower(), "role": body.role, "password_hash": auth.hash_password(body.password), "active": True, "created_at": now()}
    await db().staff_users.insert_one(doc)
    return auth.public_user(doc)


# --------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------


class NewCase(BaseModel):
    phone: str
    display_name: str
    language: str = "en"
    screening_type: str
    urgency: str = "routine"
    result_summary: str = ""
    source: str = "demo"
    location: str = ""
    external_ref: str = ""


async def _contact_now(case_id: str) -> None:
    """Fire first contact immediately instead of waiting for the next tick."""
    case = await cases.get_case(case_id)
    if case and case["status"] == "new":
        await conversation.contact_patient(case)


@app.get("/api/meta")
async def meta(_: Staff) -> dict:
    return {
        "screening_types": {k: v["en"]["name"] for k, v in content.SCREENING.items()},
        "urgencies": cases.URGENCIES,
        "statuses": cases.STATUSES,
        "close_statuses": cases.CLOSED,
        "channels": {"whatsapp": settings.whatsapp.configured, "phone_call": settings.bimpe.configured, "whatsapp_call": settings.livekit.configured},
    }


@app.post("/api/cases")
async def create_case(body: NewCase, user: Navigator, bg: BackgroundTasks) -> dict:
    try:
        case = await cases.create_case(**body.model_dump(), actor="staff", actor_id=user["_id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    bg.add_task(_contact_now, case["_id"])
    return cases.public(case)


@app.post("/api/cases/import")
async def import_cases(file: UploadFile, user: Navigator, bg: BackgroundTasks) -> dict:
    """CSV columns: phone, display_name, screening_type, urgency, language, result_summary, source, location, external_ref"""
    text = (await file.read()).decode("utf-8-sig")
    created, errors = [], []
    for i, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            case = await cases.create_case(
                phone=row.get("phone", ""),
                display_name=row.get("display_name") or row.get("name", ""),
                language=(row.get("language") or "en").strip().lower(),
                screening_type=(row.get("screening_type") or "").strip(),
                urgency=(row.get("urgency") or "routine").strip().lower(),
                result_summary=row.get("result_summary", ""),
                source=row.get("source") or "csv",
                location=row.get("location", ""),
                external_ref=row.get("external_ref", ""),
                actor="staff",
                actor_id=user["_id"],
            )
            created.append(case["_id"])
            bg.add_task(_contact_now, case["_id"])
        except ValueError as exc:
            errors.append({"line": i, "error": str(exc)})
    return {"created": created, "errors": errors}


@app.get("/api/cases")
async def list_cases(
    user: Staff,
    status: str | None = None,
    urgency: str | None = None,
    overdue: bool | None = None,
    mine: bool = False,
    open_only: bool = Query(False, alias="open"),
    q: str | None = None,
) -> list[dict]:
    flt: dict = {}
    if status:
        flt["status"] = {"$in": status.split(",")}
    elif open_only:
        flt["status"] = {"$in": list(cases.OPEN)}
    if urgency:
        flt["urgency"] = {"$in": urgency.split(",")}
    if overdue is not None:
        flt["overdue"] = overdue
    if mine:
        flt["owner_staff_id"] = user["_id"]
    if q:
        flt["$or"] = [{"patient_name": {"$regex": q, "$options": "i"}}, {"phone": {"$regex": q.replace("+", r"\+")}}, {"_id": q.upper()}]
    rows = [cases.public(c) async for c in db().cases.find(flt).sort("created_at", -1).limit(500)]
    # Loudest first: urgent and overdue at the top of every view.
    rank = {"urgent": 0, "soon": 1, "routine": 2}
    rows.sort(key=lambda c: (c["status"] in cases.CLOSED, not c.get("overdue"), c["status"] != "escalated", rank.get(c["urgency"], 3)))
    return rows


async def _case_or_404(case_id: str) -> dict:
    case = await cases.get_case(case_id)
    if case is None:
        raise HTTPException(404, "no such case")
    return case


@app.get("/api/cases/{case_id}")
async def case_detail(case_id: str, _: Staff) -> dict:
    case = await _case_or_404(case_id)
    patient = await db().patients.find_one({"_id": case["patient_id"]})
    messages = [_iso(m) async for m in db().messages.find({"case_id": case_id}).sort("created_at", 1)]
    events = [_iso(e) async for e in db().events.find({"case_id": case_id}).sort("created_at", 1)]
    calls = [_iso({k: v for k, v in c.items() if k != "transcript"}) async for c in db().calls.find({"case_id": case_id}).sort("started_at", -1)]
    return {"case": cases.public(case), "patient": _iso(patient or {}), "messages": messages, "events": events, "calls": calls, "allowed_transitions": sorted(cases.TRANSITIONS.get(case["status"], []))}


class StatusChange(BaseModel):
    status: str
    note: str = ""


@app.post("/api/cases/{case_id}/status")
async def change_status(case_id: str, body: StatusChange, user: Navigator) -> dict:
    case = await _case_or_404(case_id)
    if body.status in cases.CLOSED and not body.note.strip():
        raise HTTPException(400, "closing a case needs a note: what is the evidence?")
    try:
        case = await cases.transition(case_id, body.status, actor="staff", actor_id=user["_id"], note=body.note)
    except cases.TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    if body.status == "closed_completed":
        await conversation.say(case, content.t("closed_thanks", case["language"], first_name=cases.first_name(case["patient_name"])), meta={"kind": "closed"}, actor="system")
    return cases.public(case)


@app.post("/api/cases/{case_id}/reopen")
async def reopen(case_id: str, body: StatusChange, user: Navigator) -> dict:
    try:
        return cases.public(await cases.reopen(case_id, actor_id=user["_id"], note=body.note))
    except cases.TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc


class Assign(BaseModel):
    staff_id: str | None


@app.post("/api/cases/{case_id}/assign")
async def assign(case_id: str, body: Assign, user: Navigator) -> dict:
    await _case_or_404(case_id)
    owner = await db().staff_users.find_one({"_id": body.staff_id}) if body.staff_id else None
    if body.staff_id and not owner:
        raise HTTPException(404, "no such staff member")
    case = await cases.update_case(case_id, {"owner_staff_id": body.staff_id, "owner_name": owner["name"] if owner else None})
    await cases.log_event(case_id, "staff", "assigned", {"to": owner["name"] if owner else None}, user["_id"])
    return cases.public(case)


class Note(BaseModel):
    text: str


@app.post("/api/cases/{case_id}/note")
async def add_note(case_id: str, body: Note, user: Navigator) -> dict:
    await _case_or_404(case_id)
    await cases.log_event(case_id, "staff", "note", {"text": body.text, "by": user["name"]}, user["_id"])
    return {"ok": True}


class Escalate(BaseModel):
    reason: str


@app.post("/api/cases/{case_id}/escalate")
async def escalate(case_id: str, body: Escalate, user: Navigator) -> dict:
    case = await _case_or_404(case_id)
    try:
        case = await cases.escalate(case, body.reason, actor="staff", actor_id=user["_id"])
    except cases.TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    return cases.public(case)


class StaffMessage(BaseModel):
    text: str
    take_over: bool = True


@app.post("/api/cases/{case_id}/message")
async def staff_message(case_id: str, body: StaffMessage, user: Navigator) -> dict:
    """A staff member writes to the patient directly; by default the bot steps back."""
    case = await _case_or_404(case_id)
    pid = await conversation.say(case, body.text, meta={"staff": user["name"]}, actor="staff")
    if body.take_over:
        await cases.update_case(case_id, {"ai_paused": True})
    await cases.log_event(case_id, "staff", "staff_message", {"by": user["name"], "delivered": bool(pid)}, user["_id"])
    if not pid:
        raise HTTPException(502, "WhatsApp did not accept the message — see the timeline for the reason")
    return {"ok": True}


class AiToggle(BaseModel):
    paused: bool


@app.post("/api/cases/{case_id}/ai")
async def toggle_ai(case_id: str, body: AiToggle, user: Navigator) -> dict:
    await _case_or_404(case_id)
    case = await cases.update_case(case_id, {"ai_paused": body.paused})
    await cases.log_event(case_id, "staff", "ai_paused" if body.paused else "ai_resumed", {}, user["_id"])
    return cases.public(case)


@app.post("/api/cases/{case_id}/contact")
async def contact_again(case_id: str, user: Navigator) -> dict:
    case = await _case_or_404(case_id)
    if case["status"] in cases.CLOSED:
        raise HTTPException(409, "case is closed")
    ok = await conversation.contact_patient(case, reminder=case["status"] != "new")
    await cases.log_event(case_id, "staff", "manual_contact", {"delivered": ok}, user["_id"])
    if not ok:
        raise HTTPException(502, "WhatsApp did not accept the message — see the timeline for the reason")
    return cases.public(await cases.get_case(case_id))


@app.post("/api/cases/{case_id}/call")
async def call_patient(case_id: str, user: Navigator, channel: str = "phone") -> dict:
    """phone -> Bimpe dials the number; whatsapp -> LiveKit dials on WhatsApp."""
    case = await _case_or_404(case_id)
    try:
        if channel == "whatsapp":
            return await wa_calls.dial_outbound(case)
        return await bimpe.place_call(case, actor_id=user["_id"])
    except (bimpe.CallFailed, wa_calls.CallError) as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/calls/{call_id}")
async def call_detail(call_id: str, _: Staff) -> dict:
    call = await db().calls.find_one({"_id": call_id})
    if not call:
        raise HTTPException(404, "no such call")
    return _iso(call)


@app.get("/api/audit/export")
async def export_audit(_: Admin, case_id: str | None = None) -> Response:
    flt = {"case_id": case_id} if case_id else {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "case_id", "actor", "actor_id", "type", "payload"])
    async for e in db().events.find(flt).sort("created_at", 1):
        w.writerow([e["created_at"].isoformat(), e["case_id"], e["actor"], e.get("actor_id") or "", e["type"], json.dumps(e.get("payload", {}), default=str, ensure_ascii=False)])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=ozicare-audit.csv"})


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


@app.get("/api/metrics")
async def metrics(_: Staff) -> dict:
    total = contacted = acked = booked = 0
    first_contact_minutes: list[float] = []
    closed_by_reason: dict[str, int] = {}
    by_status: dict[str, int] = {}
    open_overdue = urgent_open = 0
    async for c in db().cases.find({}, {"status": 1, "created_at": 1, "first_contact_at": 1, "acknowledged_at": 1, "booked_at": 1, "closed_reason": 1, "overdue": 1, "urgency": 1}):
        total += 1
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
        if c.get("first_contact_at"):
            contacted += 1
            first_contact_minutes.append((c["first_contact_at"] - c["created_at"]).total_seconds() / 60)
        if c.get("acknowledged_at"):
            acked += 1
        if c.get("booked_at"):
            booked += 1
        if c.get("closed_reason"):
            closed_by_reason[c["closed_reason"]] = closed_by_reason.get(c["closed_reason"], 0) + 1
        if c["status"] in cases.OPEN:
            open_overdue += bool(c.get("overdue"))
            urgent_open += c["urgency"] == "urgent"

    def pct(n: int, d: int) -> float | None:
        return round(100 * n / d, 1) if d else None

    fc = sorted(first_contact_minutes)
    closed = sum(closed_by_reason.values())
    return {
        "total_cases": total,
        "time_to_first_contact_min": {"median": round(fc[len(fc) // 2], 2) if fc else None, "avg": round(sum(fc) / len(fc), 2) if fc else None},
        "acknowledgement_rate": pct(acked, contacted),
        "booking_rate": pct(booked, contacted),
        "closure_rate": pct(closed, total),
        "closed_by_reason": closed_by_reason,
        "open_overdue": open_overdue,
        "urgent_open": urgent_open,
        "by_status": by_status,
    }


# --------------------------------------------------------------------------
# Lab / EHR ingestion
# --------------------------------------------------------------------------


@app.post("/api/ingest")
async def ingest(body: NewCase, bg: BackgroundTasks, authorization: Annotated[str | None, Header()] = None) -> dict:
    if not settings.app.ingest_api_key:
        raise HTTPException(503, "INGEST_API_KEY is not set")
    if authorization != f"Bearer {settings.app.ingest_api_key}":
        raise HTTPException(401, "bad or missing ingest key")
    if body.external_ref and await db().cases.find_one({"external_ref": body.external_ref, "source": body.source}):
        raise HTTPException(409, "a case for this external_ref already exists")
    try:
        case = await cases.create_case(**body.model_dump(), actor="system")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    bg.add_task(_contact_now, case["_id"])
    return {"id": case["_id"], "status": case["status"]}


# --------------------------------------------------------------------------
# Meta webhook
# --------------------------------------------------------------------------

WEBHOOK_PATHS = ("/webhook/whatsapp", "/whatsapp")


async def verify_webhook(
    mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"), challenge: str = Query("", alias="hub.challenge")
) -> Response:
    if mode == "subscribe" and token and token == settings.whatsapp.verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(403, "verification failed")


async def receive_webhook(request: Request, bg: BackgroundTasks) -> dict:
    """
    Always 200 quickly: a non-200 makes Meta retry the whole batch. Message
    handling runs in the background so a slow LLM reply cannot cause a retry
    (and a duplicate answer).
    """
    body = await request.json()
    logger.info("WEBHOOK RAW: %s", json.dumps(body, ensure_ascii=False)[:1500])

    for msg in whatsapp.parse_messages(body):
        # Meta redelivers; the message id makes handling idempotent.
        if msg.get("id") and await db().messages.find_one({"provider_message_id": msg["id"]}):
            continue
        bg.add_task(_safe_inbound, msg)

    for st in whatsapp.parse_statuses(body):
        await db().messages.update_one({"provider_message_id": st["id"]}, {"$set": {"delivery": st["status"], "delivery_errors": st.get("errors")}})

    for ev in whatsapp.parse_call_events(body):
        bg.add_task(_safe_call_event, ev)
    return {"status": "ok"}


async def _safe_inbound(msg: dict) -> None:
    try:
        await conversation.handle_inbound(msg)
    except Exception:  # noqa: BLE001
        logger.exception("Inbound handling failed for ***%s", msg.get("from", "")[-4:])


async def _safe_call_event(ev: dict) -> None:
    try:
        direction = (ev.get("direction") or "").upper()
        if ev.get("sdp") and direction == "BUSINESS_INITIATED":
            await wa_calls.connect_outbound(call_id=ev["call_id"], sdp=ev["sdp"], sdp_type=ev.get("sdp_type") or "answer")
        elif ev.get("sdp"):
            await wa_calls.accept_inbound(call_id=ev["call_id"], from_number=ev.get("from") or "", sdp=ev["sdp"], sdp_type=ev.get("sdp_type") or "offer")
        elif ev.get("event") in ("terminate", "call_terminated"):
            await db().calls.update_one({"keys": ev["call_id"], "status": "active"}, {"$set": {"status": "ended", "ended_at": now()}})
    except Exception:  # noqa: BLE001
        logger.exception("Call event %s failed", ev.get("event"))


for _p in WEBHOOK_PATHS:
    app.add_api_route(_p, verify_webhook, methods=["GET"], tags=["whatsapp"])
    app.add_api_route(_p, receive_webhook, methods=["POST"], tags=["whatsapp"])


@app.get("/health")
async def health() -> dict:
    try:
        await db().command("ping")
        mongo = "ok"
    except Exception as exc:  # noqa: BLE001
        mongo = f"error: {exc}"[:200]
    return {"ok": mongo == "ok", "mongo": mongo, "whatsapp": settings.whatsapp.configured, "bimpe": settings.bimpe.configured, "livekit": settings.livekit.configured}
