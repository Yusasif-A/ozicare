"""
After the visit: the care plan, the providers it depends on, recovery
check-ins, and the evidence that closes the loop.

    care plan     The clinician records the outcome and the plan after the
                  first visit (in_care -> follow_up). The navigator sends it to
                  the patient in their language and schedules check-ins.
    providers     Every other service the plan depends on is a referral "leg"
                  to its own provider: a lab report, a treatment clinic, a
                  repeat test. Legs can wait on each other (treatment waits for
                  the histology report).
    monitor       Each leg has a deadline. When a provider misses it, OziCare
                  escalates one level per missed deadline, on its own:
                    1 chase the provider
                    2 re-route to the next in-network provider (visits only;
                      a lab already holding the sample cannot be swapped) and
                      tell the patient
                    3 hand it to the care coordinator with the reason
    check-ins     Scheduled WhatsApp check-ins (or a call): feeling well,
                  following the plan, any warning signs. A concern goes to a
                  clinician.
    verification  Recovery counts only when a result or a clinician confirms
                  it: the leg marked `verifies` comes back with a normal result.
    evidence      closed_completed is refused until the evidence is on file;
                  the clinician's sign-off is the last item.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from . import cases, referrals
from .db import db, new_id, now

logger = logging.getLogger("ozicare.aftercare")

# Days a provider has to act once a leg is requested, and after each chase.
CHASE_DAYS = 2

# What the clinician starts from: a sensible plan per pathway, edited on the
# form. Text is English and Arabic so the patient message needs no translation.
PLANS: dict[str, dict] = {
    "cervical": {
        "outcome": "Colposcopy done. Changes seen on the cervix; a small biopsy was taken and sent to the lab.",
        "instructions": [
            ("Light spotting for a few days is normal. Use pads, not tampons, for 5 days.", "النزف الخفيف لبضعة أيام أمر طبيعي. استخدمي الفوط الصحية وليس السدادات لمدة ٥ أيام."),
            ("Avoid sex and swimming for 5 days while the biopsy site heals.", "تجنبي العلاقة الزوجية والسباحة لمدة ٥ أيام حتى يلتئم موضع الخزعة."),
            ("We will message you when the biopsy result is back, about 5 days from now.", "سنراسلك عند صدور نتيجة الخزعة، بعد نحو ٥ أيام."),
        ],
        "warning_signs": [
            ("Heavy bleeding (soaking a pad an hour)", "نزف شديد (تبلل فوطة كل ساعة)"),
            ("Fever or chills", "حمى أو قشعريرة"),
            ("Bad-smelling discharge or strong pain", "إفرازات كريهة الرائحة أو ألم شديد"),
        ],
        "legs": [
            {"key": "histology", "service": "histology", "kind": "report", "days": 5},
            {"key": "treatment", "service": "gyn_treatment", "kind": "visit", "days": 14, "after": "histology"},
            {"key": "toc", "service": "test_of_cure", "kind": "result", "days": 180, "after": "treatment", "verifies": True},
        ],
        "checkins": [2, 7],
        "verify_text": "HPV test of cure negative and cytology normal",
    },
    "diabetes": {
        "outcome": "Seen in the diabetes clinic. HbA1c confirmed raised; lifestyle plan and treatment started by the clinician.",
        "instructions": [
            ("Take the treatment exactly as your clinician prescribed.", "التزم بالعلاج كما وصفه لك الطبيب تماماً."),
            ("Walk 30 minutes a day, 5 days a week, and cut sugary drinks.", "امشِ ٣٠ دقيقة يومياً، ٥ أيام في الأسبوع، وقلل المشروبات السكرية."),
            ("Your eye check and dietitian visit are being booked for you.", "نقوم بحجز فحص العين وموعد أخصائي التغذية لك."),
        ],
        "warning_signs": [
            ("Very thirsty, passing a lot of urine, or very tired", "عطش شديد أو كثرة التبول أو تعب شديد"),
            ("Feeling shaky, sweaty or confused", "رجفة أو تعرق أو تشوش"),
            ("Blurred vision", "تشوش الرؤية"),
        ],
        "legs": [
            {"key": "retinal", "service": "retinal", "kind": "visit", "days": 14},
            {"key": "dietitian", "service": "dietitian", "kind": "visit", "days": 14},
            {"key": "hba1c", "service": "lab_hba1c", "kind": "result", "days": 90, "verifies": True},
        ],
        "checkins": [3, 14],
        "verify_text": "Repeat HbA1c back in target range",
    },
}
PLANS["general"] = {
    "outcome": "Seen in clinic. Follow-up plan agreed with the patient.",
    "instructions": [("Follow the plan your clinician gave you.", "اتبع الخطة التي أعطاك إياها الطبيب.")],
    "warning_signs": [("Feeling much worse", "الشعور بتدهور كبير")],
    "legs": [{"key": "review", "service": "pc_review", "kind": "result", "days": 30, "verifies": True}],
    "checkins": [7],
    "verify_text": "Repeat review normal",
}

LEG_KIND = {"report": "Report", "visit": "Visit", "result": "Follow-up result"}


def template(case: dict) -> dict:
    """The starting plan for the clinician's form."""
    p = PLANS.get(case.get("pathway") or "", PLANS["general"])
    return {
        "outcome": p["outcome"],
        "instructions": [en for en, _ in p["instructions"]],
        "warning_signs": [en for en, _ in p["warning_signs"]],
        "legs": [{**leg, "label": referrals.SERVICES[leg["service"]][0]} for leg in p["legs"]],
        "checkins": p["checkins"],
        "verify_text": p["verify_text"],
    }


