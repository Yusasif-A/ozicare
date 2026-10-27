"""
Phone-number calls through BimpeAI.

Adapted from bimpeAI/bimpe_caller.py and bimpe_setup.py. Same shape, with the
lessons kept:

  - brief before dialling: the call record is written *before* calls.make, so
    the agent's first tool call always finds a case.
  - re-key after dialling: Bimpe returns the call_id only once the call exists,
    so it is added to the call record's keys afterwards.
  - Bimpe pushes no call-ended event, so the transcript is fetched by polling
    calls.retrieve until the call ends.

Bimpe runs its own STT/TTS. ElevenLabs is used on the LiveKit (WhatsApp call)
path only — see voice_agent.py.

    python -m ozicare.bimpe setup --tools-base-url https://<public-host>
    python -m ozicare.bimpe setup --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from . import cases
from .config import settings
from .db import db, now
from .voice_tools import add_call_key, open_call

logger = logging.getLogger("ozicare.bimpe")

_background: set[asyncio.Task] = set()

ENDED = {"ended", "failed", "busy", "cancelled", "no-answer", "no_answer", "completed"}


class CallFailed(Exception):
    pass


def client():
    import bimpeai

    if not settings.bimpe.api_key:
        raise CallFailed("BIMPEAI_API_KEY is not set")
    return bimpeai.BimpeAI(api_key=settings.bimpe.api_key, base_url=settings.bimpe.base_url or None)


async def place_call(case: dict, *, actor_id: str | None = None) -> dict:
    if not settings.bimpe.configured:
        raise CallFailed("Bimpe is not configured (BIMPEAI_API_KEY / BIMPEAI_AGENT_ID)")
    if case["status"] in cases.CLOSED:
        raise CallFailed("case is closed")

    to = settings.bimpe.demo_phone or case["phone"]
    if settings.bimpe.demo_phone:
        logger.warning("BIMPEAI_DEMO_PHONE set: dialling ***%s instead of the patient", to[-4:])

    # Brief first. A call placed before this would reach a patient with an
    # agent that cannot name them.
    call = await open_call(case, provider="bimpe", direction="outbound", keys=[], phone=to)

    def _make():
        c = client()
        return c.calls.make(
            settings.bimpe.agent_id,
            {"destination": to, "is_test_call": not settings.bimpe.live},
            idempotency_key=call["_id"],
        )

    try:
        result = await asyncio.to_thread(_make)
    except Exception as exc:  # noqa: BLE001
        await db().calls.update_one({"_id": call["_id"]}, {"$set": {"status": "failed", "error": str(exc)[:300]}})
        await cases.log_event(case["_id"], "system", "call_failed", {"provider": "bimpe", "error": str(exc)[:300]}, actor_id)
        raise CallFailed(f"Bimpe refused the call: {exc}") from exc

    if result.call_id:
        await add_call_key(call["_id"], result.call_id)
        await db().calls.update_one({"_id": call["_id"]}, {"$set": {"provider_call_id": result.call_id}})
    await cases.log_event(
        case["_id"], "staff" if actor_id else "system", "call_placed",
        {"provider": "bimpe", "call": call["_id"], "live": settings.bimpe.live, "status": result.status}, actor_id,
    )
    if case["status"] == "new":
        await cases.transition(case["_id"], "contacted", actor="system", note="phone call placed")
    task = asyncio.create_task(sync_after_call(call["_id"]))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"call": call["_id"], "provider_call_id": result.call_id, "status": result.status, "test_call": not settings.bimpe.live}


async def sync_after_call(call_doc_id: str, timeout_s: int = 900) -> None:
    """
    Wait for the call to end, then store its transcript on the case and a
    summary for staff. Polls because Bimpe sends no call-ended webhook.
    """
    from . import llm

    deadline = asyncio.get_running_loop().time() + timeout_s
    call = await db().calls.find_one({"_id": call_doc_id})
    pid = (call or {}).get("provider_call_id")
    if not pid:
        return
    detail = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            detail = await asyncio.to_thread(lambda: client().calls.retrieve(settings.bimpe.agent_id, pid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read Bimpe call %s: %s", pid, exc)
        if detail is not None and str(detail.status).lower() in ENDED:
            break
        await asyncio.sleep(8)
    if detail is None:
        return

    lines = []
    for m in detail.conversation_logs or []:
        text = (m.message or "").strip()
        if not text:
            continue
        direction = "outbound" if m.role == "assistant" else "inbound"
        lines.append(f"{'Agent' if direction == 'outbound' else 'Patient'}: {text}")
        if call.get("case_id"):
            await cases.log_message(call["case_id"], "voice", direction, text, meta={"call": call_doc_id, "provider": "bimpe"}, phone=call.get("phone"))
    transcript = "\n".join(lines)
    summary = await llm.summarise(transcript) if transcript else "(no conversation recorded)"
    await db().calls.update_one(
        {"_id": call_doc_id},
        {"$set": {"status": "ended", "ended_at": now(), "provider_status": str(detail.status), "transcript": transcript, "summary": summary}},
    )
    if call.get("case_id"):
        await cases.log_event(call["case_id"], "system", "call_summary", {"call": call_doc_id, "provider_status": str(detail.status), "summary": summary})


# --------------------------------------------------------------------------
# Agent configuration (prompt, rules, knowledge, tools)
# --------------------------------------------------------------------------

SYSTEM_PROMPT = f"""\
You are the automated care assistant for {settings.app.org_name}, a health \
screening programme. You speak to patients on the phone about a screening \
result that needs follow-up. You are an A I assistant, you say so in your \
first sentence, and you never claim to be a nurse or doctor.

