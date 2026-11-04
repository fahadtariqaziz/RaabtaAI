"""WhatsApp webhook: signature check and payload parsing (step 6.2, PLAN §15.2 Webhook, G12).

`parse_payload` turns Meta's nested `entry[].changes[].value` into flat, typed events — one per
inbound message, status update or template status change — each with a stable `event_id` used for
`webhook_events` idempotency. Unknown shapes are skipped, never raised."""

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Literal

STATUS_ORDER = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
MESSAGE_KINDS = (
    "text",
    "audio",
    "voice",
    "image",
    "document",
    "interactive",
    "button",
    "location",
)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def signature_valid(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """`X-Hub-Signature-256: sha256=<hex HMAC of the raw body with the app secret>`."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass
class InboundMessage:
    event_id: str  # = wa message id
    phone_number_id: str
    wa_id: str
    name: str | None
    kind: str  # text | audio | image | document | interactive | button | location | other
    text: str | None = None
    media_id: str | None = None
    mime_type: str | None = None
    filename: str | None = None
    timestamp: int | None = None
    kind_tag: Literal["message"] = "message"


@dataclass
class StatusUpdate:
    event_id: str  # f"status:{wamid}:{status}"
    phone_number_id: str
    wa_message_id: str
    status: str  # sent | delivered | read | failed
    errors: list[dict[str, Any]] = field(default_factory=list)
    kind_tag: Literal["status"] = "status"


@dataclass
class TemplateStatus:
    event_id: str
    waba_id: str
    template_id: str | None
    name: str | None
    language: str | None
    status: str  # APPROVED | REJECTED | PAUSED | DISABLED | PENDING ...
    reason: str | None
    kind_tag: Literal["template_status"] = "template_status"


WebhookItem = InboundMessage | StatusUpdate | TemplateStatus


def _message_text(m: dict[str, Any]) -> tuple[str, str | None]:
    kind = str(m.get("type") or "other")
    if kind == "text":
        return kind, (m.get("text") or {}).get("body")
    if kind == "button":  # quick-reply button of a template
        b = m.get("button") or {}
        return kind, b.get("text") or b.get("payload")
    if kind == "interactive":
        it = m.get("interactive") or {}
        reply = it.get("button_reply") or it.get("list_reply") or {}
        return kind, reply.get("title")
    if kind == "location":
        loc = m.get("location") or {}
        label = loc.get("name") or loc.get("address") or ""
        return kind, f"[location] {label} ({loc.get('latitude')}, {loc.get('longitude')})".strip()
    if kind in ("image", "document", "video", "sticker"):
        return kind, (m.get(kind) or {}).get("caption")
    if kind in ("audio", "voice"):
        return "audio", None
    return "other", None


def _inbound(value: dict[str, Any], pnid: str) -> list[InboundMessage]:
    names = {
        c.get("wa_id"): (c.get("profile") or {}).get("name")
        for c in _list(value.get("contacts"))
        if isinstance(c, dict)
    }
    out = []
    for m in _list(value.get("messages")):
        if not isinstance(m, dict) or not m.get("id") or not m.get("from"):
            continue
        kind, text = _message_text(m)
        media = m.get(str(m.get("type"))) if kind in ("audio", "image", "document") else None
        media = media if isinstance(media, dict) else {}
        ts = m.get("timestamp")
        out.append(
            InboundMessage(
                event_id=str(m["id"]),
                phone_number_id=pnid,
                wa_id=str(m["from"]),
                name=names.get(m["from"]),
                kind=kind,
                text=text.strip() if isinstance(text, str) and text.strip() else None,
                media_id=media.get("id"),
                mime_type=media.get("mime_type"),
                filename=media.get("filename"),
                timestamp=int(ts) if isinstance(ts, str) and ts.isdigit() else None,
            )
        )
    return out


def _statuses(value: dict[str, Any], pnid: str) -> list[StatusUpdate]:
    out = []
    for s in _list(value.get("statuses")):
        if not isinstance(s, dict) or not s.get("id") or not s.get("status"):
            continue
        out.append(
            StatusUpdate(
                event_id=f"status:{s['id']}:{s['status']}",
                phone_number_id=pnid,
                wa_message_id=str(s["id"]),
                status=str(s["status"]),
                errors=[e for e in s.get("errors") or [] if isinstance(e, dict)],
            )
        )
    return out


def _template_status(value: dict[str, Any], waba_id: str) -> TemplateStatus | None:
    event = value.get("event")
    if not isinstance(event, str):
        return None
    tid = value.get("message_template_id")
    return TemplateStatus(
        event_id=f"tpl:{tid}:{event}:{value.get('reason') or ''}"[:128],
        waba_id=waba_id,
        template_id=str(tid) if tid is not None else None,
        name=value.get("message_template_name"),
        language=value.get("message_template_language"),
        status=event.upper(),
        reason=value.get("reason") if value.get("reason") not in (None, "NONE") else None,
    )


def parse_payload(payload: dict[str, Any]) -> list[WebhookItem]:
    if payload.get("object") != "whatsapp_business_account":
        return []
    items: list[WebhookItem] = []
    entries = payload.get("entry")
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        for change in changes if isinstance(changes, list) else []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            field_name = change.get("field")
            if field_name == "messages":
                pnid = str((value.get("metadata") or {}).get("phone_number_id") or "")
                if not pnid:
                    continue
                items.extend(_inbound(value, pnid))
                items.extend(_statuses(value, pnid))
            elif field_name == "message_template_status_update":
                tpl = _template_status(value, str(entry.get("id") or ""))
                if tpl is not None:
                    items.append(tpl)
    return items


def status_advances(current: str, new: str) -> bool:
    """Status webhooks can arrive out of order: never regress read → delivered. `failed` always
    wins over queued/sent (Meta can fail a message after accepting it)."""
    if new == "failed":
        return current in ("queued", "sent")
    if current == "failed":
        return False
    return STATUS_ORDER.get(new, -1) > STATUS_ORDER.get(current, -1)