def _ar_for(pathway: str, field: str, en: str) -> str:
    """The Arabic for a template line; an edited line goes as written."""
    for e, a in PLANS.get(pathway, PLANS["general"])[field]:
        if e == en:
            return a
    return en


# --------------------------------------------------------------------------
# Care plan
# --------------------------------------------------------------------------


def _new_leg(case: dict, spec: dict, start) -> dict:
    facility, network_ok = referrals.choose_facility(spec["service"], case.get("region", ""), case.get("insurance", ""))
    waiting = bool(spec.get("after"))
    return {
        "id": new_id("LG"),
        # The provider page link: the facility updates this one step, nothing else.
        "token": secrets.token_urlsafe(12),
        "key": spec["key"],
        "service": spec["service"],
        "label": referrals.SERVICES[spec["service"]][0],
        "kind": spec["kind"],
        "days": spec["days"],
        "after": spec.get("after"),
        "verifies": bool(spec.get("verifies")),
        "facility_id": facility["id"] if facility else None,
        "facility_name": facility["name"]["en"] if facility else "No facility found",
        "network_ok": network_ok,
        "status": "waiting" if waiting else "requested",
        "requested_at": None if waiting else start,
        "due_at": None if waiting else start + timedelta(days=spec["days"] if spec["kind"] != "visit" else CHASE_DAYS),
        "level": 0,
        "tried": [facility["id"]] if facility else [],
        "actions": [],
        "done_at": None,
        "result": "",
        "normal": None,
    }


