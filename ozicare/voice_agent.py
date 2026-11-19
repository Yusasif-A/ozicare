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
so. You never claim to be a nurse or doctor. You are warm, calm and patient.

LANGUAGE: speak {language} for the whole call. Do not change language because \
of a word you did not catch or a noisy line. Only call switch_language if the \
patient clearly asks, in words, to speak {other}.

{who}

IF YOU DID NOT CATCH WHAT THEY SAID: say so kindly and ask them to repeat, in \
{language}. Never guess, and never change language because of it.

HOW THE CALL GOES (this is the post-screening follow-up)
1. Greet them, say you are the automated assistant from {org}, and ask if you \
are speaking with {first_name}. Say NOTHING about the screening until they confirm.
2. Call confirm_identity with their answer.
3. Call explain_result. Explain, a little at a time: what the screening found \
and that it is not a diagnosis; why the follow-up visit matters; where they \
have been referred. Check they follow before moving on.
4. Book: if nothing is booked yet, call get_available_slots, read the options \
and call book_slot with the number they choose. If already booked, confirm the \
time still works.
5. Prepare them: what to bring, and that a reminder comes the day before. \
Mention the warning signs once.
6. Ask if they have any questions, and answer them.
7. Call end_call with a one-sentence summary and say goodbye.
Steps are a guide, not a script: if they ask something at any point, answer it, \
then carry on from where you were.

ANSWERING QUESTIONS: be genuinely helpful. You may explain, in plain general \
terms, what the screening test is, what the result type usually means, what the \
follow-up visit or test involves and how to prepare, why follow-up matters, and \
anything about the appointment, the clinic or their referral. Use what the tools \
told you first, and general, widely accepted health information for the rest.
You may not: say they have or do not have a disease, give their personal \
chances or a prognosis, name a medicine or dose, or tell them to change or stop \
treatment. For those, say kindly that the clinician will go through it with them \
at the visit, then keep helping. Call request_human only when they ask for a \
person, or when they are worried and want to talk to someone now.

NEVER tell them to skip follow-up. NEVER ask for ID numbers, passwords or \
payment details.

Emergency symptoms (chest pain, trouble breathing, fainting, heavy bleeding, \
stroke signs, self-harm): call report_emergency immediately.
They clearly refuse follow-up after hearing why it matters: call record_decline.

