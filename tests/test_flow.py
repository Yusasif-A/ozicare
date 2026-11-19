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
        assert "1." in out and "Primary Health Centre" in out  # the referral's facility
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


def test_risk_rules():
    from ozicare import risk

    a = risk.assess({"systolic": 185, "diastolic": 110})
    assert a["urgency"] == "urgent" and a["pathway"] == "hypertension" and a["screening_type"] == "blood_pressure"
    a = risk.assess({"systolic": 150, "diastolic": 92, "hba1c": 7.1})
    assert a["urgency"] == "soon" and a["pathway"] == "diabetes" and len(a["findings"]) == 2
    a = risk.assess({"birads": "4", "bmi": 33})
    assert a["pathway"] == "breast" and a["urgency"] == "urgent"  # cancer pathway first
    assert risk.assess({"cervical_cytology": "HSIL"})["urgency"] == "soon"
    assert risk.assess({"fit": "positive"})["pathway"] == "colorectal"
    assert not risk.assess({"systolic": 118, "diastolic": 76, "hba1c": 5.2, "bmi": 23})["actionable"]


def test_readings_drive_urgency_and_referral():
    async def go():
        # Staff said routine; the rules say urgent. Rules win upward.
        case = await cases.create_case(
            phone="+971500000010", display_name="Mariam Al Mansoori", language="ar", urgency="routine",
            readings={"systolic": 190, "diastolic": 118}, region="al_ain", insurance="Thiqa",
        )
        assert case["urgency"] == "urgent" and case["screening_type"] == "blood_pressure"
        assert case["owner_name"] == "Dr. Yusuf Clinician"
        ref = case["referral"]
        assert ref["service"] == "urgent_bp" and ref["facility_region"] == "al_ain" and ref["network_ok"]
        # A private plan in Al Dhafra for a mammogram: in-network facility is in another region.
        c2 = await cases.create_case(phone="+971500000011", display_name="Sara K", language="en", readings={"birads": 4}, region="al_dhafra", insurance="Private")
        assert c2["referral"]["service"] == "breast_diagnostic" and c2["referral"]["network_ok"]
        with pytest.raises(ValueError):
            await cases.create_case(phone="+971500000012", display_name="Well Person", language="en", readings={"systolic": 115, "diastolic": 70})

    run(go())


def test_referral_decline_and_re_refer():
    async def go():
        from ozicare import referrals

        case = await cases.create_case(phone="+971500000013", display_name="Omar H", language="en", readings={"hba1c": 8.0}, region="abu_dhabi", insurance="Daman Basic")
        clin = await db().staff_users.find_one({"role": "clinician"})
        with pytest.raises(ValueError):
            await referrals.respond(case, False, staff=clin)  # reason required
        case = await referrals.respond(case, False, staff=clin, note="No endocrinology capacity this month")
        assert case["referral"]["status"] == "declined"
        first = case["referral"]["facility_id"]
        case = await referrals.re_refer(case, staff=clin)
        assert case["referral"]["status"] == "sent" and case["referral"]["facility_id"] != first
        assert case["referral"]["previous"][0]["status"] == "declined"
        case = await referrals.consult(case, staff=clin, text="Please prioritise, HbA1c 8.0")
        assert case["referral"]["consult"][0]["text"].startswith("Please")

    run(go())


def test_no_show_rebooks_then_attended_closes_loop():
    async def go():
        phone = "+971500000014"
        case = await cases.create_case(phone=phone, display_name="Khalid R", language="en", readings={"bmi": 34})
        await conversation.contact_patient(case)
        await _inbound(phone, "2")
        await _inbound(phone, "yes")
        out = await _inbound(phone, "1")
        case = await cases.get_case(case["_id"])
        assert case["status"] == "booked" and "/p?t=" in out
        case = await cases.record_attendance(case, False)
        assert case["status"] == "acknowledged" and case["no_show_count"] == 1
        assert cases.public(case)["loss_risk"]["score"] >= 25
        stats = await scheduler.tick()
        assert stats["reminded"] == 1 and "could not make your follow-up" in _texts()[-1]
        await _inbound(phone, "2")
        await _inbound(phone, "2")
        case = await cases.get_case(case["_id"])
        assert case["status"] == "booked"
        case = await cases.record_attendance(case, True)
        assert case["status"] == "in_care" and case["attended_at"]

    run(go())