async def save_plan(case: dict, plan: dict, *, staff: dict) -> dict:
    """Clinician records the outcome and plan: in_care -> follow_up."""
    if case["status"] not in ("in_care", "follow_up"):
        raise cases.TransitionError("a care plan is recorded after the patient attends")
    ts = now()
    pathway = case.get("pathway") or "general"
    base = PLANS.get(pathway, PLANS["general"])
    keys = set(plan.get("legs") or [leg["key"] for leg in base["legs"]])
    legs = [_new_leg(case, spec, ts) for spec in base["legs"] if spec["key"] in keys]
    # A leg waiting on one that was left out starts now.
    present = {leg["key"] for leg in legs}
    for leg in legs:
        if leg["after"] and leg["after"] not in present:
            leg.update(status="requested", requested_at=ts, due_at=ts + timedelta(days=leg["days"] if leg["kind"] != "visit" else CHASE_DAYS), after=None)
    checkins = [
        {"id": new_id("CK"), "day": d, "due_at": ts + timedelta(days=d), "status": "scheduled", "channel": None, "answers": None, "summary": "", "done_at": None}
        for d in sorted(set(plan.get("checkins") or base["checkins"]))
    ]
    care_plan = {
        "outcome": (plan.get("outcome") or base["outcome"]).strip(),
        "instructions": [s.strip() for s in (plan.get("instructions") or [e for e, _ in base["instructions"]]) if s.strip()],
        "warning_signs": [s.strip() for s in (plan.get("warning_signs") or [e for e, _ in base["warning_signs"]]) if s.strip()],
        "verify_text": base["verify_text"],
        "by": staff["name"],
        "by_id": staff["_id"],
        "at": ts,
        "pathway": pathway,
    }
    case = await cases.transition(
        case["_id"],
        "follow_up",
        actor="staff",
        actor_id=staff["_id"],
        note="care plan recorded",
        extra={"care_plan": care_plan, "legs": legs, "checkins": checkins, "verification": None, "provider_alert": None, "sla_due_at": None, "next_action": "recovery", "next_action_at": None},
    )
    await cases.log_event(case["_id"], "staff", "care_plan", {"by": staff["name"], "outcome": care_plan["outcome"], "providers": [f"{leg['label']} ({leg['facility_name']})" for leg in legs]}, staff["_id"])
    for leg in legs:
        if leg["status"] == "requested":
            await cases.log_event(case["_id"], "system", "provider_requested", {"service": leg["label"], "facility": leg["facility_name"], "due": leg["due_at"].isoformat()})
    from . import conversation

    await conversation.say(case, plan_text(case), meta={"kind": "care_plan"})
    return case


def plan_text(case: dict) -> str:
    lang = case.get("language", "en")
    cp = case["care_plan"]
    first = cases.first_name(case["patient_name"])
    pw = cp.get("pathway", "general")
    ins = [_ar_for(pw, "instructions", s) if lang == "ar" else s for s in cp["instructions"]]
    warn = [_ar_for(pw, "warning_signs", s) if lang == "ar" else s for s in cp["warning_signs"]]
    nexts = [f"{referrals.SERVICES[leg['service']][1 if lang == 'ar' else 0]}" for leg in case.get("legs", [])]
    if lang == "ar":
        return (
            f"{first}، هذه خطة رعايتك بعد زيارتك:\n\n"
            + "\n".join(f"• {s}" for s in ins)
            + "\n\nالخطوات التالية التي ننسقها لك:\n"
            + "\n".join(f"• {s}" for s in nexts)
            + "\n\nاطلبي المساعدة فوراً إذا ظهر:\n"
            + "\n".join(f"• {s}" for s in warn)
            + "\n\nسنطمئن عليك خلال الأيام القادمة."
        )
    return (
        f"{first}, here is your care plan after your visit:\n\n"
        + "\n".join(f"• {s}" for s in ins)
        + "\n\nNext steps we are arranging for you:\n"
        + "\n".join(f"• {s}" for s in nexts)
        + "\n\nGet help straight away if you have:\n"
        + "\n".join(f"• {s}" for s in warn)
        + "\n\nWe will check in on you over the next few days."
    )


# --------------------------------------------------------------------------
# Providers: legs and the delay monitor
# --------------------------------------------------------------------------


def _leg(case: dict, leg_id: str) -> dict:
    for leg in case.get("legs") or []:
        if leg["id"] == leg_id:
            return leg
    raise ValueError("no such provider step")


async def _save_legs(case: dict, legs: list[dict], extra: dict | None = None) -> dict:
    return await cases.update_case(case["_id"], {"legs": legs, **(extra or {})})