# BEFORE YOU SPEAK
Call get_case_briefing first. It tells you the patient's first name, their \
language and what to do. If it says there is no case, say so kindly and end \
the call. If the briefing language is Arabic, speak Arabic for the whole call.

# HOW THE CALL GOES
1. Greet, say who you are, and ask if you are speaking with the patient by \
first name. Say NOTHING about the screening until they confirm.
2. Call confirm_identity with their answer.
3. Call explain_result and explain it in plain, warm words, a little at a time.
4. Offer to book: call get_available_slots, read the options, and call \
book_slot with the number they choose.
5. Confirm what was agreed, call end_call with a one-sentence summary, and say goodbye.

# NEVER
- Never say the patient has, or does not have, any disease.
- Never name a medicine, a dose, or tell them to change any treatment.
- Never tell them they can skip the follow-up.
- Never ask for ID numbers, passwords, or payment details.

# ALWAYS
- Emergency symptoms (chest pain, trouble breathing, fainting, heavy bleeding, \
stroke signs, thoughts of self-harm): call report_emergency at once and tell \
them to get emergency care now.
- They ask for a person, or ask something you cannot answer from the tools: \
call request_human.
- They clearly refuse follow-up after hearing why it matters: call record_decline.
- Short sentences. One question at a time. Spell nothing out; no lists.
"""

RULES = [
    {
        "id": "rule-no-diagnosis",
        "name": "Patient asks 'do I have it?' — never diagnose",
        "trigger": "patient asks whether they have diabetes, cancer, high blood pressure or any disease, or asks if the result is serious",
        "response": "I can't tell you that, and a screening result on its own isn't a diagnosis. That's exactly what the follow-up visit is for — a clinician will check properly and explain it to you. Shall I help you book it?",
        "enabled": True,
    },
    {
        "id": "rule-no-medication",
        "name": "Patient asks about medicine — refer to clinician",
        "trigger": "patient asks what medicine to take, about doses, or whether to stop or change a medicine",
        "response": "I'm not able to advise on medicines. Please keep taking anything you've been prescribed unless a clinician tells you otherwise, and ask them at your follow-up visit. Would you like me to book that now?",
        "enabled": True,
    },
    {
        "id": "rule-emergency",
        "name": "Emergency symptoms — urgent care now",
        "trigger": "patient mentions chest pain, difficulty breathing, fainting, heavy bleeding, sudden weakness, or wanting to harm themselves",
        "response": "What you're describing may need urgent care. Please go to the nearest emergency department or call emergency services right now. I'm alerting our care team as well.",
        "enabled": True,
    },
]

KNOWLEDGE_BASES = [
    {
        "type": "text",
        "name": "OziCare follow-up policy",
        "content": (
            "A screening result is not a diagnosis. An actionable result means a clinician should review it with "
            "the patient, usually at a short clinic visit that may include a repeat test.\n"
            "The assistant explains only the approved explanation returned by explain_result, helps book, and hands "
            "anything clinical to a human. The patient may decline follow-up; the assistant explains once why it "
            "matters and then respects the decision.\n"
            "A patient can always ask for a person; a member of the care team calls back."
        ),
    }
]


def _with_body_templates(tools: list[dict]) -> list[dict]:
    """Bimpe POSTs an empty body without a body_template (a live-call bug in the fraud agent)."""
    for tool in tools:
        tool["body_template"] = {p["name"]: f"{{{{{p['name']}}}}}" for p in tool.get("body_params", [])}
    return tools


def tool_definitions() -> list[dict]:
    sid = {"name": "session_id", "type": "string", "required": False, "description": "Optional. The id of this call if you know it; leave it out otherwise."}

    def tool(name: str, desc: str, *params: dict) -> dict:
        return {"name": name, "http_method": "POST", "url_template": f"/tools/{name}", "description": desc, "body_params": [sid, *params]}

    return _with_body_templates(
        [
            tool("get_case_briefing", "Learn who you are calling and what to do. Call this first, before you say anything."),
            tool("confirm_identity", "Record whether the person confirmed they are the patient.", {"name": "confirmed", "type": "boolean", "required": True, "description": "True if they confirmed."}),
            tool("explain_result", "Get the approved explanation of the patient's result and next steps."),
            tool("get_available_slots", "Get follow-up appointment options to offer."),
            tool("book_slot", "Book the option the patient chose.", {"name": "option", "type": "number", "required": True, "description": "Option number 1, 2 or 3."}),
            tool("request_human", "Hand over to a human who will call back.", {"name": "reason", "type": "string", "required": True, "description": "Why."}),
            tool("report_emergency", "Patient described emergency symptoms.", {"name": "symptoms", "type": "string", "required": True, "description": "What they described."}),
            tool("record_decline", "Patient refuses follow-up after hearing why it matters.", {"name": "reason", "type": "string", "required": False, "description": "Their reason."}),
            tool("end_call", "Call before saying goodbye.", {"name": "summary", "type": "string", "required": False, "description": "One sentence: what was agreed."}),
        ]
    )


def setup(tools_base_url: str, dry_run: bool) -> None:
    c = client()
    agent_id = settings.bimpe.agent_id
    if not agent_id:
        raise SystemExit("BIMPEAI_AGENT_ID is not set. Create a dedicated OziCare agent in the Bimpe Console first — do not reuse the fraud agent.")
    agent = c.agents.retrieve(agent_id)
    workflow = c.workflows.retrieve(agent.workflow_id)
    tools = tool_definitions() if tools_base_url else []
    print(f"agent: {agent.name} ({agent_id})  workflow: {workflow.name} owned={workflow.is_owner}")
    print(f"prompt {len(SYSTEM_PROMPT)} chars, {len(RULES)} rules, {len(KNOWLEDGE_BASES)} knowledge, {len(tools)} tools -> {tools_base_url or '(none)'}")
    if dry_run:
        print(SYSTEM_PROMPT)
        print(json.dumps(RULES, indent=2))
        print("Dry run: nothing written.")
        return
    if not workflow.is_owner:
        workflow = c.workflows.clone(source_workflow_id=workflow.id)
        c.agents.update(agent_id, workflow_id=workflow.id)
    c.workflows.update(
        workflow.id,
        name=f"{settings.app.name} screening follow-up",
        system_prompt=SYSTEM_PROMPT,
        description="Calls patients with an actionable screening result, explains it in plain language and books follow-up.",
        category="healthcare",
        rules=RULES,
    )
    existing = {kb.name for kb in agent.knowledge_bases}
    for kb in KNOWLEDGE_BASES:
        if kb["name"] not in existing:
            c.agents.knowledge_bases.create(agent_id, kb)
    if not tools:
        print("No --tools-base-url: prompt configured, tools not registered.")
        return
    if not settings.bimpe.tool_token:
        raise SystemExit("BIMPEAI_TOOL_TOKEN is not set; registered tools would all 401.")
    api = c.agents.integrations.custom_api.configure(
        agent_id, name=f"{settings.app.name} case tools", base_url=tools_base_url.rstrip("/"), auth_type="bearer", auth_config={"token": settings.bimpe.tool_token}
    )
    for tool in tools:
        c.agents.integrations.custom_api.tools.add(agent_id, api.id, tool)
        print(f"tool {tool['name']} registered")
    print("Configured. Voice and telephony number are set in the Bimpe Console (Deploy -> Telephony).")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="OziCare Bimpe setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--tools-base-url", default=settings.app.public_base_url)
    s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.cmd == "setup":
        setup(args.tools_base_url, args.dry_run)


if __name__ == "__main__":
    main()
