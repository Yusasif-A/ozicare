"""
Demo data and the one-click outreach, so a demo starts at the interesting part.

    POST /api/demo/reset   (admin) wipes cases, fills the board with sample
                           patients at every step of the loop, and creates one
                           live case for DEMO_PATIENT_PHONE, already risk-
                           assessed and referred, waiting for outreach.
    POST /api/cases/{id}/outreach   one click: WhatsApp message + call.

Sample patients use +97150000xxxx numbers, which no one owns, and nothing is
sent to them: they are written straight to the database, backdated, with the
events a real run would have produced.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from . import cases, referrals
from .config import settings
from .db import db, now

logger = logging.getLogger("ozicare.demo")

# name, lang, region, insurance, readings, status, extra fields, hours ago.
# A believable working week: every pathway, every region, every step of the
# loop, including the ones that go wrong (overdue, no-show, lost, declined).
SAMPLES = [
    ("Fatima Al Hosani", "ar", "abu_dhabi", "Thiqa", {"birads": 4}, "escalated", {"escalation": {"reason": "Urgent result not acknowledged within SLA", "summary": "Breast screening BI-RADS 4. Two WhatsApp messages unanswered. Needs a personal call today.", "by": "system"}}, 3),
    ("Rahul Mehta", "en", "al_ain", "Daman Basic", {"systolic": 186, "diastolic": 112}, "booked", {"appt_days": 1, "referral_status": "accepted"}, 8),
    ("Hessa Al Ketbi", "ar", "abu_dhabi", "Thiqa", {"cervical_cytology": "suspected carcinoma"}, "booked", {"appt_days": 1, "referral_status": "accepted"}, 20),
    ("Ahmed Al Dhaheri", "ar", "al_ain", "Daman Basic", {"systolic": 172, "diastolic": 104}, "contacted", {"attempts": 3, "overdue": True}, 50),
    ("Sara Thomas", "en", "abu_dhabi", "Daman Enhanced", {"hba1c": 7.8, "bmi": 31}, "booked", {"appt_days": 2}, 26),
    ("Omar Khalifa", "ar", "al_dhafra", "Thiqa", {"fit": "positive"}, "acknowledged", {"no_show_count": 1}, 120),
    ("Noura Al Shamsi", "ar", "abu_dhabi", "Thiqa", {"bmi": 41}, "booked", {"appt_days": 4, "referral_status": "accepted"}, 30),
    ("Priya Nair", "en", "abu_dhabi", "Private", {"cervical_cytology": "LSIL"}, "follow_up", {"attended_days_ago": 8, "aftercare": "lab_late"}, 300),
    ("Yousef Al Ameri", "ar", "al_ain", "Thiqa", {"hba1c": 9.1}, "acknowledged", {}, 18),
    ("Maria Santos", "en", "abu_dhabi", "Daman Basic", {"fasting_glucose": 131}, "contacted", {"attempts": 1}, 5),
    ("Abdulla Al Mansoori", "ar", "al_dhafra", "Thiqa", {"systolic": 158, "diastolic": 96}, "new", {}, 0.2),
    ("Aisha Rahman", "en", "al_ain", "Daman Enhanced", {"birads": "0"}, "contacted", {"attempts": 2}, 30),
    ("Mohammed Al Suwaidi", "ar", "abu_dhabi", "Thiqa", {"fit": "positive"}, "booked", {"appt_days": 3, "referral_status": "accepted"}, 60),
    ("Leila Haddad", "ar", "abu_dhabi", "Private", {"cervical_cytology": "ASC-US"}, "acknowledged", {}, 40),
    ("John Okafor", "en", "al_ain", "Self-pay", {"bmi": 36, "systolic": 144, "diastolic": 91}, "contacted", {"attempts": 1}, 10),
    ("Shamma Al Nuaimi", "ar", "al_dhafra", "Thiqa", {"hba1c": 6.8}, "follow_up", {"attended_days_ago": 6, "aftercare": "rerouted"}, 340),
    ("Khalid Al Mazrouei", "ar", "al_ain", "Thiqa", {"hba1c": 6.1}, "closed_completed", {"aftercare": "complete", "note": "Seen at Al Ain Family Health Centre, lifestyle plan agreed."}, 400),
    ("Ravi Kumar", "en", "abu_dhabi", "Daman Basic", {"systolic": 152, "diastolic": 98}, "closed_completed", {"aftercare": "complete", "note": "Repeat BP confirmed, started on care plan at primary care."}, 330),
    ("Mariam Al Blooshi", "ar", "abu_dhabi", "Thiqa", {"birads": 3}, "closed_completed", {"aftercare": "complete", "note": "Follow-up imaging done, routine recall in 6 months."}, 600),
    ("Fatma Yilmaz", "en", "al_ain", "Daman Enhanced", {"cervical_cytology": "HSIL"}, "closed_completed", {"aftercare": "complete", "note": "Colposcopy done, treated at Al Ain Regional Hospital."}, 700),
    ("Grace Mensah", "en", "abu_dhabi", "Self-pay", {"systolic": 148, "diastolic": 94}, "closed_lost", {"attempts": 3}, 500),
    ("Saeed Al Hammadi", "ar", "al_dhafra", "Daman Basic", {"fit": "positive"}, "closed_declined", {"note": "Declined colonoscopy after explanation; GP informed."}, 450),
]

# What the patient and OziCare said, so a sample's timeline is not empty.
CHATTER = {
    "contacted": [("outbound", "first_contact")],
    "acknowledged": [("outbound", "first_contact"), ("inbound", "1"), ("outbound", "confirm"), ("inbound", "yes")],
    "booked": [("outbound", "first_contact"), ("inbound", "2"), ("outbound", "confirm"), ("inbound", "yes"), ("outbound", "booked")],
    "in_care": [("outbound", "first_contact"), ("inbound", "2"), ("outbound", "confirm"), ("inbound", "yes"), ("outbound", "booked")],
    "follow_up": [("outbound", "first_contact"), ("inbound", "2"), ("outbound", "confirm"), ("inbound", "yes"), ("outbound", "booked")],
    "escalated": [("outbound", "first_contact"), ("outbound", "reminder")],
    "closed_completed": [("outbound", "first_contact"), ("inbound", "2"), ("outbound", "booked"), ("outbound", "closed")],
    "closed_lost": [("outbound", "first_contact"), ("outbound", "reminder"), ("outbound", "reminder")],
    "closed_declined": [("outbound", "first_contact"), ("inbound", "4"), ("outbound", "decline_confirm"), ("inbound", "4"), ("outbound", "declined")],
}

# The live case Reset demo creates for the presenter's phone. Both are results
# that come back from a lab days later, after the person has gone home.
SCENARIOS = {
    # Cervical sample read by the lab one to two weeks after screening.
    "cervical": {
        "name": "Mariam Al Mansoori",
        "language": "en",
        "readings": {"cervical_cytology": "HSIL, HPV 16 positive"},
        "location": "Al Ain women's health screening unit",
        "summary": {
            "en": "The laboratory has now read the sample taken at your screening visit about two weeks ago.",
            "ar": "انتهى المختبر الآن من قراءة العينة التي أُخذت في زيارة الفحص قبل نحو أسبوعين.",
        },
    },
    # HbA1c blood test sent to the lab from a community screening. 7.4% is
    # "soon"; keep it under 10 or the case turns urgent and escalates itself.
    "diabetes": {
        "name": "Mariam Al Mansoori",
        "language": "ar",
        "readings": {"hba1c": 7.4},
        "location": "Al Ain community health screening",
        "summary": {
            "en": "Your blood test from the community screening last week has come back from the laboratory.",
            "ar": "وصلت من المختبر نتيجة تحليل الدم الذي أُجري لك في الفحص المجتمعي الأسبوع الماضي.",
        },
    },
}

STAMP = {
    "contacted": ["first_contact_at"],
    "acknowledged": ["first_contact_at", "acknowledged_at"],
    "escalated": ["first_contact_at"],
    "booked": ["first_contact_at", "acknowledged_at", "booked_at"],
    "in_care": ["first_contact_at", "acknowledged_at", "booked_at", "attended_at"],
    "follow_up": ["first_contact_at", "acknowledged_at", "booked_at", "attended_at"],
    "closed_completed": ["first_contact_at", "acknowledged_at", "booked_at", "attended_at", "closed_at"],
    "closed_lost": ["first_contact_at", "closed_at"],
    "closed_declined": ["first_contact_at", "acknowledged_at", "closed_at"],
}


async def _sample(i: int, row: tuple) -> None:
    name, lang, region, insurance, readings, status, extra, hours = row
    case = await cases.create_case(
        phone=f"+97150000{1000 + i}", display_name=name, language=lang, region=region, insurance=insurance,
        readings=readings, source=("phc", "lab", "camp")[i % 3], actor="system",
    )
    created = now() - timedelta(hours=hours)
    fields: dict = {"status": status, "created_at": created, "next_action_at": None, "identity_confirmed": status not in ("new", "contacted", "escalated")}
    if status == "new":
        fields["next_action_at"] = None
    step = max(hours, 1) / 6
    for k, key in enumerate(STAMP.get(status, [])):
        fields[key] = created + timedelta(hours=step * (k + 1) * 0.6, minutes=1)
    if "attended_days_ago" in extra:
        fields["attended_at"] = now() - timedelta(days=extra["attended_days_ago"])
    if "appt_days" in extra:
        slot = cases.next_slots(lang, extra["appt_days"])[-1]
        clinic = referrals.clinic_for(case, lang)
        fields["appointment"] = {"slot_iso": slot["iso"], "label": slot["label"], "clinic": clinic["name"], "address": clinic["address"], "channel": "whatsapp"}
        fields["sla_due_at"] = now() + timedelta(days=extra["appt_days"], hours=12)
    else:
        fields["sla_due_at"] = now() + timedelta(hours=6) if not extra.get("overdue") else now() - timedelta(hours=2)
    for k in ("attempts", "overdue", "no_show_count", "escalation"):
        if k in extra:
            fields[k] = {**extra[k], "at": now() - timedelta(hours=1)} if k == "escalation" else extra[k]
    if status.startswith("closed"):
        fields["closed_reason"] = cases.CLOSE_REASONS[status]
    if extra.get("referral_status") or status in ("in_care", "follow_up", "closed_completed"):
        fields["referral"] = {**case["referral"], "status": "accepted", "responder": "Dr. Yusuf Clinician", "responded_at": created + timedelta(hours=2)}
    if status in ("in_care", "follow_up", "closed_completed"):
        clinic = referrals.clinic_for(case, lang)
        visit = fields.get("attended_at") or created
        fields["appointment"] = {"slot_iso": visit.isoformat(), "label": visit.strftime("%a %d %b, %H:%M"), "clinic": clinic["name"], "address": clinic["address"], "channel": "whatsapp"}
    if extra.get("aftercare"):
        fields.update(_aftercare_fields(case, extra["aftercare"], fields.get("attended_at") or created, fields.get("closed_at")))
    await cases.update_case(case["_id"], fields)
    await db().cases.update_one({"_id": case["_id"]}, {"$set": {"updated_at": now() - timedelta(minutes=10 * i)}})
    # Backdate the intake events so the timeline reads in order.
    await db().events.update_many({"case_id": case["_id"]}, {"$set": {"created_at": created}})
    await _chatter(case, lang, status, created, fields)
    note = extra.get("note")
    await cases.log_event(case["_id"], "system", "status_changed", {"from": "new", "to": status, "note": note or "demo history"})
    await db().events.update_one({"case_id": case["_id"], "type": "status_changed"}, {"$set": {"created_at": fields.get("closed_at") or fields.get("booked_at") or created + timedelta(minutes=30)}})


DEMO_RESULTS = {
    "histology": "CIN2 on biopsy: treatment advised",
    "gyn_treatment": "LLETZ treatment done, margins clear",
    "test_of_cure": "HPV not detected, cytology negative",
    "retinal": "No diabetic eye disease",
    "dietitian": "Nutrition plan agreed",
    "lab_hba1c": "HbA1c 6.3%, in target",
    "pc_review": "Repeat review normal",
}


def _aftercare_fields(case: dict, mode: str, attended, closed=None) -> dict:
    """Care plan, provider steps and check-ins for a sample, written directly (nothing is sent)."""
    from . import aftercare
    from .referrals import choose_facility

    pathway = case.get("pathway") if case.get("pathway") in aftercare.PLANS else "general"
    base = aftercare.PLANS[pathway]
    t0 = attended + timedelta(hours=1)
    legs = [aftercare._new_leg(case, spec, t0) for spec in base["legs"]]
    cp = {
        "outcome": base["outcome"],
        "instructions": [e for e, _ in base["instructions"]],
        "warning_signs": [e for e, _ in base["warning_signs"]],
        "verify_text": base["verify_text"],
        "by": "Dr. Yusuf Clinician",
        "by_id": None,
        "at": t0,
        "pathway": pathway,
    }
    cks = [
        {"id": f"CK-D{case['_id'][-4:]}{d}", "day": d, "due_at": t0 + timedelta(days=d), "status": "scheduled", "channel": None, "answers": None, "summary": "", "done_at": None}
        for d in base["checkins"]
    ]
    out: dict = {"care_plan": cp, "legs": legs, "checkins": cks, "verification": None, "provider_alert": None}
    if mode == "complete":
        end = closed or now()
        for k, leg in enumerate(legs):
            leg.update(
                status="done",
                requested_at=leg["requested_at"] or t0,
                done_at=end - timedelta(hours=2 * (len(legs) - k)),
                due_at=None,
                result=DEMO_RESULTS.get(leg["service"], "Done"),
                normal=True if leg["kind"] == "result" else None,
                by="facility (FHIR)",
            )
        for ck in cks:
            ck.update(status="done", channel="whatsapp", done_at=ck["due_at"], answers={"feeling": "well", "following_plan": True, "warning_signs": "", "notes": ""})
        vleg = next(x for x in legs if x["verifies"])
        out["verification"] = {"at": vleg["done_at"], "source": vleg["label"], "facility": vleg["facility_name"], "result": vleg["result"], "by": "facility (FHIR)"}
        out["signoff"] = {"by": "Dr. Yusuf Clinician", "by_id": None, "role": "clinician", "at": end, "note": "Loop closed with evidence"}
        return out
    cks[0].update(status="done", channel="voice", done_at=cks[0]["due_at"], answers={"feeling": "well, a little tired", "following_plan": True, "warning_signs": "", "notes": ""})
    if mode == "lab_late":
        lab = legs[0]
        lab.update(
            level=3,
            due_at=None,
            actions=[
                {"at": t0 + timedelta(days=5), "level": 1, "text": f"Deadline missed. Chased {lab['facility_name']} automatically"},
                {"at": t0 + timedelta(days=7), "level": 3, "text": "Escalated to the care coordinator"},
            ],
        )
        out["provider_alert"] = {
            "reason": f"{lab['label']} at {lab['facility_name']}: no report after automatic chase. Blocking: {legs[1]['label']}.",
            "at": t0 + timedelta(days=7),
            "leg": lab["id"],
            "service": lab["label"],
            "facility": lab["facility_name"],
        }
        out["overdue"] = True
    if mode == "rerouted":
        eye = legs[0]
        alt, _ok = choose_facility(eye["service"], case.get("region", ""), case.get("insurance", ""), exclude=set(eye["tried"]))
        if alt:
            old = eye["facility_name"]
            eye.update(
                level=2,
                facility_id=alt["id"],
                facility_name=alt["name"]["en"],
                tried=[*eye["tried"], alt["id"]],
                requested_at=t0 + timedelta(days=4),
                due_at=now() + timedelta(days=1),
                actions=[
                    {"at": t0 + timedelta(days=2), "level": 1, "text": f"Deadline missed. Chased {old} automatically"},
                    {"at": t0 + timedelta(days=4), "level": 2, "text": f"No response from {old}. Re-routed to {alt['name']['en']} (in network)"},
                ],
            )
        legs[1].update(status="done", done_at=t0 + timedelta(days=3), due_at=None, result=DEMO_RESULTS["dietitian"], by="Amina Navigator")
    return out


async def _chatter(case: dict, lang: str, status: str, created, fields: dict) -> None:
    from .content import TEXT, explanation, t

    fname = cases.first_name(case["patient_name"])
    texts = {
        "first_contact": t("first_contact", lang, first_name=fname, org=settings.app.org_name),
        "reminder": t("reminder", lang, first_name=fname, org=settings.app.org_name),
        "confirm": t("confirm_identity", lang, first_name=fname),
        "decline_confirm": TEXT["decline_confirm"][lang],
        "declined": TEXT["declined"][lang],
        "closed": t("closed_thanks", lang, first_name=fname),
    }
    appt = fields.get("appointment")
    if appt:
        texts["booked"] = t("booked", lang, slot=appt["label"], clinic=appt["clinic"], address=appt["address"], bring="—")
    else:
        texts["booked"] = explanation(case["screening_type"], lang)
    for k, (direction, key) in enumerate(CHATTER.get(status, [])):
        body = key if direction == "inbound" else texts.get(key, "")
        if key == "yes" and lang == "ar":
            body = "نعم"
        await db().messages.insert_one(
            {
                "_id": f"MS-D{case['_id'][-6:]}{k}",
                "case_id": case["_id"],
                "channel": "whatsapp",
                "direction": direction,
                "body": body,
                "phone": case["phone"],
                "provider_message_id": None,
                "delivery": "read" if direction == "outbound" else None,
                "meta": {"by": "system", "demo": True},
                "created_at": created + timedelta(minutes=2 + 7 * k),
            }
        )


async def seed_if_empty() -> None:
    """
    First start on an empty database: fill the board with the sample week and
    both demo patients, so the dashboard is never blank and the presenter's
    only step is Notify. Real data is never touched. Off with DEMO_AUTOSEED=false.
    """
    if not settings.app.demo_autoseed or await db().cases.count_documents({}) > 0:
        return
    await _populate()


async def _populate() -> list[str]:
    for i, row in enumerate(SAMPLES):
        await _sample(i, row)
    live = []
    for key in SCENARIOS:
        case = await _live_case(key)
        if case:
            live.append(case["_id"])
    logger.info("Demo data: %d sample patients, live cases %s", len(SAMPLES), live or "none (set DEMO_PATIENT_PHONE)")
    return live


async def _live_case(scenario: str, phone: str = "", name: str = "", lang: str = "") -> dict | None:
    """
    A patient on the presenter's phone, already entered, risk-assessed and
    referred, waiting for Notify. One phone holds one open case at a time, so
    with a single DEMO_PATIENT_PHONE the second scenario goes on hold (closed)
    until the presenter switches to it with Start demo.
    """
    phone = phone or settings.app.demo_patient_phone
    if not phone:
        return None
    sc = SCENARIOS[scenario]
    language = lang or sc["language"]
    await db().cases.update_many(
        {"phone": cases.normalize_phone(phone), "status": {"$in": list(cases.OPEN)}},
        {"$set": {"status": "closed_transferred", "closed_reason": "transferred", "closed_at": now(), "next_action_at": None}},
    )
    case = await cases.create_case(
        phone=phone,
        display_name=name or sc["name"],
        language=language,
        emirates_id="784-1985-1234567-1",
        region="al_ain",
        insurance="Thiqa",
        readings=sc["readings"],
        location=sc["location"],
        result_summary=sc["summary"][language],
        source="lab",
        actor="system",
    )
    # Waits for the presenter's click instead of messaging on its own. The
    # referral is already accepted, so the call can say the clinic expects them.
    ref = {**case["referral"], "status": "accepted", "responder": "Dr. Yusuf Clinician", "responded_at": now()}
    await cases.update_case(case["_id"], {"next_action_at": None, "next_action": "outreach", "demo_live": True, "demo_scenario": scenario, "referral": ref})
    await cases.log_event(case["_id"], "staff", "referral_accepted", {"facility": ref["facility_name"], "by": ref["responder"], "note": ""})
    # The presenter signs in to the patient page with DEMO_PATIENT_PASSWORD.
    from .patient_app import set_password

    if settings.app.demo_patient_password:
        await set_password(case["patient_id"], settings.app.demo_patient_password)
    return case


async def reset(*, scenario: str = "cervical", phone: str = "", name: str = "", lang: str = "") -> dict:
    """Wipe cases and rebuild the demo board, with `scenario` as the open live case."""
    for coll in ("cases", "messages", "events", "calls", "patients"):
        await db()[coll].delete_many({})
    for i, row in enumerate(SAMPLES):
        await _sample(i, row)
    other = [k for k in SCENARIOS if k != scenario]
    for k in other:
        await _live_case(k, phone)
    live = await _live_case(scenario, phone, name, lang)
    logger.info("Demo reset (%s): live case %s", scenario, live["_id"] if live else None)
    return {"samples": len(SAMPLES), "live_case": live["_id"] if live else None, "scenario": scenario}


async def outreach(case: dict, *, channel: str, actor_id: str | None) -> dict:
    """
    One click: WhatsApp first (the message the patient can re-read, with the
    call button and their page link), then the call on the chosen channel.
    """
    from . import bimpe, conversation, wa_calls

    out: dict = {"message": False, "call": None, "call_error": None}
    if case["status"] == "follow_up":
        # After the visit, Notify is the recovery check-in.
        from . import aftercare

        await aftercare.send_checkin(case)
        await cases.log_event(case["_id"], "staff", "outreach", {"channel": "checkin"}, actor_id)
        return {**out, "message": True}
    out["message"] = await conversation.contact_patient(case, reminder=case["status"] != "new")
    case = await cases.get_case(case["_id"])
    await cases.log_event(case["_id"], "staff", "outreach", {"channel": channel}, actor_id)
    if channel in ("whatsapp", "invite"):
        # The tap-to-call button always works (patient-initiated), including
        # where Meta blocks business-initiated calls, e.g. +234 and +1.
        from .content import t

        lang = case["language"]
        await conversation.say(case, t("call_me", lang), call_button=t("call_button", lang), meta={"kind": "call_button"})
    if channel == "invite":
        # Notify only: the patient calls in when ready.
        return out
    try:
        if channel == "whatsapp":
            out["call"] = await wa_calls.dial_outbound(case)
        elif channel == "phone":
            out["call"] = await bimpe.place_call(case, actor_id=actor_id)
    except (bimpe.CallFailed, wa_calls.CallError) as exc:
        out["call_error"] = str(exc)
        if channel == "whatsapp":
            out["call_error"] += " | The patient can tap 'Talk to us' in WhatsApp: that call runs the same script."
        await cases.log_event(case["_id"], "system", "call_failed", {"channel": channel, "error": str(exc)[:300]})
    return out


async def advance(case: dict, step: str) -> dict:
    """
    Demo only: skip days ahead for the live case.
      delay   the first provider step still waiting on a provider misses its
              deadline, and the monitor runs (one escalation level per click)
      result  the follow-up test result arrives from the lab over FHIR
    """
    from . import aftercare, fhir

    legs = case.get("legs") or []
    if not legs:
        raise ValueError("Record the care plan first: provider steps come from it")
    if step == "delay":
        cand = [x for x in legs if x["status"] in ("requested", "accepted") and x["kind"] != "result" and x["level"] < 3]
        if not cand:
            raise ValueError("No provider step is waiting on a provider right now")
        leg = cand[0]
        days = leg["days"] if leg["kind"] == "report" and leg["level"] == 0 else aftercare.CHASE_DAYS
        shift = timedelta(days=days, minutes=1)
        new = [dict(x) for x in legs]
        for x in new:
            if x["id"] == leg["id"]:
                x["due_at"] = now() - timedelta(minutes=1)
                x["requested_at"] = (x.get("requested_at") or now()) - shift
                x["actions"] = [{**a, "at": a["at"] - shift} for a in x["actions"]]
        await cases.update_case(case["_id"], {"legs": new})
        stats = await aftercare.monitor(case["_id"])
        return {"step": step, "service": leg["label"], "facility": leg["facility_name"], **stats}
    if step == "result":
        leg = next((x for x in legs if x["verifies"]), None)
        if leg is None:
            raise ValueError("This plan has no follow-up result step")
        if leg["status"] == "waiting":
            before = next((x["label"] for x in legs if x["key"] == leg.get("after")), "the earlier step")
            raise ValueError(f"Finish {before} first")
        if leg["status"] == "done":
            raise ValueError("The result is already in")
        obs = {
            "resourceType": "Observation",
            "status": "final",
            "basedOn": [{"reference": f"ServiceRequest/{leg['id']}"}],
            "code": {"text": leg["label"]},
            "valueString": DEMO_RESULTS.get(leg["service"], "Normal"),
            "interpretation": [{"coding": [{"code": "N"}]}],
        }
        return {**await fhir.apply_followup_result(obs), "step": step}
    raise ValueError("step must be delay or result")