async def update_leg(case: dict, leg_id: str, *, action: str, staff: dict | None, note: str = "", result: str = "", normal: bool | None = None, by: str = "") -> dict:
    """Provider accepted, or the step is done (report in, visit attended, result back)."""
    leg = _leg(case, leg_id)
    if leg["status"] == "done":
        raise ValueError("this step is already done")
    ts = now()
    who = staff["name"] if staff else (by or "facility (FHIR)")
    legs = [dict(x) for x in case["legs"]]
    cur = next(x for x in legs if x["id"] == leg_id)
    if action == "accept":
        if cur["status"] != "requested":
            raise ValueError("only a requested step can be accepted")
        cur.update(status="accepted", accepted_at=ts, due_at=ts + timedelta(days=cur["days"]))
        cur["actions"] = [*cur["actions"], {"at": ts, "text": f"Accepted by {who}"}]
        case = await _save_legs(case, legs)
        await cases.log_event(case["_id"], "staff" if staff else "system", "provider_accepted", {"service": cur["label"], "facility": cur["facility_name"], "by": who}, (staff or {}).get("_id"))
        return case
    if action != "done":
        raise ValueError("action must be accept or done")
    if cur["status"] == "waiting":
        raise ValueError("this step is waiting on an earlier one")
    if cur["kind"] == "result" and normal is None:
        raise ValueError("say whether the result is normal")
    cur.update(status="done", done_at=ts, result=(result or note).strip(), normal=normal, by=who, due_at=None)
    cur["actions"] = [*cur["actions"], {"at": ts, "text": f"Done: {(result or note).strip() or cur['label']} ({who})"}]
    await cases.log_event(
        case["_id"], "staff" if staff else "system", "provider_done",
        {"service": cur["label"], "facility": cur["facility_name"], "result": cur["result"], "normal": normal, "by": who}, (staff or {}).get("_id"),
    )
    # Unblock what was waiting on it.
    for x in legs:
        if x["status"] == "waiting" and x.get("after") == cur["key"]:
            x.update(status="requested", requested_at=ts, due_at=ts + timedelta(days=x["days"] if x["kind"] != "visit" else CHASE_DAYS))
            await cases.log_event(case["_id"], "system", "provider_requested", {"service": x["label"], "facility": x["facility_name"], "due": x["due_at"].isoformat()})
    extra: dict = {}
    if not any(x["level"] >= 3 and x["status"] != "done" for x in legs):
        extra["provider_alert"] = None
    case = await _save_legs(case, legs, extra)
    if cur["verifies"]:
        case = await _verify(case, cur, who=who)
    return case


async def _verify(case: dict, leg: dict, *, who: str) -> dict:
    from . import conversation

    if leg["normal"]:
        ver = {"at": now(), "source": leg["label"], "facility": leg["facility_name"], "result": leg["result"], "by": who}
        case = await cases.update_case(case["_id"], {"verification": ver, "next_action": "clinician_signoff"})
        await cases.log_event(case["_id"], "system", "recovery_verified", ver)
        lang = case["language"]
        first = cases.first_name(case["patient_name"])
        text = (
            f"{first}، وصلت نتيجة فحص المتابعة وهي مطمئنة. سيراجعها طبيبك ويؤكد إغلاق متابعتك."
            if lang == "ar"
            else f"Good news, {first}: your follow-up test result is back and it is reassuring. Your clinician will review it and confirm your follow-up is complete."
        )
        await conversation.say(case, text, meta={"kind": "recovery_verified"})
        return case
    await cases.log_event(case["_id"], "system", "result_not_resolved", {"service": leg["label"], "result": leg["result"]})
    return await conversation.escalate_with_summary(case, f"Follow-up result not resolved: {leg['result'] or leg['label']}. Clinician to revise the care plan.", pause_ai=False)


async def monitor(case_id: str | None = None) -> dict:
    """
    One pass over every overdue provider step (or one case's): each missed
    deadline moves that step one level up the escalation ladder.
    """
    stats = {"chased": 0, "rerouted": 0, "escalated": 0}
    q: dict = {"status": {"$in": ["follow_up", "escalated"]}, "legs": {"$elemMatch": {"status": {"$in": ["requested", "accepted"]}, "due_at": {"$lte": now()}, "level": {"$lt": 3}}}}
    if case_id:
        q["_id"] = case_id
    async for case in db().cases.find(q).limit(50):
        try:
            await _escalate_legs(case, stats)
        except Exception:  # noqa: BLE001 - one case must not stall the rest
            logger.exception("Provider monitor failed on %s", case["_id"])
    return stats


