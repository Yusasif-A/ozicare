"""
WhatsApp Cloud API: sending, and parsing Meta's webhook.

Transport only — no case logic. conversation.py decides what to say; this
module says it. Adapted from sahara-code-switch/whatsapp_connector.py, keeping
its two hard-won rules:

  - every interactive send falls back to plain text: the button is a
    convenience, a message that never arrives is a failure.
  - every raw webhook is logged: a silently ignored payload looks exactly like
    a broken one.

Without WHATSAPP_TOKEN the module runs dry: sends are logged and return a fake
id, so the dashboard and the demo still work on a laptop with no Meta number.
"""

from __future__ import annotations

import logging
import secrets

import httpx

from .config import settings

logger = logging.getLogger("ozicare.whatsapp")

BUTTON_TITLE_MAX = 20  # Meta rejects reply-button titles longer than this.


class WhatsAppError(Exception):
    pass


def wa_id(phone_e164: str) -> str:
    """Meta wants the number without the leading +."""
    return phone_e164.lstrip("+")


def _mask(number: str) -> str:
    return f"***{number[-4:]}" if number else "***"


async def _post(payload: dict) -> tuple[int, dict]:
    if not settings.whatsapp.configured:
        fake = f"dry-{secrets.token_hex(6)}"
        logger.info("[dry-run] WhatsApp %s to %s", payload.get("type"), _mask(payload.get("to", "")))
        return 200, {"messages": [{"id": fake}], "dry_run": True}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{settings.whatsapp.graph_url}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp.token}"},
            json={"messaging_product": "whatsapp", "recipient_type": "individual", **payload},
        )
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:500]}
    return r.status_code, body


def _message_id(body: dict) -> str | None:
    msgs = body.get("messages") or []
    return msgs[0].get("id") if msgs else None


async def send_text(to: str, text: str) -> str:
    status, body = await _post({"to": wa_id(to), "type": "text", "text": {"body": text, "preview_url": True}})
    if status not in (200, 201):
        logger.error("WhatsApp text to %s failed %s: %s", _mask(to), status, body)
        raise WhatsAppError(_error_text(body))
    return _message_id(body) or ""


async def send_buttons(to: str, text: str, buttons: list[tuple[str, str]]) -> str:
    """
    Up to three reply buttons as (id, title). Falls back to the plain text if
    Meta refuses the interactive message — the text already lists the options.
    """
    payload = {
        "to": wa_id(to),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:BUTTON_TITLE_MAX]}}
                    for bid, title in buttons[:3]
                ]
            },
        },
    }
    status, body = await _post(payload)
    if status in (200, 201):
        return _message_id(body) or ""
    logger.warning("Buttons refused (%s), sending plain text: %s", status, str(body)[:300])
    return await send_text(to, text)


async def send_call_button(to: str, text: str, label: str, ttl_minutes: int = 60 * 24) -> str:
    """
    A message with WhatsApp's voice_call button: one tap rings our number, and
    the call lands on the LiveKit agent. Patient-initiated, so it also works
    where Meta blocks business-initiated calls (e.g. Nigerian numbers).
    """
    payload = {
        "to": wa_id(to),
        "type": "interactive",
        "interactive": {
            "type": "voice_call",
            "body": {"text": text},
            "action": {"name": "voice_call", "parameters": {"display_text": label[:BUTTON_TITLE_MAX], "ttl_minutes": ttl_minutes}},
        },
    }
    status, body = await _post(payload)
    if status in (200, 201):
        return _message_id(body) or ""
    logger.warning("Call button refused (%s), sending plain text: %s", status, str(body)[:300])
    return await send_text(to, text)


async def send_template(to: str, name: str, lang: str, body_params: list[str]) -> str:
    """
    First contact outside the 24-hour window. Meta only delivers business-
    initiated messages from an approved template, so this is the path a real
    deployment uses for "patient receives WhatsApp within 1 minute".
    """
    payload = {
        "to": wa_id(to),
        "type": "template",
        "template": {
            "name": name,
            "language": {"code": "ar" if lang == "ar" else "en"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]}],
        },
    }
    status, body = await _post(payload)
    if status not in (200, 201):
        logger.error("Template %s to %s failed %s: %s", name, _mask(to), status, body)
        raise WhatsAppError(_error_text(body))
    return _message_id(body) or ""


def _error_text(body: dict) -> str:
    err = body.get("error") or {}
    code = err.get("code")
    msg = err.get("message") or str(body)[:300]
    if code == 131047:
        # The one everybody hits: free-form text outside the 24h service window.
        return f"{msg} (outside the 24h window — needs an approved template, or the patient must message first)"
    return f"{code}: {msg}" if code else msg


# --------------------------------------------------------------------------
# Webhook parsing
# --------------------------------------------------------------------------


def parse_messages(body: dict) -> list[dict]:
    """
    Inbound patient messages, flattened. Button taps come back with the button
    id as `button_id` and its title as `text`, so the router can treat a tap
    and a typed reply the same way.
    """
    out: list[dict] = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            value = change.get("value", {})
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):
                kind = m.get("type")
                text, button_id = "", None
                if kind == "text":
                    text = (m.get("text") or {}).get("body", "")
                elif kind == "interactive":
                    inter = m.get("interactive") or {}
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    button_id, text = reply.get("id"), reply.get("title", "")
                elif kind == "button":
                    # Quick-reply button on a template message.
                    btn = m.get("button") or {}
                    button_id, text = btn.get("payload"), btn.get("text", "")
                else:
                    text = f"[{kind} message]"
                out.append(
                    {
                        "from": "+" + m.get("from", "").lstrip("+"),
                        "id": m.get("id"),
                        "type": kind,
                        "text": text.strip(),
                        "button_id": button_id,
                        "profile_name": names.get(m.get("from")),
                    }
                )
    return out


def parse_statuses(body: dict) -> list[dict]:
    """Delivery receipts: sent / delivered / read / failed."""
    out: list[dict] = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            for s in change.get("value", {}).get("statuses", []):
                out.append(
                    {
                        "id": s.get("id"),
                        "status": s.get("status"),
                        "recipient": s.get("recipient_id"),
                        "errors": s.get("errors"),
                    }
                )
    return out


def parse_call_events(body: dict) -> list[dict]:
    """Meta `calls` webhook events (verbatim shape from sahara: SDP at calls[].session.sdp)."""
    events: list[dict] = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "calls":
                continue
            for call in change.get("value", {}).get("calls", []):
                session = call.get("session") or {}
                events.append(
                    {
                        "call_id": call.get("id"),
                        "event": call.get("event"),
                        "direction": call.get("direction"),
                        "from": call.get("from"),
                        "to": call.get("to"),
                        "status": call.get("status"),
                        "sdp": session.get("sdp"),
                        "sdp_type": session.get("sdp_type"),
                    }
                )
    return events
