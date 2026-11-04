"""Webhook payloads in the shapes Meta sends (WhatsApp Cloud API docs, v23)."""

import hashlib
import hmac
import json
from typing import Any

PNID = "106540352242922"
WABA = "102290129340398"
WA_ID = "923001234567"


def envelope(
    value: dict[str, Any], field: str = "messages", entry_id: str = WABA
) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": entry_id, "changes": [{"value": value, "field": field}]}],
    }


def _value(messages: list[dict[str, Any]], name: str = "Ayesha") -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550783881", "phone_number_id": PNID},
        "contacts": [{"profile": {"name": name}, "wa_id": WA_ID}],
        "messages": messages,
    }


def text_msg(body: str, wamid: str = "wamid.TEXT1", ts: str = "1762230000") -> dict[str, Any]:
    return envelope(
        _value(
            [{"from": WA_ID, "id": wamid, "timestamp": ts, "type": "text", "text": {"body": body}}]
        )
    )


def audio_msg(wamid: str = "wamid.AUDIO1", media_id: str = "MEDIA123") -> dict[str, Any]:
    return envelope(
        _value(
            [
                {
                    "from": WA_ID,
                    "id": wamid,
                    "timestamp": "1762230000",
                    "type": "audio",
                    "audio": {"mime_type": "audio/ogg; codecs=opus", "id": media_id, "voice": True},
                }
            ]
        )
    )


def image_msg(wamid: str = "wamid.IMG1", caption: str | None = None) -> dict[str, Any]:
    image: dict[str, Any] = {"mime_type": "image/jpeg", "id": "MEDIAIMG", "sha256": "x"}
    if caption:
        image["caption"] = caption
    return envelope(
        _value([{"from": WA_ID, "id": wamid, "timestamp": "1", "type": "image", "image": image}])
    )


def interactive_msg(title: str, wamid: str = "wamid.INT1") -> dict[str, Any]:
    return envelope(
        _value(
            [
                {
                    "from": WA_ID,
                    "id": wamid,
                    "timestamp": "1",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "qr0", "title": title},
                    },
                }
            ]
        )
    )


def location_msg() -> dict[str, Any]:
    loc = {"latitude": 31.52, "longitude": 74.35, "name": "Gulberg", "address": "Lahore"}
    return envelope(
        _value(
            [
                {
                    "from": WA_ID,
                    "id": "wamid.LOC1",
                    "timestamp": "1",
                    "type": "location",
                    "location": loc,
                }
            ]
        )
    )


def status_update(
    wamid: str, status: str, errors: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    st: dict[str, Any] = {
        "id": wamid,
        "status": status,
        "timestamp": "1762230100",
        "recipient_id": WA_ID,
    }
    if errors:
        st["errors"] = errors
    return envelope(
        {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550783881", "phone_number_id": PNID},
            "statuses": [st],
        }
    )


def template_status(
    name: str, language: str, event: str, tid: str = "594425479261596"
) -> dict[str, Any]:
    return envelope(
        {
            "event": event,
            "message_template_id": tid,
            "message_template_name": name,
            "message_template_language": language,
            "reason": "NONE" if event != "REJECTED" else "INVALID_FORMAT",
        },
        field="message_template_status_update",
    )


def signed(payload: dict[str, Any], secret: str) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": f"sha256={sig}", "Content-Type": "application/json"}
