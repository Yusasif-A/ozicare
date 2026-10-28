"""
The LiveKit voice agent for WhatsApp calls.

    python -m ozicare.voice_agent dev

Speech is ElevenLabs both ways (Scribe STT, Flash v2.5 TTS), English or Arabic
per case. The LLM is Gemma. Tools are the shared voice_tools, so a WhatsApp
call and a Bimpe phone call do exactly the same things to a case.

Kept from the fraud agent (sahara-code-switch/agent.py), each for a reason
that cost a live call:
  - tts_node buffers to whole sentences and vets each before it is spoken —
    here against diagnosis/dosing instead of credential requests.
  - Gemma channel tokens are stripped before TTS.
  - session.start() and wait_for_participant() are bounded, with logs that say
    which leg failed instead of a silent hang.
  - telephony-tuned VAD and a single idle process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RoomInputOptions,
    RoomOutputOptions,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.plugins import elevenlabs, openai, silero

from . import cases, content, guard, voice_tools
from .config import settings
from .db import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", handlers=[logging.StreamHandler(stream=sys.stdout)], force=True)
logger = logging.getLogger("ozicare.voice_agent")

BLOCKED_REPLACEMENT = {
    "en": "I can't advise on that myself, but a clinician will go through it with you at your follow-up visit.",
    "ar": "لا أستطيع تقديم نصيحة في ذلك، لكن الطبيب سيناقشه معك في زيارة المتابعة.",
}

INSTRUCTIONS = """\
You are the automated care assistant for {org}, a health screening programme, \
on a WhatsApp voice call with a patient. You are an A I assistant and you say \
so. You never claim to be a nurse or doctor.

LANGUAGE: speak {language} for the whole call{switch_note}.

{who}

HOW THE CALL GOES
1. Greet them, say you are the automated assistant from {org}, and ask if you \
are speaking with {first_name}. Say NOTHING about the screening until they confirm.
2. Call confirm_identity with their answer.
3. Call explain_result and explain it in warm, plain words, a little at a time.
4. Offer to book: call get_available_slots, read the options, and call \
book_slot with the number they choose.
5. Confirm what was agreed, call end_call with a one-sentence summary, say goodbye.

NEVER say the patient has or does not have a disease. NEVER name a medicine or \
dose or tell them to change treatment. NEVER tell them to skip follow-up. NEVER \
ask for ID numbers, passwords or payment details.

Emergency symptoms (chest pain, trouble breathing, fainting, heavy bleeding, \
stroke signs, self-harm): call report_emergency immediately.
They ask for a person, or ask something the tools do not answer: call request_human.
They clearly refuse follow-up after hearing why it matters: call record_decline.

