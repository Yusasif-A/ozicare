"""
The loop that keeps cases moving when nobody is looking at them.

One asyncio task inside the API process, ticking every SCHEDULER_TICK_SECONDS.
It is idempotent per tick — every action pushes `next_action_at` forward before
the next tick can see the case — so a slow tick never double-sends.

Per due case:
  new                         -> first contact
  contacted, no ack, attempts -> reminder; urgent escalates instead of waiting
  contacted, attempts used up -> closed_lost (still reportable)
  acknowledged, not booked    -> reminder, then left overdue for staff
  booked, reminder due        -> appointment reminder
and for every open case, `overdue` is set once `sla_due_at` passes.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from . import cases, conversation
from .config import settings
from .db import db, now

logger = logging.getLogger("ozicare.scheduler")


async def tick() -> dict:
    stats = {"contacted": 0, "reminded": 0, "escalated": 0, "lost": 0, "appt_reminders": 0, "overdue": 0}
    ts = now()

    # Overdue flag first, so the board is right even if sending below fails.
    res = await db().cases.update_many(
        {"status": {"$in": list(cases.OPEN)}, "sla_due_at": {"$lt": ts}, "overdue": {"$ne": True}},
        {"$set": {"overdue": True, "overdue_since": ts}},
    )
    if res.modified_count:
        stats["overdue"] = res.modified_count
        async for c in db().cases.find({"overdue_since": ts}):
            await cases.log_event(c["_id"], "system", "overdue", {"status": c["status"]})

    due = db().cases.find({"status": {"$in": ["new", "contacted", "acknowledged", "booked"]}, "next_action_at": {"$lte": ts}}).limit(50)
    async for case in due:
        try:
            await _act(case, stats)
        except Exception:  # noqa: BLE001 - one bad case must not stall the rest
            logger.exception("Scheduler failed on %s", case["_id"])
            await db().cases.update_one({"_id": case["_id"]}, {"$set": {"next_action_at": now() + timedelta(minutes=5)}})
    return stats


async def _act(case: dict, stats: dict) -> None:
    status = case["status"]
    if status == "new":
        if await conversation.contact_patient(case):
            stats["contacted"] += 1
        return

    if status == "contacted":
        attempts = case.get("attempts", 0)
        if case["urgency"] == "urgent" and not case.get("escalated_for_no_ack"):
            # Urgent and silent: a human takes over now, not after more texts.
            await cases.update_case(case["_id"], {"escalated_for_no_ack": True})
            await conversation.escalate_with_summary(case, "Urgent result not acknowledged within SLA", pause_ai=False)
            stats["escalated"] += 1
            return
        if attempts >= settings.sla.max_attempts:
            await cases.transition(case["_id"], "closed_lost", actor="system", note=f"No response after {attempts} attempts")
            stats["lost"] += 1
            return
        await conversation.contact_patient(case, reminder=True)
        stats["reminded"] += 1
        return

    if status == "acknowledged":
        # Engaged but not booked: nudge, but never close someone who replied.
        if case.get("attempts", 0) < settings.sla.max_attempts:
            await conversation.contact_patient(case, reminder=True)
            stats["reminded"] += 1
        else:
            await cases.update_case(case["_id"], {"next_action_at": None, "next_action": "staff_follow_up"})
        return

    if status == "booked" and case.get("next_action") == "appointment_reminder":
        await conversation.send_appointment_reminder(case)
        # Nothing more is automatic: attendance is confirmed by staff.
        await cases.update_case(case["_id"], {"next_action_at": None, "next_action": "confirm_attendance"})
        stats["appt_reminders"] += 1


async def run_forever(stop: asyncio.Event) -> None:
    logger.info("Scheduler running every %ss", settings.sla.tick_seconds)
    while not stop.is_set():
        try:
            stats = await tick()
            if any(stats.values()):
                logger.info("Scheduler tick: %s", stats)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.sla.tick_seconds)
        except asyncio.TimeoutError:
            pass
