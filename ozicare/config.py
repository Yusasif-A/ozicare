"""
Central configuration for OziCare.

Everything is read from .env exactly once, here, so no other module touches
os.getenv. Same contract as the sahara/bimpe projects: override=True, because a
stale exported variable silently beating the file on disk has cost a live call
before.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

logger = logging.getLogger("ozicare.config")


def _env(key: str, default: str = "") -> str:
    # .env here has values written as KEY = "value", so strip stray quotes.
    return (os.getenv(key) or default).strip().strip('"').strip("'")


def _int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


@dataclass
class AppSettings:
    name: str = field(default_factory=lambda: _env("APP_NAME", "OziCare"))
    # The organisation the patient hears about. Kept separate from the product
    # name so "This is OziCare from OziCare" never happens.
    org_name: str = field(default_factory=lambda: _env("ORG_NAME", "City Health Screening Programme"))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL").rstrip("/"))
    dashboard_origin: str = field(default_factory=lambda: _env("DASHBOARD_ORIGIN", "http://localhost:3000"))
    jwt_secret: str = field(default_factory=lambda: _env("JWT_SECRET"))
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", "admin@ozicare.demo"))
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD"))
    # Bearer key a lab/EHR uses for POST /api/ingest.
    ingest_api_key: str = field(default_factory=lambda: _env("INGEST_API_KEY"))
    # Where escalations are sent on WhatsApp, in addition to the dashboard.
    escalation_phone: str = field(default_factory=lambda: _env("ESCALATION_PHONE"))


@dataclass
class MongoSettings:
    uri: str = field(default_factory=lambda: _env("MONGO_URI"))
    db: str = field(default_factory=lambda: _env("MONGO_DB", "ozicare"))


@dataclass
class LLMSettings:
    base_url: str = field(default_factory=lambda: _env("GEMMA_BASE_URL").rstrip("/"))
    model: str = field(default_factory=lambda: _env("GEMMA_MODEL", "google/gemma-4-E26B-it"))
    api_key: str = field(default_factory=lambda: _env("API_KEY", "none"))


@dataclass
class ElevenLabsSettings:
    # Paid key first: the free tier's quota has run out mid-call before.
    api_key: str = field(
        default_factory=lambda: _env("PAID_ELEVENLABS_API_KEY") or _env("FREE_ELEVENLABS_API_KEY")
    )
    # Flash v2.5 measured ~0.4s to first byte warm, and speaks Arabic. Breeze was
    # dropped at ~11s to first byte per sentence.
    tts_model: str = field(default_factory=lambda: _env("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5"))
    voice_en: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_EN", "EXAVITQu4vr4xnSDxMaL"))
    voice_ar: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE_AR", "EXAVITQu4vr4xnSDxMaL"))
    stt_model: str = field(default_factory=lambda: _env("ELEVENLABS_STT_MODEL", "scribe_v1"))


@dataclass
class WhatsAppSettings:
    token: str = field(default_factory=lambda: _env("WHATSAPP_TOKEN"))
    phone_number_id: str = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID"))
    verify_token: str = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN"))
    graph_version: str = field(default_factory=lambda: _env("WHATSAPP_GRAPH_VERSION", "v23.0"))
    # Approved template for first contact outside the 24h window. Without one,
    # first contact only reaches patients who messaged us in the last 24 hours.
    template_en: str = field(default_factory=lambda: _env("WHATSAPP_TEMPLATE_EN"))
    template_ar: str = field(default_factory=lambda: _env("WHATSAPP_TEMPLATE_AR"))
    # Log sends instead of calling Meta: rehearse the demo without texting anyone.
    dry_run: bool = field(default_factory=lambda: _env("WHATSAPP_DRY_RUN").lower() in {"1", "true", "yes"})

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_version}/{self.phone_number_id}"

    @property
    def configured(self) -> bool:
        return bool(self.token and self.phone_number_id) and not self.dry_run


@dataclass
class LiveKitSettings:
    url: str = field(default_factory=lambda: _env("LIVEKIT_URL"))
    api_key: str = field(default_factory=lambda: _env("LIVEKIT_API_KEY"))
    api_secret: str = field(default_factory=lambda: _env("LIVEKIT_API_SECRET"))
    agent_name: str = field(default_factory=lambda: _env("LIVEKIT_AGENT_NAME", "ozicare-voice"))
    # The voice agent worker's health server.
    agent_http_port: int = field(default_factory=lambda: _int("AGENT_HTTP_PORT", 8091))

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key and self.api_secret)


@dataclass
class BimpeSettings:
    api_key: str = field(default_factory=lambda: _env("BIMPEAI_API_KEY"))
    base_url: str = field(default_factory=lambda: _env("BIMPEAI_BASE_URL"))
    agent_id: str = field(default_factory=lambda: _env("BIMPEAI_AGENT_ID"))
    tool_token: str = field(default_factory=lambda: _env("BIMPEAI_TOOL_TOKEN"))
    # True places real calls; anything else uses Bimpe test telephony.
    live: bool = field(default_factory=lambda: _env("BIMPEAI_CALL_LIVE").lower() in {"1", "true", "yes"})
    # Test only: ring this number instead of the patient's. Never in production.
    demo_phone: str = field(default_factory=lambda: _env("BIMPEAI_DEMO_PHONE"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.agent_id)


@dataclass
class SLASettings:
    """
    Minutes, per urgency. Short by default so the demo shows the loop moving;
    set the env vars to real programme values for a pilot.
    """

    urgent_contact_min: int = field(default_factory=lambda: _int("SLA_URGENT_CONTACT_MIN", 5))
    urgent_ack_min: int = field(default_factory=lambda: _int("SLA_URGENT_ACK_MIN", 10))
    soon_contact_min: int = field(default_factory=lambda: _int("SLA_SOON_CONTACT_MIN", 60))
    soon_ack_min: int = field(default_factory=lambda: _int("SLA_SOON_ACK_MIN", 24 * 60))
    routine_contact_min: int = field(default_factory=lambda: _int("SLA_ROUTINE_CONTACT_MIN", 240))
    routine_ack_min: int = field(default_factory=lambda: _int("SLA_ROUTINE_ACK_MIN", 72 * 60))
    # Reminders before a case is closed as lost to follow-up.
    max_attempts: int = field(default_factory=lambda: _int("SLA_MAX_ATTEMPTS", 3))
    tick_seconds: int = field(default_factory=lambda: _int("SCHEDULER_TICK_SECONDS", 30))


@dataclass
class Settings:
    app: AppSettings = field(default_factory=AppSettings)
    mongo: MongoSettings = field(default_factory=MongoSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    eleven: ElevenLabsSettings = field(default_factory=ElevenLabsSettings)
    whatsapp: WhatsAppSettings = field(default_factory=WhatsAppSettings)
    livekit: LiveKitSettings = field(default_factory=LiveKitSettings)
    bimpe: BimpeSettings = field(default_factory=BimpeSettings)
    sla: SLASettings = field(default_factory=SLASettings)

    def validate(self) -> list[str]:
        problems = []
        if not self.mongo.uri:
            problems.append("MONGO_URI is not set")
        if not self.app.jwt_secret:
            problems.append("JWT_SECRET is not set; staff login will refuse every request")
        if not self.llm.base_url:
            problems.append("GEMMA_BASE_URL is not set; free-text questions fall back to templates")
        if not self.whatsapp.configured:
            problems.append("WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID missing; WhatsApp sends are logged only")
        if not self.eleven.api_key:
            problems.append("No ElevenLabs key; the LiveKit voice agent cannot speak or listen")
        if not self.bimpe.configured:
            problems.append("BIMPEAI_API_KEY / BIMPEAI_AGENT_ID missing; phone calls are disabled")
        if self.bimpe.configured and not self.bimpe.tool_token:
            problems.append("BIMPEAI_TOOL_TOKEN missing; /tools/* refuses every Bimpe request")
        return problems

    def log_summary(self) -> None:
        logger.info(
            "OziCare: org=%s whatsapp=%s livekit=%s bimpe=%s(live=%s) llm=%s",
            self.app.org_name,
            "on" if self.whatsapp.configured else "off",
            "on" if self.livekit.configured else "off",
            "on" if self.bimpe.configured else "off",
            self.bimpe.live,
            self.llm.model,
        )


settings = Settings()
