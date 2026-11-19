"""
After the visit: care plan, provider delays escalating on their own, check-ins,
verified recovery, and closing only with the evidence on file.
"""

from __future__ import annotations

import pytest

from ozicare import aftercare, cases, demo, fhir, scheduler, voice_tools
from ozicare.db import db

from .test_flow import SENT, _inbound, _texts, fresh, run  # noqa: F401  (shared fixtures and capture)


async def _staff(role: str) -> dict:
    return await db().staff_users.find_one({"role": role})


async def _attended_cervical(phone: str) -> dict:
    case = await cases.create_case(phone=phone, display_name="Mariam Test", language="en", readings={"cervical_cytology": "HSIL, HPV 16 positive"}, region="al_ain", insurance="Thiqa")
    case = await cases.update_case(case["_id"], {"referral": {**case["referral"], "status": "accepted", "responder": "Dr", "responded_at": case["created_at"]}, "identity_confirmed": True})
    case = await cases.transition(case["_id"], "acknowledged", actor="patient")
    case = await cases.book(case, cases.next_slots("en")[0])
    return await cases.record_attendance(case, True)


def test_full_loop_closes_only_with_evidence():
    async def go():
        phone = "+971500000031"
        clin = await _staff("clinician")
        case = await _attended_cervical(phone)

        # Closing before the evidence is in is refused.
        with pytest.raises(cases.TransitionError, match="Cannot close"):
            await aftercare.sign_off(case, staff=clin, note="done")

        # Care plan: follow_up, three providers, the plan goes to the patient.
        case = await aftercare.save_plan(case, {}, staff=clin)
        assert case["status"] == "follow_up"
        assert [x["service"] for x in case["legs"]] == ["histology", "gyn_treatment", "test_of_cure"]
        assert [x["status"] for x in case["legs"]] == ["requested", "waiting", "waiting"]
        assert case["legs"][0]["facility_name"] == "Al Ain Pathology Laboratory"
        assert "here is your care plan" in _texts()[-1] and "Heavy bleeding" in _texts()[-1]

        # Lab late: chase, then (a lab cannot be swapped) the coordinator.
        r = await demo.advance(case, "delay")
        assert r["chased"] == 1
        case = await cases.get_case(case["_id"])
        assert case["legs"][0]["level"] == 1
        r = await demo.advance(case, "delay")
        case = await cases.get_case(case["_id"])
        assert r["escalated"] == 1 and case["legs"][0]["level"] == 3
        assert "Blocking: Gynaecology treatment clinic" in case["provider_alert"]["reason"]

        # Report in: the alert clears and the treatment clinic is requested.
        nav = await _staff("navigator")
        case = await aftercare.update_leg(case, case["legs"][0]["id"], action="done", staff=nav, result="CIN2")
        assert case["provider_alert"] is None and case["legs"][1]["status"] == "requested"

        # Treatment clinic silent: chase, then re-route in network, patient told.
        await demo.advance(case, "delay")
        r = await demo.advance(await cases.get_case(case["_id"]), "delay")
        case = await cases.get_case(case["_id"])
        assert r["rerouted"] == 1 and case["legs"][1]["level"] == 2
        assert case["legs"][1]["facility_name"] == "Abu Dhabi Specialist Hospital"
        assert "we have moved your Gynaecology treatment clinic" in _texts()[-1]
        case = await aftercare.update_leg(case, case["legs"][1]["id"], action="done", staff=nav, result="LLETZ done")

        # Check-in on WhatsApp: a concern goes to a clinician.
        await aftercare.send_checkin(case)
        assert any("check-in after your visit" in t for t in _texts()[-2:])
        await _inbound(phone, "", button_id="ck_ok")
        case = await cases.get_case(case["_id"])
        assert case["checkins"][0]["status"] == "done" and case["checkins"][0]["answers"]["feeling"] == "well"

        # Still not closable: no verified result.
        assert "Recovery verified by a result" in aftercare.evidence(case)["missing"]

        # The test of cure arrives over FHIR: recovery verified.
        r = await demo.advance(case, "result")
        assert r["normal"] and r["verified"]
        case = await cases.get_case(case["_id"])
        assert "reassuring" in _texts()[-1]
        ev = aftercare.evidence(case)
        assert ev["ready_to_close"] and not ev["complete"]

        case = await aftercare.sign_off(case, staff=clin, note="Treated, test of cure negative")
        assert case["status"] == "closed_completed"
        ev = aftercare.evidence(case)
        assert ev["complete"]
        bundle = fhir.evidence_bundle(case)
        kinds = {e["resource"]["resourceType"] for e in bundle["entry"]}
        assert {"ServiceRequest", "Appointment", "Encounter", "CarePlan", "Observation", "DiagnosticReport", "Communication", "Task", "Provenance"} <= kinds
        assert bundle["meta"]["tag"][0]["code"] == "complete"

    run(go())


def test_checkin_concern_escalates_and_call_tools():
    async def go():
        phone = "+971500000032"
        clin = await _staff("clinician")
        case = await aftercare.save_plan(await _attended_cervical(phone), {}, staff=clin)
        await aftercare.send_checkin(case)
        await _inbound(phone, "", button_id="ck_concern")
        assert "what is worrying you" in _texts()[-1]
        await _inbound(phone, "the bleeding is heavier today")
        case = await cases.get_case(case["_id"])
        assert case["status"] == "escalated" and case["checkins"][0]["concern"]

        # The call: care plan behind the identity gate, then the check-in.
        case = await cases.transition(case["_id"], "follow_up", actor="staff")
        call = await voice_tools.open_call(case, provider="livekit", direction="inbound", keys=["ck-call"])
        assert "Identity not confirmed" in await voice_tools.get_care_plan(call)
        await voice_tools.confirm_identity(call, True)
        call = await db().calls.find_one({"_id": call["_id"]})
        plan = await voice_tools.get_care_plan(call)
        assert "WHAT WAS DONE AT THE VISIT" in plan and "Pathology lab" in plan
        out = await voice_tools.record_checkin(call, "fine", True, "", "")
        assert out.startswith("Recorded")
        case = await cases.get_case(case["_id"])
        assert case["status"] == "follow_up" and sum(c["status"] == "done" for c in case["checkins"]) == 2

    run(go())


def test_samples_fill_the_provider_monitor():
    async def go():
        await demo.reset(phone="+971500000099")
        priya = await db().cases.find_one({"patient_name": "Priya Nair"})
        assert priya["status"] == "follow_up" and priya["legs"][0]["level"] == 3 and priya["provider_alert"]
        shamma = await db().cases.find_one({"patient_name": "Shamma Al Nuaimi"})
        assert shamma["legs"][0]["level"] == 2
        done = await db().cases.find_one({"patient_name": "Ravi Kumar"})
        assert aftercare.evidence(done)["complete"]
        # Nothing is overdue right after a reset, so the scheduler leaves them.
        stats = await scheduler.tick()
        assert stats["providers"]["escalated"] == 0

    run(go())
