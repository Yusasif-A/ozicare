"""
The WhatsApp conversation: outbound contact and the inbound router.

Order of checks on every inbound message is deliberate and safety-first:

  1. emergency symptoms  -> emergency text + escalate (never waits on the LLM)
  2. language switch     -> "عربي" / "English"
  3. staff has taken over (ai_paused) -> log only, staff replies from dashboard
  4. identity + consent  -> nothing about the result is shared before YES
  5. menu intents        -> explain / book / call / decline / human
  6. free text           -> bounded LLM answer, guard-checked, template fallback
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from . import cases, content, guard, llm, whatsapp
from .config import settings
from .content import t
from .db import db, now

logger = logging.getLogger("ozicare.conversation")

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ARABIC = re.compile(r"[؀-ۿ]")

_INTENT_WORDS = {
    "explain": r"\b(explain|result|what does it mean|meaning)\b|شرح|اشرح|نتيجة|نتيجتي",
    "book": r"\b(book|appointment|slot|schedule)\b|حجز|احجز|موعد",
    "call": r"\b(call|phone|ring)\b|اتصل|اتصال|مكالمة",
    "decline": r"\b(stop|unsubscribe|no follow[- ]?up|not interested|don'?t want)\b|لا أريد|لا اريد|توقف|إيقاف",
}
_YES = re.compile(r"^\s*(yes|y|yeah|yep|confirm|it'?s me|نعم|اي|أيوه|ايوه|أنا|انا|صحيح)\b", re.IGNORECASE)
_NO = re.compile(r"^\s*(no|n|nope|wrong|not me|لا|ليس أنا|ليس انا|رقم خطأ)\b", re.IGNORECASE)
_TO_AR = re.compile(r"^\s*(عربي|العربية|arabic)\s*$", re.IGNORECASE)
_TO_EN = re.compile(r"^\s*(english|انجليزي|إنجليزي|الإنجليزية)\s*$", re.IGNORECASE)


def _normalise(text: str) -> str:
    return (text or "").translate(_AR_DIGITS).strip()


def _intent(text: str, button_id: str | None) -> str | None:
    if button_id in ("explain", "book", "call", "decline"):
        return button_id
    norm = _normalise(text)
    if norm in ("1", "2", "3", "4"):
        return {"1": "explain", "2": "book", "3": "call", "4": "decline"}[norm]
    for name, pattern in _INTENT_WORDS.items():
        if re.search(pattern, norm, re.IGNORECASE):
            return name
    return None


# --------------------------------------------------------------------------
# Sending, always logged against the case
# --------------------------------------------------------------------------


async def say(case: dict, text: str, *, buttons: list[tuple[str, str]] | None = None, call_button: str | None = None, meta: dict | None = None, actor: str = "system") -> str | None:
    to = case["phone"]
    try:
        if call_button:
            pid = await whatsapp.send_call_button(to, text, call_button)
        elif buttons:
            pid = await whatsapp.send_buttons(to, text, buttons)
        else:
            pid = await whatsapp.send_text(to, text)
    except whatsapp.WhatsAppError as exc:
        await cases.log_message(case["_id"], "whatsapp", "outbound", text, meta={**(meta or {}), "error": str(exc), "by": actor}, phone=to)
        await cases.log_event(case["_id"], "system", "delivery_failed", {"error": str(exc)})
        return None
    await cases.log_message(case["_id"], "whatsapp", "outbound", text, provider_message_id=pid, meta={**(meta or {}), "by": actor}, phone=to)
    return pid


def _menu_buttons(lang: str, include_explain: bool = True) -> list[tuple[str, str]]:
    keys = (["explain"] if include_explain else []) + ["book", "call"]
    return [(k, content.BUTTONS[k][lang]) for k in keys]


# --------------------------------------------------------------------------
# Outbound contact (called by the API on create, and by the scheduler)
# --------------------------------------------------------------------------


async def contact_patient(case: dict, *, reminder: bool = False) -> bool:
    """
    First contact, or a reminder. Uses the approved template when one is
    configured (works any time), otherwise interactive buttons (works inside
    the 24h window — fine for a demo where the patient has messaged first).
    """
    lang = case["language"]
    fname = cases.first_name(case["patient_name"])
    org = settings.app.org_name
    template = settings.whatsapp.template_ar if lang == "ar" else settings.whatsapp.template_en

    if reminder:
        text = t("reminder", lang, first_name=fname, org=org)
    else:
        text = t("first_contact", lang, first_name=fname, org=org)
        if case["urgency"] == "urgent":
            text += t("urgent_suffix", lang)

    pid = None
    if template:
        try:
            pid = await whatsapp.send_template(case["phone"], template, lang, [fname, org])
            await cases.log_message(case["_id"], "whatsapp", "outbound", text, provider_message_id=pid, meta={"template": template}, phone=case["phone"])
        except whatsapp.WhatsAppError as exc:
            logger.warning("Template failed for %s, trying session message: %s", case["_id"], exc)
    if pid is None:
        pid = await say(case, text, buttons=_menu_buttons(lang), meta={"kind": "reminder" if reminder else "first_contact"})

    attempts = case.get("attempts", 0) + 1
    if pid is None:
        # Retry soon; the board shows delivery_failed in the timeline meanwhile.
        await cases.update_case(case["_id"], {"attempts": attempts, "next_action_at": now() + timedelta(minutes=10), "next_action": "contact"})
        return False

    fields = {"attempts": attempts, "next_action_at": now() + cases.ack_window(case["urgency"]), "next_action": "reminder", "last_contact_at": now()}
    await cases.log_event(case["_id"], "system", "contacted", {"channel": "whatsapp", "attempt": attempts, "reminder": reminder})
    if case["status"] == "new":
        await cases.transition(case["_id"], "contacted", actor="system", note="WhatsApp sent", extra=fields)
    else:
        await cases.update_case(case["_id"], fields)
    return True


async def send_appointment_reminder(case: dict) -> None:
    appt = case.get("appointment") or {}
    await say(case, t("appointment_reminder", case["language"], slot=appt.get("label", ""), clinic=appt.get("clinic", "")), meta={"kind": "appointment_reminder"})
    await cases.log_event(case["_id"], "system", "appointment_reminder", {})


# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------


async def transcript(case_id: str, limit: int = 40) -> str:
    rows = [m async for m in db().messages.find({"case_id": case_id}).sort("created_at", -1).limit(limit)]
    lines = []
    for m in reversed(rows):
        who = "Patient" if m["direction"] == "inbound" else ("Staff" if (m.get("meta") or {}).get("by") == "staff" else "OziCare")
        lines.append(f"[{m['channel']}] {who}: {m['body']}")
    return "\n".join(lines)


async def escalate_with_summary(case: dict, reason: str, *, actor: str = "system", pause_ai: bool = True) -> dict:
    summary = await llm.summarise(
        f"Case {case['_id']}: {case['screening_type']} ({case['urgency']}). Reason for escalation: {reason}\n\n" + await transcript(case["_id"])
    )
    case = await cases.escalate(case, reason, actor=actor, summary=summary)
    if pause_ai:
        case = await cases.update_case(case["_id"], {"ai_paused": True})
    await notify_staff(case, reason, summary)
    return case


async def notify_staff(case: dict, reason: str, summary: str) -> None:
    """Best effort: the dashboard banner is the primary alert, this is the pager."""
    phone = settings.app.escalation_phone
    if not phone:
        return
    text = (
        f"OziCare escalation {case['_id']} ({case['urgency'].upper()})\n"
        f"Patient: {case['patient_name']} ***{case['phone'][-4:]}\n"
        f"Reason: {reason}\nOwner: {case.get('owner_name') or 'unassigned'}\n\n{summary}"
    )
    try:
        await whatsapp.send_text(cases.normalize_phone(phone), text[:4000])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Escalation notify failed: %s", exc)


# --------------------------------------------------------------------------
# Inbound
# --------------------------------------------------------------------------


async def handle_inbound(msg: dict) -> None:
    phone = msg["from"]
    text = msg.get("text", "")
    case = await cases.active_case_for_phone(phone)

    if case is None:
        await cases.log_message(None, "whatsapp", "inbound", text, provider_message_id=msg.get("id"), phone=phone)
        latest = await cases.latest_case_for_phone(phone)
        lang = (latest or {}).get("language") or ("ar" if _ARABIC.search(text) else "en")
        try:
            await whatsapp.send_text(phone, t("no_case", lang, org=settings.app.org_name))
        except whatsapp.WhatsAppError:
            pass
        return

    await cases.log_message(case["_id"], "whatsapp", "inbound", text, provider_message_id=msg.get("id"), meta={"button_id": msg.get("button_id")}, phone=phone)
    await db().cases.update_one({"_id": case["_id"]}, {"$set": {"last_inbound_at": now()}})

    # 1. Emergency — before anything else, and never via the LLM.
    if guard.is_emergency(text):
        await say(case, t("emergency", case["language"]), meta={"kind": "emergency"})
        await escalate_with_summary(case, f"Possible emergency reported by patient: \"{text[:200]}\"", actor="patient")
        return

    # 2. Language.
    norm = _normalise(text)
    if _TO_AR.match(norm) or _TO_EN.match(norm):
        lang = "ar" if _TO_AR.match(norm) else "en"
        case = await _set_language(case, lang)
        await say(case, t("language_set", lang) + "\n\n" + t("menu", lang), buttons=_menu_buttons(lang))
        return
    if case["language"] == "en" and _ARABIC.search(text) and not norm.isdigit():
        case = await _set_language(case, "ar")

    lang = case["language"]
    intent = _intent(text, msg.get("button_id"))

    # 3. A human has taken over this conversation: the bot stays out of it.
    if case.get("ai_paused"):
        await cases.log_event(case["_id"], "patient", "message_while_paused", {"text": text[:300]})
        return

    # 4. Identity before any detail.
    if not case.get("identity_confirmed"):
        await _identity_step(case, text, intent)
        return

    # Slot selection.
    if case.get("conv_state") == "await_slot":
        chosen = _chosen_slot(case, norm, msg.get("button_id"))
        if chosen is not None:
            await _confirm_booking(case, chosen)
            return

    if guard.wants_human(text) and intent is None:
        await say(case, t("human_requested", lang), meta={"kind": "human_requested"})
        await escalate_with_summary(case, "Patient asked to speak to a person", actor="patient")
        return

    await _run_intent(case, intent, text)


async def _set_language(case: dict, lang: str) -> dict:
    await db().patients.update_one({"_id": case["patient_id"]}, {"$set": {"preferred_language": lang}})
    await cases.log_event(case["_id"], "patient", "language_changed", {"to": lang})
    return await cases.update_case(case["_id"], {"language": lang})


async def _identity_step(case: dict, text: str, intent: str | None) -> None:
    lang = case["language"]
    norm = _normalise(text)
    if case.get("conv_state") == "await_identity":
        if _YES.match(norm):
            await db().patients.update_one({"_id": case["patient_id"]}, {"$set": {"consent_at": now()}})
            case = await cases.update_case(case["_id"], {"identity_confirmed": True, "conv_state": None})
            await cases.log_event(case["_id"], "patient", "identity_confirmed", {"consent": True})
            await _run_intent(case, case.get("pending_intent") or "explain", "")
            return
        if _NO.match(norm):
            await say(case, t("wrong_person", lang), meta={"kind": "wrong_person"})
            await escalate_with_summary(case, "Recipient says this is the wrong person — check the phone number", actor="patient")
            return
    # First reply, or an unclear one: ask (again). Remember what they wanted.
    await cases.update_case(case["_id"], {"conv_state": "await_identity", "pending_intent": intent})
    await say(case, t("confirm_identity", lang, first_name=cases.first_name(case["patient_name"])), meta={"kind": "confirm_identity"})


async def _run_intent(case: dict, intent: str | None, text: str) -> None:
    lang = case["language"]

    if intent == "explain":
        case = await cases.acknowledge(case)
        await say(case, content.explanation(case["screening_type"], lang, case.get("result_summary", "")), meta={"kind": "explain", "approved": True})
        await say(case, t("menu", lang), buttons=_menu_buttons(lang, include_explain=False))
        await cases.update_case(case["_id"], {"conv_state": None})
        return

    if intent == "book":
        case = await cases.acknowledge(case)
        slots = cases.next_slots(lang)
        await cases.update_case(case["_id"], {"conv_state": "await_slot", "offered_slots": slots})
        clinic = content.CLINIC[lang]["name"]
        lines = "\n".join(f"{i}. {s['label']}" for i, s in enumerate(slots, 1))
        body = f"{t('slots_intro', lang, clinic=clinic)}\n\n{lines}\n\n{t('slots_other', lang)}"
        buttons = [(f"slot_{i}", s["label"].replace(" الساعة", "")) for i, s in enumerate(slots)]
        await say(case, body, buttons=buttons, meta={"kind": "slots"})
        await cases.log_event(case["_id"], "system", "slots_offered", {"slots": [s["label"] for s in slots]})
        return

    if intent == "call":
        case = await cases.acknowledge(case)
        await cases.update_case(case["_id"], {"callback_requested_at": now()})
        await cases.log_event(case["_id"], "patient", "callback_requested", {"channel": "whatsapp"})
        await say(case, t("call_me", lang), call_button=t("call_button", lang), meta={"kind": "call_button"})
        return

    if intent == "decline":
        if case.get("conv_state") == "await_decline_confirm":
            await cases.transition(case["_id"], "closed_declined", actor="patient", note="Declined on WhatsApp after explanation")
            await say(case, t("declined", lang), meta={"kind": "declined"})
        else:
            await cases.update_case(case["_id"], {"conv_state": "await_decline_confirm"})
            await say(case, t("decline_confirm", lang), meta={"kind": "decline_confirm"})
        return

    # Free text: the only place the LLM speaks.
    case = await cases.acknowledge(case)
    history = await _llm_history(case["_id"])
    reply, audit = await llm.answer_question(
        text, lang=lang, screening_type=case["screening_type"], result_summary=case.get("result_summary", ""), history=history
    )
    if reply is None:
        await say(case, t("fallback", lang), buttons=_menu_buttons(lang), meta={"kind": "fallback", "ai": audit})
        if audit.get("blocked"):
            await cases.log_event(case["_id"], "ai", "ai_reply_blocked", audit)
        return
    await say(case, reply, meta={"kind": "ai_answer", "ai": audit}, actor="ai")
    await cases.log_event(case["_id"], "ai", "ai_answer", {"question": text[:300], "reply": reply})


async def _llm_history(case_id: str) -> list[dict]:
    rows = [m async for m in db().messages.find({"case_id": case_id, "channel": "whatsapp"}).sort("created_at", -1).limit(7)]
    rows = list(reversed(rows))[:-1]  # drop the message being answered
    return [{"role": "user" if m["direction"] == "inbound" else "assistant", "content": m["body"][:600]} for m in rows]


def _chosen_slot(case: dict, norm: str, button_id: str | None) -> dict | None:
    slots = case.get("offered_slots") or []
    idx = None
    if button_id and button_id.startswith("slot_"):
        idx = int(button_id.split("_")[1])
    elif norm.isdigit():
        idx = int(norm) - 1
    if idx is not None and 0 <= idx < len(slots):
        return slots[idx]
    return None


async def _confirm_booking(case: dict, slot: dict) -> None:
    lang = case["language"]
    case = await cases.book(case, slot, actor="patient", channel="whatsapp")
    appt = case["appointment"]
    s = content.screening(case["screening_type"], lang)
    await say(case, t("booked", lang, slot=appt["label"], clinic=appt["clinic"], address=appt["address"], bring=s["bring"]), meta={"kind": "booked"})