def test_patient_page_needs_sign_in_then_books():
    async def go():
        from fastapi import HTTPException

        from ozicare import patient_app

        phone = "+971500000016"
        case = await cases.create_case(phone=phone, display_name="Noura S", language="ar", readings={"hba1c": 7.0})
        await conversation.contact_patient(case)
        assert "/p?t=" in _texts()[-1]
        # The link alone shows nothing but a masked phone for the sign-in form.
        info = await patient_app.link_info(case["patient_token"])
        assert info["phone"] == phone and "•••" in info["phone_masked"] and "explain" not in info
        with pytest.raises(HTTPException):
            await patient_app.view(None)
        with pytest.raises(HTTPException):
            await patient_app.login(patient_app.Login(phone=phone, password="anything"))  # no password set yet
        await patient_app.set_password(case["patient_id"], "Noura-pass-1")
        with pytest.raises(HTTPException):
            await patient_app.login(patient_app.Login(phone=phone, password="wrong"))
        res = await patient_app.login(patient_app.Login(phone="00971500000016", password="Noura-pass-1"))
        bearer = f"Bearer {res['token']}"
        # Signing in confirms identity, like YES on WhatsApp.
        assert (await cases.get_case(case["_id"]))["identity_confirmed"]
        v = await patient_app.view(bearer)
        assert v["referral"]["clinic"] and v["slots"]
        assert (await patient_app.view(bearer, "en"))["screening"].startswith("blood sugar")
        v = await patient_app.book(patient_app.Book(slot_iso=v["slots"][0]["iso"]), bearer)
        assert v["appointment"] and v["step"] == "booked"
        assert (await cases.get_case(case["_id"]))["status"] == "booked"
        with pytest.raises(HTTPException):
            await patient_app.view("Bearer not-a-token")
        assert "patient_token" not in cases.public(case) and "/p?t=" in cases.public(case)["patient_link"]

    run(go())


def test_whatsapp_call_follows_post_screening_flow():
    """The LiveKit (WhatsApp call) agent runs the same steps as the phone call."""

    async def go():
        from ozicare import bimpe, voice_agent

        case = await cases.create_case(phone="+971500000017", display_name="Layla H", language="en", readings={"systolic": 168, "diastolic": 102}, region="al_ain", insurance="Thiqa")
        # Same script on both channels.
        for prompt in (voice_agent.INSTRUCTIONS, bimpe.SYSTEM_PROMPT):
            for step in ("confirm_identity", "explain_result", "get_available_slots", "book_slot", "what to bring", "end_call"):
                assert step in prompt
        call = await voice_tools.open_call(case, provider="livekit", direction="inbound", keys=["wa-call-1"])
        assert "Identity not confirmed" in await voice_tools.explain_result(call)
        await voice_tools.confirm_identity(call, True)
        call = await db().calls.find_one({"_id": call["_id"]})
        script = await voice_tools.explain_result(call)
        for part in ("WHAT THE SCREENING FOUND", "REFERRAL", "Al Ain Family Health Centre", "WHY IT MATTERS", "WHAT TO BRING", "WARNING SIGNS", "offer to book"):
            assert part in script
        await voice_tools.get_available_slots(call)
        out = await voice_tools.book_slot(call, 1)
        assert "reminder the day before" in out and "OziCare page" in out
        # Once booked, a second call reminds instead of re-booking.
        call2 = await voice_tools.open_call(await cases.get_case(case["_id"]), provider="livekit", direction="inbound", keys=["wa-call-2"])
        await voice_tools.confirm_identity(call2, True)
        assert "ALREADY BOOKED" in await voice_tools.explain_result(await db().calls.find_one({"_id": call2["_id"]}))

    run(go())


