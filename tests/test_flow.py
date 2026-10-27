"""
End-to-end loop against a throwaway Mongo database, WhatsApp captured not sent.

    .venv/Scripts/python -m pytest tests -q

Uses the real Gemma endpoint for the one free-text step, so it needs network.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from ozicare import cases, conversation, guard, scheduler, voice_tools, whatsapp
from ozicare.config import settings
from ozicare.db import db, now

settings.mongo.db = "ozicare_test"
settings.app.escalation_phone = ""
settings.whatsapp.template_en = settings.whatsapp.template_ar = ""

SENT: list[dict] = []


async def _capture(payload: dict):
    SENT.append(payload)
    return 200, {"messages": [{"id": f"wamid.test{len(SENT)}"}]}


whatsapp._post = _capture  # never reach Meta from a test


def _texts() -> list[str]:
    out = []
    for p in SENT:
        if p["type"] == "text":
            out.append(p["text"]["body"])
        elif p["type"] == "interactive":
            out.append(p["interactive"]["body"]["text"])
    return out


async def _reset() -> None:
    from ozicare import auth
    from ozicare.db import ensure_indexes

    for name in ("patients", "cases", "messages", "events", "calls", "staff_users"):
        await db()[name].delete_many({})
    await ensure_indexes()
    await auth.seed_staff()
    SENT.clear()


async def _inbound(phone: str, text: str, button_id: str | None = None) -> str:
    n = len(SENT)
    await conversation.handle_inbound({"from": phone, "id": f"in-{now().timestamp()}", "type": "text", "text": text, "button_id": button_id})
    return "\n---\n".join(_texts()[n:])


def run(coro):
    """Each asyncio.run is a new loop; the Mongo client is bound to its loop."""
    from ozicare import db as dbm

    async def wrapped():
        dbm._client = None
        try:
            return await coro
        finally:
            await dbm.close()

    return asyncio.run(wrapped())


@pytest.fixture(autouse=True)
def fresh():
    run(_reset())
    yield


def test_guard():
    assert guard.violations("You have diabetes and need care.")
    assert guard.violations("Take 500 mg of metformin daily.")
    assert guard.violations("There is no need to see a doctor.")
    assert guard.violations("لديك سكري")
    assert guard.violations("تناول الدواء مرتين")
    assert not guard.violations("A screening result is not a diagnosis. A clinician will review it with you.")
    assert guard.is_emergency("I have chest pain since morning")
    assert guard.is_emergency("عندي ألم في الصدر")
    assert not guard.is_emergency("when is the clinic open")
    assert guard.strip_channel_tokens("<|channel>thought blah<channel|>Hello there") == "Hello there"


def test_happy_path_english():
    async def go():
        phone = "+2348000000001"
        case = await cases.create_case(phone=phone, display_name="Grace Okafor", language="en", screening_type="general_abnormal", urgency="soon", result_summary="")
        assert case["owner_name"] == "Amina Navigator"  # non-urgent -> navigator
        assert await conversation.contact_patient(case)
        case = await cases.get_case(case["_id"])
        assert case["status"] == "contacted" and case["first_contact_at"]
        assert "Hello Grace" in _texts()[-1]

        out = await _inbound(phone, "1")
        assert "confirm you are Grace" in out  # nothing shared before identity
        assert "outside the expected range" not in out

        out = await _inbound(phone, "yes")
        assert "outside the expected range" in out and "not a diagnosis" in out
        assert (await cases.get_case(case["_id"]))["status"] == "acknowledged"

        out = await _inbound(phone, "2")
        assert "1." in out and "Riverside" in out
        out = await _inbound(phone, "", button_id="slot_1")
        c = await cases.get_case(case["_id"])
        assert c["status"] == "booked" and c["appointment"]["label"] in out

        await cases.transition(c["_id"], "in_care", actor="staff", note="attended")
        c = await cases.transition(c["_id"], "closed_completed", actor="staff", note="seen by clinician")
        assert c["closed_reason"] == "completed"
        types = [e["type"] async for e in db().events.find({"case_id": c["_id"]})]
        assert {"created", "contacted", "identity_confirmed", "booked", "status_changed"} <= set(types)

    run(go())


def test_arabic_switch_and_decline():
    async def go():
        phone = "+966500000002"
        case = await cases.create_case(phone=phone, display_name="Fatima Al-Harbi", language="en", screening_type="blood_pressure", urgency="routine")
        await conversation.contact_patient(case)
        out = await _inbound(phone, "عربي")
        assert "سأكمل باللغة العربية" in out
        out = await _inbound(phone, "١")
        assert "حفاظاً على خصوصيتك" in out
        out = await _inbound(phone, "نعم")
        assert "ضغط الدم" in out
        out = await _inbound(phone, "٤")
        assert "نحترم قرارك" in out
        out = await _inbound(phone, "4")
        assert (await cases.get_case(case["_id"]))["status"] == "closed_declined"

    run(go())


def test_emergency_escalates_to_clinician_and_pauses_ai():
    async def go():
        phone = "+2348000000003"
        case = await cases.create_case(phone=phone, display_name="Musa Bello", language="en", screening_type="blood_pressure", urgency="soon")
        await conversation.contact_patient(case)
        out = await _inbound(phone, "I have chest pain and feel dizzy")
        assert "emergency" in out.lower()
        c = await cases.get_case(case["_id"])
        assert c["status"] == "escalated" and c["ai_paused"]
        assert c["owner_name"] == "Dr. Yusuf Clinician"
        assert c["escalation"]["summary"]
        out = await _inbound(phone, "hello?")
        assert out == ""  # staff has the conversation now

    run(go())


def test_free_text_goes_to_llm_and_is_guarded():
    async def go():
        phone = "+2348000000004"
        case = await cases.create_case(phone=phone, display_name="Ada Eze", language="en", screening_type="diabetes", urgency="routine")
        await conversation.contact_patient(case)
        await _inbound(phone, "1")
        await _inbound(phone, "yes")
        out = await _inbound(phone, "Do I definitely have diabetes? What medicine should I take?")
        assert out
        assert not guard.violations(out)
        last = await db().messages.find_one({"case_id": case["_id"], "direction": "outbound"}, sort=[("created_at", -1)])
        assert last["meta"]["kind"] in ("ai_answer", "fallback")

    run(go())


def test_scheduler_urgent_escalates_routine_goes_lost():
    async def go():
        urgent = await cases.create_case(phone="+2348000000005", display_name="Urgent Patient", language="en", screening_type="cervical", urgency="urgent")
        assert urgent["owner_name"] == "Dr. Yusuf Clinician"
        routine = await cases.create_case(phone="+2348000000006", display_name="Quiet Patient", language="en", screening_type="diabetes", urgency="routine")
        stats = await scheduler.tick()
        assert stats["contacted"] == 2
        past = now() - timedelta(minutes=1)
        await db().cases.update_many({}, {"$set": {"next_action_at": past, "sla_due_at": past}})
        await db().cases.update_one({"_id": routine["_id"]}, {"$set": {"attempts": settings.sla.max_attempts}})
        stats = await scheduler.tick()
        assert stats["overdue"] == 2
        assert (await cases.get_case(urgent["_id"]))["status"] == "escalated"
        assert (await cases.get_case(routine["_id"]))["status"] == "closed_lost"

    run(go())


def test_illegal_transition_refused():
    async def go():
        c = await cases.create_case(phone="+2348000000007", display_name="X Y", language="en", screening_type="diabetes", urgency="routine")
        with pytest.raises(cases.TransitionError):
            await cases.transition(c["_id"], "in_care", actor="staff")

    run(go())


def test_voice_tools_gate_on_identity_then_book():
    async def go():
        case = await cases.create_case(phone="+2348000000008", display_name="Bola Ade", language="en", screening_type="diabetes", urgency="soon")
        call = await voice_tools.open_call(case, provider="bimpe", direction="outbound", keys=["bimpe-xyz"])
        brief = await voice_tools.get_case_briefing(call)
        assert brief["first_name"] == "Bola" and "Say nothing about the screening" in brief["instruction"]
        assert "Identity not confirmed" in await voice_tools.explain_result(call)
        await voice_tools.confirm_identity(call, True)
        call = await db().calls.find_one({"_id": call["_id"]})
        assert "blood sugar" in await voice_tools.explain_result(call)
        await voice_tools.get_available_slots(call)
        out = await voice_tools.book_slot(call, 2)
        assert "Booked" in out
        assert (await cases.get_case(case["_id"]))["status"] == "booked"
        # Bimpe never fills session_id: resolution must still find this call.
        resolved = await voice_tools.resolve_call("{{session_id}}")
        assert resolved["_id"] == call["_id"]

    run(go())