This is a phone call: short sentences, one question at a time, no lists, no \
symbols, no markdown.
"""

# After the visit: the same assistant and rules, a different call.
CHECKIN_STEPS = """\
HOW THE CALL GOES (this is the recovery check-in after their visit)
1. Greet them, say you are the automated assistant from {org}, and ask if you \
are speaking with {first_name}. Say NOTHING about their health until they confirm.
2. Call confirm_identity with their answer.
Keep this call SHORT: short sentences, one question at a time, no long explanations.
3. Call get_care_plan. Ask how they have been feeling since the visit. Wait.
4. In ONE question, ask if they have had any of the warning signs (name them \
briefly). Wait.
5. Call record_checkin with their answers (following_plan true unless they say \
otherwise). If they report any warning sign, tell them a clinician will call them today.
6. In one sentence, say what is next (the first next step only), and ask if \
they have any questions.
7. Call end_call with a one-sentence summary and say goodbye.
Steps are a guide, not a script: if they ask something at any point, answer it, \
then carry on from where you were.

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
        # per Arabic utterance. Only the call's own language: a secondary
        # language let a mumbled English word come back as Arabic, and the
        # agent then switched language on its own. Keyterms: batch Scribe heard
        # "OziCare" as "Wally McIver" on the Arabic test clip.
        return elevenlabs.STT(
            api_key=settings.eleven.api_key,
            model="scribe_v2_realtime",
            language_code=code,
            keyterms=[settings.app.name, settings.app.org_name[:50], "cervical", "colposcopy", "HbA1c", "Mariam"],
            # Without server VAD the plugin uses manual commits: a transcript is
            # only finalised when the turn times out, which added ~3s of dead
            # air to every reply on a live call. Let Scribe commit on silence.
            server_vad={
                "vad_silence_threshold_secs": 0.6,
                "vad_threshold": 0.4,
                "min_speech_duration_ms": 120,
                "min_silence_duration_ms": 300,
            },
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
            fmt = INSTRUCTIONS
            if case.get("care_plan") and case["status"] in ("follow_up", "escalated"):
                fmt = fmt[: fmt.index("HOW THE CALL GOES")] + CHECKIN_STEPS + fmt[fmt.index("ANSWERING QUESTIONS") :]
            instructions = fmt.format(
                org=settings.app.org_name,
                language=language,
                other="English" if lang == "ar" else "Arabic",
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
    async def switch_language(self, ctx: RunContext, language: str, patient_request: str) -> str:
        """Switch the call between English and Arabic, ONLY when the patient
        clearly asks in words to change language. Never because you could not
        understand them.

        Args:
            language: "en" for English or "ar" for Arabic.
            patient_request: The patient's exact words asking to switch.
        """
        lang = "ar" if language.lower().startswith("ar") else "en"
        asked = (patient_request or "").lower()
        if lang == self.lang:
            return f"You are already speaking {'Arabic' if lang == 'ar' else 'English'}. Carry on."
        asks_for = ("arab", "عرب", "english", "انجليزي", "إنجليزي", "الإنجليزية", "language", "لغة")
        if not any(w in asked for w in asks_for):
            return (
                f"Do not switch. The patient did not ask to change language. Keep speaking "
                f"{'Arabic' if self.lang == 'ar' else 'English'}, and if you did not understand them, ask them to repeat."
            )
        self.lang = lang
        self.session.tts.update_options(voice_id=settings.eleven.voice_ar if lang == "ar" else settings.eleven.voice_en, language=lang)
        # The recogniser has to listen for the new language too.
        if hasattr(self.session.stt, "update_options"):
            self.session.stt.update_options(secondary_languages=[lang])
        if self.case_id:
            # Logged, but the case keeps its language: WhatsApp messages and the
            # booking confirmation stay in the language the patient chose.
            await cases.log_event(self.case_id, "patient", "language_changed", {"to": lang, "channel": "voice", "words": patient_request[:120]})
        return f"Switched. Continue the call in {'Arabic' if lang == 'ar' else 'English'}."

    @function_tool()
    async def get_care_plan(self, ctx: RunContext) -> str:
        """Get the patient's care plan after their visit, and where each next step is."""
        return await voice_tools.get_care_plan(await self._call())

    @function_tool()
    async def record_checkin(self, ctx: RunContext, feeling: str, following_plan: bool, warning_signs: str = "", notes: str = "") -> str:
        """Record the recovery check-in answers.

        Args:
            feeling: How they feel since the visit, in a few words.
            following_plan: True if they have been able to follow the care plan.
            warning_signs: Any warning signs they report; empty if none.
            notes: Anything else the care team should know.
        """
        return await voice_tools.record_checkin(await self._call(), feeling, following_plan, warning_signs, notes)

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
        # Short endpointing so the agent answers as soon as the patient stops,
        # and the LLM starts on the transcript before the turn is confirmed.
        turn_handling={
            "endpointing": {"min_delay": 0.3, "max_delay": 1.5},
            "interruption": {"enabled": True, "min_duration": 0.3},
            "preemptive_generation": {"enabled": True},
        },
        # Thinking off: Gemma's reasoning channel adds latency and leaks
        # "<|channel>thought" markup into the reply on a phone call.
        llm=openai.LLM(
            base_url=settings.llm.base_url,
            model=settings.llm.model,
            api_key=settings.llm.api_key,
            temperature=0.3,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        ),
        stt=_build_stt(lang, vad),
        tts=_build_tts(lang),
    )
    agent = CareAgent(call=call, case=case, lang=lang)

    @session.on("conversation_item_added")
    def _log_turn(ev) -> None:
        item = getattr(ev, "item", None)
        direction = "inbound" if getattr(item, "role", "") == "user" else "outbound"
        text = (getattr(item, "text_content", None) or "").strip()
        if direction == "outbound":
            # What was spoken, not the model's reasoning-channel markup.
            text = guard.sanitize_for_tts(text)
        if not text or not call.get("case_id"):
            return
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