async def _escalate_legs(case: dict, stats: dict) -> None:
    from . import conversation

    ts = now()
    legs = [dict(x) for x in case["legs"]]
    alert = case.get("provider_alert")
    patient_note = None
    for leg in legs:
        if leg["status"] not in ("requested", "accepted") or not leg["due_at"] or leg["due_at"] > ts or leg["level"] >= 3:
            continue
        late = (ts - (leg.get("requested_at") or ts)).days
        blocked = [x["label"] for x in legs if x.get("after") == leg["key"] and x["status"] == "waiting"]
        blocks = f" Blocking: {', '.join(blocked)}." if blocked else ""
        nxt = leg["level"] + 1
        if nxt == 2 and leg["kind"] == "visit":
            alt, network_ok = referrals.choose_facility(leg["service"], case.get("region", ""), case.get("insurance", ""), exclude=set(leg["tried"]))
            if alt:
                old = leg["facility_name"]
                leg.update(facility_id=alt["id"], facility_name=alt["name"]["en"], network_ok=network_ok, tried=[*leg["tried"], alt["id"]], level=2, requested_at=ts, due_at=ts + timedelta(days=CHASE_DAYS))
                leg["actions"] = [*leg["actions"], {"at": ts, "level": 2, "text": f"No response from {old}. Re-routed to {alt['name']['en']} (in network)"}]
                await cases.log_event(case["_id"], "system", "provider_rerouted", {"service": leg["label"], "from": old, "to": alt["name"]["en"], "network_ok": network_ok, "reason": f"no response from {old}"})
                lang = case["language"]
                svc = referrals.SERVICES[leg["service"]][1 if lang == "ar" else 0]
                patient_note = (
                    f"تحديث: لتسريع رعايتك، حوّلنا موعد {svc} إلى {alt['name']['ar']}. سنرسل لك الموعد قريباً."
                    if lang == "ar"
                    else f"Update: to avoid a delay, we have moved your {svc} to {alt['name']['en']}, {alt['address']['en']}. We will send you the appointment soon."
                )
                await notify_provider(case, leg, "new")
                stats["rerouted"] += 1
                continue
            nxt = 3
        if nxt == 1:
            leg.update(level=1, due_at=ts + timedelta(days=CHASE_DAYS))
            leg["actions"] = [*leg["actions"], {"at": ts, "level": 1, "text": f"Deadline missed. Chased {leg['facility_name']} automatically"}]
            await cases.log_event(case["_id"], "system", "provider_chased", {"service": leg["label"], "facility": leg["facility_name"], "days_waiting": late})
            await notify_provider(case, leg, "chase", days=late)
            stats["chased"] += 1
            continue
        # Level 3: a person takes it.
        reason = f"{leg['label']} at {leg['facility_name']}: no {'report' if leg['kind'] == 'report' else 'response'} after automatic chase.{blocks}"
        leg.update(level=3, due_at=None)
        leg["actions"] = [*leg["actions"], {"at": ts, "level": 3, "text": "Escalated to the care coordinator"}]
        alert = {"reason": reason, "at": ts, "leg": leg["id"], "service": leg["label"], "facility": leg["facility_name"]}
        await cases.log_event(case["_id"], "system", "provider_escalated", {"reason": reason, "owner": case.get("owner_name")})
        await conversation.notify_staff(case, "Provider delay", reason)
        stats["escalated"] += 1
    await _save_legs(case, legs, {"provider_alert": alert, "overdue": bool(alert)})
    if patient_note:
        await conversation.say(case, patient_note, meta={"kind": "provider_rerouted"})


def provider_link(leg: dict) -> str:
    from .config import settings

    return f"{settings.app.patient_app_url}/provider?t={leg.get('token', '')}" if settings.app.patient_app_url and leg.get("token") else ""


def _initials(name: str) -> str:
    return " ".join(f"{p[0]}." for p in name.split() if p)[:12]