This is a phone call: short sentences, one question at a time, no lists, no \
symbols, no markdown.
"""

NO_CASE_INSTRUCTIONS = """\
You are the automated assistant for {org}. The caller has no open screening \
follow-up with us. Politely say you could not find a follow-up for this number, \
suggest they contact the clinic where they were screened, and end the call. \
Do not discuss any health matters. Speak {language}.
"""


def _build_stt(lang: str, vad) -> object:
    """
    ElevenLabs Scribe. The plugin's STT is preferred; if this plugin version
    has none, fall back to the batch wrapper proven in sahara-code-switch,
    driven by the VAD.
    """
    code = "ar" if lang == "ar" else "en"
    if hasattr(elevenlabs, "STT"):
        # Realtime streams as the patient speaks; batch Scribe measured ~3.3s
        # per Arabic utterance. The other language is secondary so a mid-call
        # switch is still transcribed. Keyterms: batch Scribe heard "OziCare"
        # as "Wally McIver" on the Arabic test clip.
        return elevenlabs.STT(
            api_key=settings.eleven.api_key,
            model="scribe_v2_realtime",
            language_code=code,
            secondary_languages=["en" if code == "ar" else "ar"],
            keyterms=[settings.app.name, settings.app.org_name[:50]],
        )
    from livekit.agents import stt as agents_stt

    from .elevenlabs_stt import ElevenLabsSTT

    return agents_stt.StreamAdapter(stt=ElevenLabsSTT(api_key=settings.eleven.api_key, model=settings.eleven.stt_model, language=code), vad=vad)


def _build_tts(lang: str):
    return elevenlabs.TTS(
        api_key=settings.eleven.api_key,
        voice_id=settings.eleven.voice_ar if lang == "ar" else settings.eleven.voice_en,
        model=settings.eleven.tts_model,
        language="ar" if lang == "ar" else "en",
    )


class CareAgent(Agent):
    def __init__(self, *, call: dict, case: dict | None, lang: str) -> None:
        self.call_id = call["_id"]
        self.case_id = (case or {}).get("_id")
        self.lang = lang
        self.blocked: list[str] = []
        language = "Arabic (Modern Standard Arabic)" if lang == "ar" else "English"
        if case is None:
            instructions = NO_CASE_INSTRUCTIONS.format(org=settings.app.org_name, language=language)
        else:
            who = "We called the patient." if call["direction"] == "outbound" else "The patient called us by tapping the call button in our WhatsApp message."
            instructions = INSTRUCTIONS.format(
                org=settings.app.org_name,
                language=language,
                switch_note=", unless the patient asks to switch between English and Arabic" ,
                who=who,
                first_name=cases.first_name(case["patient_name"]),
            )
        super().__init__(instructions=instructions)

    async def _call(self) -> dict:
        # Re-read every time: identity_confirmed is written by a tool.
        return await db().calls.find_one({"_id": self.call_id})

    # -- output guard -------------------------------------------------------

    async def tts_node(self, input, model_settings):
        async def guarded():
            buffer = ""

            def vet(raw: str) -> str:
                sentence = guard.sanitize_for_tts(raw)
                bad = guard.violations(sentence)
                if bad:
                    logger.error("GUARD BLOCKED %r (%s)", sentence, bad)
                    self.blocked.append(sentence)
                    if self.case_id:
                        asyncio.create_task(cases.log_event(self.case_id, "ai", "ai_reply_blocked", {"channel": "voice", "text": sentence, "patterns": bad}))
                    return BLOCKED_REPLACEMENT[self.lang]
                return sentence

            async for chunk in input:
                buffer += chunk
                # Arabic full stop and question mark too, or Arabic replies are
                # held until the very end of the turn.
                while (m := re.search(r"[.!?؟。]\s", buffer)) is not None:
                    sentence, buffer = buffer[: m.end()], buffer[m.end() :]
                    if sentence.strip():
                        yield vet(sentence)
            if buffer.strip():
                yield vet(buffer)

        async for frame in super().tts_node(guarded(), model_settings):
            yield frame

    # -- tools ---------------------------------------------------------------

    @function_tool()
    async def confirm_identity(self, ctx: RunContext, confirmed: bool) -> str:
        """Record whether the person confirmed they are the patient.

        Args:
            confirmed: True if they confirmed they are the patient.
        """
        return await voice_tools.confirm_identity(await self._call(), confirmed)

    @function_tool()
    async def explain_result(self, ctx: RunContext) -> str:
        """Get the approved explanation of the patient's result and next steps."""
        return await voice_tools.explain_result(await self._call())

    @function_tool()
    async def get_available_slots(self, ctx: RunContext) -> str:
        """Get follow-up appointment options to offer the patient."""
        return await voice_tools.get_available_slots(await self._call())

    @function_tool()
    async def book_slot(self, ctx: RunContext, option: int) -> str:
        """Book the appointment option the patient chose.

        Args:
            option: The option number they chose, 1, 2 or 3.
        """
        return await voice_tools.book_slot(await self._call(), option)

    @function_tool()
    async def request_human(self, ctx: RunContext, reason: str) -> str:
        """Hand over to a member of the care team, who will call back.

        Args:
            reason: Why, in the patient's words if possible.
        """
        return await voice_tools.request_human(await self._call(), reason)

    @function_tool()
    async def report_emergency(self, ctx: RunContext, symptoms: str) -> str:
        """The patient described possible emergency symptoms.

        Args:
            symptoms: What they described.
        """
        return await voice_tools.report_emergency(await self._call(), symptoms)

    @function_tool()
    async def record_decline(self, ctx: RunContext, reason: str) -> str:
        """The patient refuses follow-up after hearing why it matters.

        Args:
            reason: Their reason, if they gave one.
        """
        return await voice_tools.record_decline(await self._call(), reason)

    @function_tool()
    async def switch_language(self, ctx: RunContext, language: str) -> str:
        """Switch the call between English and Arabic when the patient asks.

        Args:
            language: "en" for English or "ar" for Arabic.
        """
        lang = "ar" if language.lower().startswith("ar") else "en"
        self.lang = lang
        self.session.tts.update_options(voice_id=settings.eleven.voice_ar if lang == "ar" else settings.eleven.voice_en, language=lang)
        if self.case_id:
            await cases.update_case(self.case_id, {"language": lang})
            await cases.log_event(self.case_id, "patient", "language_changed", {"to": lang, "channel": "voice"})
        return f"Switched. Continue the call in {'Arabic' if lang == 'ar' else 'English'}."

    @function_tool()
    async def end_call(self, ctx: RunContext, summary: str) -> str:
        """Call this before saying goodbye.

        Args:
            summary: One sentence describing what was agreed on this call.
        """
        return await voice_tools.end_call(await self._call(), summary)


