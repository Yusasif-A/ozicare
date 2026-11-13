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
    ("Priya Nair", "en", "abu_dhabi", "Private", {"cervical_cytology": "LSIL"}, "in_care", {"attended_days_ago": 1}, 200),
    ("Yousef Al Ameri", "ar", "al_ain", "Thiqa", {"hba1c": 9.1}, "acknowledged", {}, 18),
    ("Maria Santos", "en", "abu_dhabi", "Daman Basic", {"fasting_glucose": 131}, "contacted", {"attempts": 1}, 5),
    ("Abdulla Al Mansoori", "ar", "al_dhafra", "Thiqa", {"systolic": 158, "diastolic": 96}, "new", {}, 0.2),
    ("Aisha Rahman", "en", "al_ain", "Daman Enhanced", {"birads": "0"}, "contacted", {"attempts": 2}, 30),
    ("Mohammed Al Suwaidi", "ar", "abu_dhabi", "Thiqa", {"fit": "positive"}, "booked", {"appt_days": 3, "referral_status": "accepted"}, 60),
    ("Leila Haddad", "ar", "abu_dhabi", "Private", {"cervical_cytology": "ASC-US"}, "acknowledged", {}, 40),
    ("John Okafor", "en", "al_ain", "Self-pay", {"bmi": 36, "systolic": 144, "diastolic": 91}, "contacted", {"attempts": 1}, 10),
    ("Shamma Al Nuaimi", "ar", "al_dhafra", "Thiqa", {"hba1c": 6.8}, "in_care", {"attended_days_ago": 2}, 240),
    ("Khalid Al Mazrouei", "ar", "al_ain", "Thiqa", {"hba1c": 6.1}, "closed_completed", {"note": "Seen at Al Ain Family Health Centre, lifestyle plan agreed."}, 400),
    ("Ravi Kumar", "en", "abu_dhabi", "Daman Basic", {"systolic": 152, "diastolic": 98}, "closed_completed", {"note": "Repeat BP confirmed, started on care plan at primary care."}, 330),
    ("Mariam Al Blooshi", "ar", "abu_dhabi", "Thiqa", {"birads": 3}, "closed_completed", {"note": "Follow-up imaging done, routine recall in 6 months."}, 600),
    ("Fatma Yilmaz", "en", "al_ain", "Daman Enhanced", {"cervical_cytology": "HSIL"}, "closed_completed", {"note": "Colposcopy done, treated at Al Ain Regional Hospital."}, 700),
    ("Grace Mensah", "en", "abu_dhabi", "Self-pay", {"systolic": 148, "diastolic": 94}, "closed_lost", {"attempts": 3}, 500),
    ("Saeed Al Hammadi", "ar", "al_dhafra", "Daman Basic", {"fit": "positive"}, "closed_declined", {"note": "Declined colonoscopy after explanation; GP informed."}, 450),
]

# What the patient and OziCare said, so a sample's timeline is not empty.
CHATTER = {
    "contacted": [("outbound", "first_contact")],
    "acknowledged": [("outbound", "first_contact"), ("inbound", "1"), ("outbound", "confirm"), ("inbound", "yes")],
    "booked": [("outbound", "first_contact"), ("inbound", "2"), ("outbound", "confirm"), ("inbound", "yes"), ("outbound", "booked")],
    "in_care": [("outbound", "first_contact"), ("inbound", "2"), ("outbound", "confirm"), ("inbound", "yes"), ("outbound", "booked")],
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
    if extra.get("referral_status") or status in ("in_care", "closed_completed"):
        fields["referral"] = {**case["referral"], "status": "accepted", "responder": "Dr. Yusuf Clinician", "responded_at": created + timedelta(hours=2)}
    await cases.update_case(case["_id"], fields)
    await db().cases.update_one({"_id": case["_id"]}, {"$set": {"updated_at": now() - timedelta(minutes=10 * i)}})
    # Backdate the intake events so the timeline reads in order.
    await db().events.update_many({"case_id": case["_id"]}, {"$set": {"created_at": created}})
    await _chatter(case, lang, status, created, fields)
    note = extra.get("note")
    await cases.log_event(case["_id"], "system", "status_changed", {"from": "new", "to": status, "note": note or "demo history"})
    await db().events.update_one({"case_id": case["_id"], "type": "status_changed"}, {"$set": {"created_at": fields.get("closed_at") or fields.get("booked_at") or created + timedelta(minutes=30)}})


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