async def notify_provider(case: dict, leg: dict, kind: str, days: int = 0) -> None:
    """
    The referral desk hears about it on WhatsApp, with the provider page link.
    Initials and case number only: the clinical detail is behind the link.
    """
    from . import whatsapp
    from .config import settings

    phone = settings.app.provider_desk_phone
    if not phone:
        return
    head = "OziCare referral: reminder" if kind == "chase" else "OziCare referral: new request"
    when = f"Requested {days} day{'s' if days != 1 else ''} ago and now overdue." if kind == "chase" else "Re-routed to you to avoid a delay for the patient."
    action = "send the report" if leg["kind"] != "visit" else "confirm an appointment"
    text = (
        f"{head}\n{leg['facility_name']}: {leg['label']}\n"
        f"Patient {_initials(case['patient_name'])} (case {case['_id']}), {case['urgency']} priority.\n"
        f"{when}\nPlease {action} here: {provider_link(leg)}"
    )
    try:
        pid = await whatsapp.send_text(cases.normalize_phone(phone), text)
        await cases.log_event(case["_id"], "system", "provider_notified", {"facility": leg["facility_name"], "service": leg["label"], "kind": kind, "channel": "whatsapp", "sent": bool(pid)})
    except Exception as exc:  # noqa: BLE001 - the dashboard alert still stands
        logger.warning("Provider desk message failed: %s", exc)


# --------------------------------------------------------------------------
# Check-ins
# --------------------------------------------------------------------------

CHECKIN_TEXT = {
    "en": "Hi {first}, this is your {org} check-in after your visit. How are you feeling? Tap below, or tap Talk to us to speak to our assistant.",
    "ar": "مرحباً {first}، هذه متابعة {org} بعد زيارتك. كيف تشعرين؟ اضغطي أدناه، أو اضغطي تحدث معنا للتحدث مع مساعدنا.",
}
CHECKIN_BUTTONS = {
    "en": [("ck_ok", "Feeling well"), ("ck_concern", "I have a concern")],
    "ar": [("ck_ok", "أشعر بخير"), ("ck_concern", "لدي قلق")],
}


async def send_checkin(case: dict) -> None:
    """The next scheduled check-in, on WhatsApp, with the call button."""
    from . import conversation
    from .config import settings
    from .content import t

    lang = case["language"]
    cks = [dict(c) for c in case.get("checkins") or []]
    nxt = next((c for c in cks if c["status"] == "scheduled"), None)
    if nxt is None:
        nxt = {"id": new_id("CK"), "day": None, "due_at": now(), "status": "scheduled", "channel": None, "answers": None, "summary": "", "done_at": None}
        cks.append(nxt)
    nxt.update(status="sent", sent_at=now())
    await cases.update_case(case["_id"], {"checkins": cks, "conv_state": "await_checkin"})
    first = cases.first_name(case["patient_name"])
    await conversation.say(case, CHECKIN_TEXT[lang].format(first=first, org=settings.app.org_name), buttons=CHECKIN_BUTTONS[lang], meta={"kind": "checkin"})
    await conversation.say(case, t("call_me", lang), call_button=t("call_button", lang), meta={"kind": "call_button"})
    await cases.log_event(case["_id"], "system", "checkin_sent", {"day": nxt["day"]})


async def record_checkin(case: dict, *, channel: str, feeling: str, following_plan: bool | None, warning_signs: str = "", notes: str = "") -> dict:
    """Answers from WhatsApp or the call. Any warning sign goes to a clinician."""
    from . import conversation

    cks = [dict(c) for c in case.get("checkins") or []]
    cur = next((c for c in cks if c["status"] == "sent"), None) or next((c for c in cks if c["status"] == "scheduled"), None)
    if cur is None:
        cur = {"id": new_id("CK"), "day": None, "due_at": now(), "status": "scheduled"}
        cks.append(cur)
    concern = bool(warning_signs.strip())
    answers = {"feeling": feeling, "following_plan": following_plan, "warning_signs": warning_signs.strip(), "notes": notes.strip()}
    cur.update(status="done", channel=channel, answers=answers, done_at=now(), concern=concern)
    case = await cases.update_case(case["_id"], {"checkins": cks, "conv_state": None})
    await cases.log_event(case["_id"], "patient", "checkin_done", {"channel": channel, **answers})
    if concern:
        case = await conversation.escalate_with_summary(case, f"Check-in: patient reports {warning_signs.strip()[:200]}", actor="patient", pause_ai=False)
    return case