def test_demo_reset_fills_board_and_outreach_messages():
    async def go():
        from ozicare import demo

        res = await demo.reset(phone="+971500000099", name="Mariam Al Mansoori", lang="en")
        assert res["samples"] == len(demo.SAMPLES) and res["live_case"]
        statuses = {c["status"] async for c in db().cases.find({})}
        assert {"escalated", "booked", "follow_up", "closed_completed", "closed_lost", "closed_declined", "new"} <= statuses
        assert await db().messages.count_documents({}) > len(demo.SAMPLES)  # sample timelines are not empty
        await demo.seed_if_empty()  # never adds to a database that has data
        assert await db().cases.count_documents({}) == len(demo.SAMPLES) + len(demo.SCENARIOS)
        # Only the chosen scenario is open on the presenter's phone.
        assert await db().cases.count_documents({"phone": "+971500000099", "status": {"$in": list(cases.OPEN)}}) == 1
        live = await cases.get_case(res["live_case"])
        assert live["status"] == "new" and live["referral"]["facility_name"] and live["next_action_at"] is None
        assert (await scheduler.tick())["contacted"] == 0  # waits for the presenter's click
        n = len(SENT)
        out = await demo.outreach(live, channel="invite", actor_id=None)
        assert out["message"] and out["call"] is None
        assert any(p["type"] == "interactive" and p["interactive"]["type"] == "voice_call" for p in SENT[n:])
        live = await cases.get_case(live["_id"])
        assert live["status"] == "contacted" and live["referral"]["status"] == "accepted"
        # Second demo: diabetes in Arabic, routed to endocrinology, not urgent.
        res = await demo.reset(scenario="diabetes", phone="+971500000099")
        d = await cases.get_case(res["live_case"])
        assert d["language"] == "ar" and d["pathway"] == "diabetes" and d["urgency"] == "soon"
        assert d["referral"]["service"] == "endocrinology" and "المختبر" in d["result_summary"]

    run(go())


def test_demo_autoseed_on_empty_database():
    async def go():
        from ozicare import demo

        settings.app.demo_patient_phone = "+971500000098"
        try:
            await demo.seed_if_empty()
        finally:
            settings.app.demo_patient_phone = ""
        assert await db().cases.count_documents({}) == len(demo.SAMPLES) + len(demo.SCENARIOS)
        live = [c async for c in db().cases.find({"demo_live": True, "status": "new"})]
        assert len(live) == 1 and live[0]["next_action_at"] is None  # ready for Notify, nothing sent
        assert (await scheduler.tick())["contacted"] == 0
        from ozicare import patient_app

        res = await patient_app.login(patient_app.Login(phone="+971500000098", password=settings.app.demo_patient_password))
        assert res["token"]

    run(go())


def test_fhir_bundle_in_and_encounter_closes():
    async def go():
        from ozicare import fhir

        res = await fhir.ingest_bundle(fhir.example_bundle(phone="+971500000015"))
        assert res["actionable"] and res["pathway"] == "hypertension" and res["urgency"] == "soon"
        case = await cases.get_case(res["case_id"])
        assert case["language"] == "ar" and case["region"] == "al_ain" and case["insurance"] == "Thiqa"
        assert case["emirates_id"].startswith("784")
        assert {f["pathway"] for f in case["risk_findings"]} == {"hypertension", "diabetes"}
        sr = fhir.service_request(case)
        assert sr["resourceType"] == "ServiceRequest" and sr["subject"]["identifier"]["value"] == case["emirates_id"]
        slot = cases.next_slots("ar")[0]
        case = await cases.book(case, slot)
        assert fhir.appointment(case)["status"] == "booked"
        out = await fhir.apply_encounter({"resourceType": "Encounter", "status": "finished", "basedOn": [{"reference": f"ServiceRequest/{case['_id']}"}]})
        assert out["status"] == "in_care"
        assert fhir.task(await cases.get_case(case["_id"]))["status"] == "in-progress"

    run(go())
