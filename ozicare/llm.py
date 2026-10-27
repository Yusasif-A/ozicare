"""
The only two things the LLM is trusted with: answering a free-text question
from approved knowledge, and summarising a conversation for staff.

Every reply is logged and passed through guard.violations() before use; a reply
that fails is discarded for approved template text, and the failure is recorded
on the case so staff can see the model tried something it should not have.
"""

from __future__ import annotations

import logging

import httpx

from . import content, guard
from .config import settings

logger = logging.getLogger("ozicare.llm")

ANSWER_PROMPT = """\
You are the patient messaging assistant for {org}, a health screening programme. \
You are an automated assistant, not a clinician, and you say so if asked.

The patient had a screening test and the result needs follow-up. You help them \
understand what that means in plain language and get to the next step.

STRICT RULES — never break these:
- Use ONLY the facts in APPROVED KNOWLEDGE below. If the answer is not there, say \
you cannot answer that here and that a member of the care team can.
- Never say or imply the patient has a disease, or that they definitely do not.
- Never mention medicine names, doses, or tell them to start, stop or change any medicine.
- Never tell them they do not need to see a clinician, or to ignore their result.
- Never ask for information you do not need (no ID numbers, no passwords, no payment).
- If they describe emergency symptoms, tell them to go to emergency care now.
- Reply in {language}. Two to four short sentences. Plain text, no markdown, no lists.
- End by offering the next step: they can reply 2 to book or 3 for a call.

APPROVED KNOWLEDGE:
{knowledge}
"""

SUMMARY_PROMPT = """\
Summarise this patient conversation for a clinician picking up the case. Plain \
English, at most 5 short lines: why the patient was contacted, what they asked \
or said, any symptoms mentioned, what they agreed to, and what the staff member \
should do next. Do not add facts that are not in the conversation.
"""

LANG_NAMES = {"en": "English", "ar": "Arabic (Modern Standard Arabic)"}


async def _chat(messages: list[dict], *, max_tokens: int = 300, temperature: float = 0.2) -> str:
    if not settings.llm.base_url:
        raise RuntimeError("GEMMA_BASE_URL is not set")
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            f"{settings.llm.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm.api_key}"},
            json={
                "model": settings.llm.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"] or ""
    return guard.strip_channel_tokens(raw)


async def answer_question(
    question: str,
    *,
    lang: str,
    screening_type: str,
    result_summary: str,
    history: list[dict] | None = None,
) -> tuple[str | None, dict]:
    """
    Returns (reply or None, audit). None means "use the template fallback":
    the model was unreachable, or its reply failed the guard.
    """
    system = ANSWER_PROMPT.format(
        org=settings.app.org_name,
        language=LANG_NAMES.get(lang, "English"),
        knowledge=content.knowledge_for_llm(screening_type, lang, result_summary),
    )
    messages = [{"role": "system", "content": system}]
    for turn in (history or [])[-6:]:
        messages.append(turn)
    messages.append({"role": "user", "content": question})

    audit: dict = {"model": settings.llm.model, "question": question}
    try:
        reply = await _chat(messages)
    except Exception as exc:  # noqa: BLE001 - any failure means "use the template"
        logger.warning("LLM unavailable: %s", exc)
        audit["error"] = str(exc)[:300]
        return None, audit

    audit["raw_reply"] = reply
    bad = guard.violations(reply)
    if bad or not reply:
        logger.warning("LLM reply blocked by guard: %s", bad)
        audit["blocked"] = bad or ["empty"]
        return None, audit
    return reply, audit


async def summarise(transcript: str) -> str:
    """Handoff summary for staff. Falls back to the raw tail if the model is down."""
    try:
        return await _chat(
            [{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": transcript[-6000:]}],
            max_tokens=250,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Summary unavailable: %s", exc)
        return "(automatic summary unavailable) Last messages:\n" + transcript[-800:]
