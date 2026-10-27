"""
Safety checks, both directions.

Outbound: every LLM reply (WhatsApp text and every sentence the voice agent is
about to speak) is checked before it leaves. A reply that diagnoses, doses, or
tells the patient to skip care is replaced with approved template text — the
same "vet before TTS" idea as the fraud agent's credential guard.

Inbound: patient text is scanned for emergency symptoms and for requests for a
human, so those paths never depend on the LLM classifying them correctly.

Regex, not a model, on purpose: the guard has to be deterministic and cheap
enough to run on every sentence of a live call.
"""

from __future__ import annotations

import re

# --- outbound: what the assistant must never say -------------------------

_FORBIDDEN_EN = [
    # Definitive diagnosis.
    r"\byou (definitely |certainly |clearly )?(have|got|are suffering from) (diabetes|cancer|hypertension|high blood pressure|hiv|an? (disease|infection|tumou?r))",
    r"\byou are (diabetic|hypertensive)\b",
    r"\b(this|it|your result) (means|confirms|shows) (that )?you have\b",
    r"\byou do not have (cancer|diabetes|hypertension)\b",
    # Dosing and prescribing.
    r"\b\d+(\.\d+)?\s?(mg|mcg|milligrams?|units?|ml|tablets?|pills?)\b",
    r"\b(take|start|increase|decrease|double|stop taking|begin) (your |the )?(medication|medicine|insulin|metformin|amlodipine|tablets?|pills?|dose)\b",
    r"\b(metformin|insulin|amlodipine|lisinopril|losartan|hydrochlorothiazide|aspirin|ibuprofen)\b",
    # Telling the patient to ignore care.
    r"\b(no need|don'?t need|do not need) (to )?(see|visit|go to) (a |the )?(doctor|clinic|clinician|hospital)\b",
    r"\b(ignore|skip) (the |your )?(result|follow[- ]?up|appointment|advice)\b",
    r"\bnothing to worry about\b",
]

_FORBIDDEN_AR = [
    r"(أنت|انت|لديك|عندك)\s*(مصاب|مريض)",
    r"لديك\s*(سكري|السكري|سرطان|السرطان|ضغط|ارتفاع ضغط)",
    r"(النتيجة|نتيجتك)\s*(تؤكد|تعني أن)\s*(لديك|عندك)",
    r"\d+\s*(ملغ|ملجم|مجم|ملغم|وحدة|وحدات|حبة|حبات|مل)\b",
    r"(تناول|خذ|ابدأ|توقف عن)\s*(الدواء|دواء|الأنسولين|انسولين|ميتفورمين|حبوب)",
    r"(لا داعي|لا حاجة)\s*(لزيارة|للذهاب|لمراجعة)\s*(الطبيب|العيادة|المستشفى)",
    r"(تجاهل|لا تهتم ب)\s*(النتيجة|المتابعة|الموعد)",
]

_FORBIDDEN = [re.compile(p, re.IGNORECASE) for p in _FORBIDDEN_EN + _FORBIDDEN_AR]


def violations(text: str) -> list[str]:
    """Return the patterns the text trips. Empty means safe to send."""
    return [p.pattern for p in _FORBIDDEN if p.search(text or "")]


def is_safe(text: str) -> bool:
    return not violations(text)


# --- inbound: what the patient says ---------------------------------------

_EMERGENCY_EN = [
    r"chest pain", r"pain in (my )?chest", r"can'?t breathe", r"cannot breathe", r"difficulty breathing",
    r"short(ness)? of breath", r"faint(ed|ing)?", r"passed out", r"unconscious", r"seizure", r"fits?\b",
    r"stroke", r"face (is )?drooping", r"can'?t move (my )?(arm|leg)", r"heavy bleeding", r"bleeding a lot",
    r"suicid", r"kill myself", r"want to die", r"severe (headache|pain)", r"worst headache",
]
_EMERGENCY_AR = [
    r"[أا]لم\s*(في\s*)?(ال|بال)صدر", r"وجع\s*(في\s*)?(ال|بال)صدر", r"لا أستطيع التنفس", r"لا استطيع التنفس", r"صعوبة (في )?التنفس",
    r"ضيق (في )?التنفس", r"إغماء", r"اغماء", r"أغمي علي", r"فقدت الوعي", r"تشنج", r"جلطة", r"نزيف (شديد|حاد|كثير)",
    r"انتحار", r"أريد أن أموت", r"اريد ان اموت", r"صداع شديد", r"ألم شديد",
]
_EMERGENCY = [re.compile(p, re.IGNORECASE) for p in _EMERGENCY_EN + _EMERGENCY_AR]

_HUMAN = re.compile(
    r"\b(human|person|agent|staff|nurse|doctor|someone real|real person|speak to (a|someone))\b|موظف|شخص|إنسان|انسان|ممرض|طبيب|دكتور",
    re.IGNORECASE,
)


def is_emergency(text: str) -> bool:
    return any(p.search(text or "") for p in _EMERGENCY)


def wants_human(text: str) -> bool:
    return bool(_HUMAN.search(text or ""))


# --- LLM output hygiene (verbatim from the fraud agent) -------------------


def strip_channel_tokens(text: str) -> str:
    """
    Remove the model's reasoning-channel markup.

    gemma-4 emits harmony-style control tokens, and on a live call the caller
    heard the agent say "channel thought channel ...". The real reply is
    whatever follows the last closing marker, so keep that and drop the
    scaffolding.
    """
    text = text or ""
    if "<|" in text or "|>" in text:
        tail = re.split(r"<\s*channel\s*\|\s*>", text)
        if len(tail) > 1:
            text = tail[-1]
        text = re.sub(r"<\s*\|\s*channel\s*>\s*\w*", " ", text)
        text = re.sub(r"<\s*\|[^>]*>", " ", text)
        text = re.sub(r"<[^<>|]*\|\s*>", " ", text)
    return text.strip()


def sanitize_for_tts(text: str) -> str:
    """Strip control tokens and markdown so the TTS does not read them aloud."""
    text = strip_channel_tokens(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*{1,3}|_{1,3}", "", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*[-*+•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