def prewarm(proc: JobProcess) -> None:
    # Telephony-tuned: WhatsApp delivers narrowband Opus; the default 0.6
    # threshold clipped first syllables on the fraud agent's live calls.
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.4, activation_threshold=0.45)


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    meta = json.loads(ctx.job.metadata or "{}")
    call = await db().calls.find_one({"_id": meta.get("call_doc_id")}) if meta.get("call_doc_id") else None
    if call is None:
        # Console mode (`python -m ozicare.voice_agent console`): rehearse
        # against the newest open case without any telephony.
        case = await db().cases.find_one({"status": {"$in": list(cases.OPEN)}}, sort=[("created_at", -1)])
        call = await voice_tools.open_call(case, provider="livekit", direction="inbound", keys=[ctx.room.name])
    case = await cases.get_case(call["case_id"]) if call.get("case_id") else None
    lang = (case or {}).get("language") or meta.get("language") or "en"
    logger.info("CALL room=%s case=%s lang=%s", ctx.room.name, (case or {}).get("_id"), lang)

    vad = ctx.proc.userdata["vad"]
    session = AgentSession(
        vad=vad,
        allow_interruptions=True,
        min_interruption_duration=0.3,
        llm=openai.LLM(base_url=settings.llm.base_url, model=settings.llm.model, api_key=settings.llm.api_key),
        stt=_build_stt(lang, vad),
        tts=_build_tts(lang),
    )
    agent = CareAgent(call=call, case=case, lang=lang)

    @session.on("conversation_item_added")
    def _log_turn(ev) -> None:
        item = getattr(ev, "item", None)
        text = (getattr(item, "text_content", None) or "").strip()
        if not text or not call.get("case_id"):
            return
        direction = "inbound" if getattr(item, "role", "") == "user" else "outbound"
        asyncio.create_task(cases.log_message(call["case_id"], "voice", direction, text, meta={"call": call["_id"], "provider": "livekit"}, phone=call.get("phone")))

    try:
        await asyncio.wait_for(
            session.start(
                agent=agent,
                room=ctx.room,
                room_input_options=RoomInputOptions(audio_enabled=True, text_enabled=False),
                room_output_options=RoomOutputOptions(audio_enabled=True, transcription_enabled=True),
            ),
            timeout=45,
        )
    except asyncio.TimeoutError:
        logger.error("session.start() timed out: nothing joined %s — the WhatsApp leg was accepted but never bridged", ctx.room.name)
        return

    try:
        await asyncio.wait_for(ctx.wait_for_participant(), timeout=20)
    except asyncio.TimeoutError:
        logger.warning("No caller in the room after 20s; speaking anyway")

    first = cases.first_name((case or {}).get("patient_name", ""))
    if case is None:
        opening = "Hello, this is the automated assistant from {org}.".format(org=settings.app.org_name) if lang == "en" else f"مرحباً، معك المساعد الآلي من {settings.app.org_name}."
    elif lang == "ar":
        opening = f"مرحباً، معك المساعد الآلي من {settings.app.org_name}. هل أتحدث مع {first}؟"
    else:
        opening = f"Hello, this is the automated assistant from {settings.app.org_name}. Am I speaking with {first}?"
    await session.say(opening, allow_interruptions=True)

    async def _finish() -> None:
        current = await db().calls.find_one({"_id": call["_id"]})
        if current and current.get("status") == "active":
            await voice_tools.end_call(current, "(call ended without end_call)")
        if call.get("case_id"):
            from . import llm
            from .conversation import transcript

            summary = await llm.summarise(await transcript(call["case_id"]))
            await db().calls.update_one({"_id": call["_id"]}, {"$set": {"summary": summary, "blocked": agent.blocked}})
            await cases.log_event(call["case_id"], "system", "call_summary", {"call": call["_id"], "summary": summary})

    ctx.add_shutdown_callback(_finish)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name=settings.livekit.agent_name, num_idle_processes=1, port=settings.livekit.agent_http_port))
