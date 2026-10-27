"""
WhatsApp voice calls via LiveKit's connector — ported from
sahara-code-switch/whatsapp_connector.py, which is proven on live calls.

Kept from the original, because both cost real debugging time:
  - generated protobuf request objects, never hand-rolled JSON: LiveKit
    silently ignores unknown fields, so a misspelt field returns 200 "OK" and
    then never bridges media.
  - the SDP is a SessionDescription message, passed as a dict.

Inbound (patient taps the call button) is the main path: it works from every
country, including where Meta blocks business-initiated calls.
"""

from __future__ import annotations

import json
import logging
import secrets

from livekit import api

from . import cases
from .config import settings
from .voice_tools import add_call_key, open_call

logger = logging.getLogger("ozicare.wa_calls")


class CallError(Exception):
    pass


def _client() -> api.LiveKitAPI:
    return api.LiveKitAPI(settings.livekit.url, settings.livekit.api_key, settings.livekit.api_secret)


def _cloud_api_version() -> str:
    return settings.whatsapp.graph_version.lstrip("vV")


def _sdp(sdp: str, sdp_type: str) -> dict:
    return {"type": sdp_type, "sdp": sdp}


async def accept_inbound(*, call_id: str, from_number: str, sdp: str, sdp_type: str = "offer") -> dict:
    """
    The patient tapped "Talk to us". Find their case, open a call record, and
    accept the call with the agent dispatched into the room in the same RPC —
    no window where the patient is connected to an empty room.
    """
    phone = "+" + from_number.lstrip("+")
    case = await cases.active_case_for_phone(phone)
    call = await open_call(case, provider="livekit", direction="inbound", keys=[call_id], phone=phone)
    room = f"ozicare-{(case or {}).get('_id', 'nocase').lower()}-{secrets.token_hex(3)}"
    metadata = json.dumps({"call_doc_id": call["_id"], "case_id": (case or {}).get("_id"), "language": (case or {}).get("language", "en")})

    lk = _client()
    try:
        await lk.connector.accept_whatsapp_call(
            api.AcceptWhatsAppCallRequest(
                whatsapp_phone_number_id=settings.whatsapp.phone_number_id,
                whatsapp_api_key=settings.whatsapp.token,
                whatsapp_cloud_api_version=_cloud_api_version(),
                whatsapp_call_id=call_id,
                sdp=_sdp(sdp, sdp_type),
                room_name=room,
                agents=[api.RoomAgentDispatch(agent_name=settings.livekit.agent_name, metadata=metadata)],
                participant_identity=phone,
            )
        )
    except Exception as exc:
        logger.error("accept_whatsapp_call failed: %s", exc)
        raise CallError(f"could not accept call {call_id}: {exc}") from exc
    finally:
        await lk.aclose()

    logger.info("Accepted WhatsApp call %s into %s (case=%s)", call_id[-10:], room, (case or {}).get("_id"))
    return {"room": room, "call": call["_id"], "case_id": (case or {}).get("_id")}


async def dial_outbound(case: dict) -> dict:
    """
    Business-initiated WhatsApp call. Blocked by Meta for numbers registered in
    Nigeria, the USA, Canada, Egypt and Vietnam — use the call button there.
    """
    call = await open_call(case, provider="livekit", direction="outbound", keys=[], phone=case["phone"])
    room = f"ozicare-{case['_id'].lower()}-{secrets.token_hex(3)}"
    metadata = json.dumps({"call_doc_id": call["_id"], "case_id": case["_id"], "language": case["language"]})
    lk = _client()
    try:
        result = await lk.connector.dial_whatsapp_call(
            api.DialWhatsAppCallRequest(
                whatsapp_phone_number_id=settings.whatsapp.phone_number_id,
                whatsapp_to_phone_number=case["phone"].lstrip("+"),
                whatsapp_api_key=settings.whatsapp.token,
                whatsapp_cloud_api_version=_cloud_api_version(),
                room_name=room,
                agents=[api.RoomAgentDispatch(agent_name=settings.livekit.agent_name, metadata=metadata)],
                participant_identity=case["phone"],
            )
        )
    except Exception as exc:
        logger.error("dial_whatsapp_call failed: %s", exc)
        raise CallError(f"could not dial: {exc}") from exc
    finally:
        await lk.aclose()
    wa_call_id = getattr(result, "whatsapp_call_id", "") or ""
    if wa_call_id:
        await add_call_key(call["_id"], wa_call_id)
    return {"room": room, "call": call["_id"]}


async def connect_outbound(*, call_id: str, sdp: str, sdp_type: str = "answer") -> None:
    """Relay Meta's SDP answer so media flows on a call we dialled."""
    lk = _client()
    try:
        await lk.connector.connect_whatsapp_call(api.ConnectWhatsAppCallRequest(whatsapp_call_id=call_id, sdp=_sdp(sdp, sdp_type)))
    except Exception as exc:
        raise CallError(f"could not connect call {call_id}: {exc}") from exc
    finally:
        await lk.aclose()