async def due_checkins() -> int:
    """Scheduler: send check-ins that are due."""
    sent = 0
    async for case in db().cases.find({"status": "follow_up", "checkins": {"$elemMatch": {"status": "scheduled", "due_at": {"$lte": now()}}}}).limit(50):
        try:
            await send_checkin(case)
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception("Check-in failed on %s", case["_id"])
    return sent


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


def evidence(case: dict) -> dict:
    """What proves the loop closed, item by item. `required` items gate closure."""
    ref = case.get("referral") or {}
    cp = case.get("care_plan")
    legs = case.get("legs") or []
    cks = [c for c in case.get("checkins") or [] if c.get("status") == "done"]
    ver = case.get("verification")
    so = case.get("signoff")
    appt = case.get("appointment") or {}

    def item(key, label, ok, at=None, detail="", required=True):
        return {"key": key, "label": label, "ok": bool(ok), "at": at.isoformat() if hasattr(at, "isoformat") else at, "detail": detail, "required": required}

    open_legs = [x for x in legs if x["status"] != "done"]
    items = [
        item("result", "Screening result and risk rules applied", True, case.get("created_at"), ", ".join(f["reason"] for f in case.get("risk_findings", []))[:160]),
        item("referral", "Referral accepted by receiving clinic", ref.get("status") == "accepted", ref.get("responded_at"), f"{ref.get('service_label', '')}, {ref.get('facility_name') or ''} ({ref.get('responder') or 'pending'})"),
        item("informed", "Patient informed and confirmed identity", case.get("acknowledged_at"), case.get("acknowledged_at"), "WhatsApp + AI call, transcript in timeline"),
        item("attended", "Attended first visit (Encounter)", case.get("attended_at"), case.get("attended_at"), f"{appt.get('label', '')}, {appt.get('clinic', '')}".strip(", ")),
        item("care_plan", "Post-visit care plan documented", cp, (cp or {}).get("at"), f"by {cp['by']}" if cp else ""),
        item(
            "providers",
            "Every provider step completed",
            legs and not open_legs,
            max((x["done_at"] for x in legs if x.get("done_at")), default=None),
            f"{len(legs) - len(open_legs)}/{len(legs)} done" + (f"; open: {', '.join(x['label'] for x in open_legs)}" if open_legs else ""),
        ),
        item("checkins", "Recovery check-ins with the patient", cks, cks[-1]["done_at"] if cks else None, f"{len(cks)} completed" if cks else "none yet", required=False),
        item("verified", "Recovery verified by a result", ver, (ver or {}).get("at"), f"{ver['source']}: {ver['result']}" if ver else (cp or {}).get("verify_text", "")),
        item("signoff", "Clinician sign-off", so, (so or {}).get("at"), f"{so['by']}: {so['note']}" if so else ""),
    ]
    missing = [i["label"] for i in items if i["required"] and not i["ok"] and i["key"] != "signoff"]
    return {"items": items, "missing": missing, "ready_to_close": not missing, "complete": not missing and bool(so)}


async def sign_off(case: dict, *, staff: dict, note: str) -> dict:
    """The clinician closes the loop: refused while evidence is missing."""
    ev = evidence(case)
    if ev["missing"]:
        raise cases.TransitionError("Cannot close: missing " + "; ".join(ev["missing"]))
    # Check-ins still ahead are no longer needed once the loop is closed.
    cks = [{**k, "status": "cancelled"} if k.get("status") in ("scheduled", "sent") else k for k in case.get("checkins") or []]
    await cases.update_case(case["_id"], {"checkins": cks})
    so = {"by": staff["name"], "by_id": staff["_id"], "role": staff["role"], "at": now(), "note": note.strip() or "Loop closed with evidence"}
    case = await cases.transition(case["_id"], "closed_completed", actor="staff", actor_id=staff["_id"], note=so["note"], extra={"signoff": so})
    await cases.log_event(case["_id"], "staff", "signed_off", {"by": staff["name"], "note": so["note"]}, staff["_id"])
    return case
