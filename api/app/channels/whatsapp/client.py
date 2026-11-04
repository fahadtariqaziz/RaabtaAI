"""Graph API client for WhatsApp Cloud API (step 6.3.1, PLAN §15.2 Outbound).

Retries 429/5xx and transport errors with exponential backoff; everything else maps to a typed
`WhatsAppError` carrying Meta's error code (e.g. 131047 = outside the 24h window). The transport
is injectable so tests run against `httpx.MockTransport` (no network)."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings

log = logging.getLogger(__name__)

GRAPH_VERSION = "v23.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
MAX_ATTEMPTS = 4
OUTSIDE_WINDOW_CODES = {131047}  # "Re-engagement message" — free-form after 24h
RATE_LIMIT_CODES = {4, 80007, 130429, 131048, 131056}
MEDIA_MAX_BYTES = 16 * 1024 * 1024  # WhatsApp audio/image limit


class WhatsAppError(RuntimeError):
    """A Graph API call failed. `retryable` = worth re-queueing later (rate limit / 5xx)."""

    def __init__(self, message: str, *, code: int | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status

    @property
    def retryable(self) -> bool:
        return (self.status is not None and (self.status == 429 or self.status >= 500)) or (
            self.code in RATE_LIMIT_CODES
        )

    @property
    def outside_window(self) -> bool:
        return self.code in OUTSIDE_WINDOW_CODES


@dataclass(frozen=True)
class SendResult:
    wa_message_id: str


def _error(resp: httpx.Response) -> WhatsAppError:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    # Meta messages never contain the access token; keep them short for the messages table.
    msg = str(err.get("message") or resp.reason_phrase or "Graph API error")[:300]
    code = err.get("code")
    return WhatsAppError(msg, code=code if isinstance(code, int) else None, status=resp.status_code)


class WhatsAppClient:
    def __init__(
        self,
        access_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = GRAPH_BASE,
        backoff: float = 0.5,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=httpx.Timeout(15.0, connect=5.0),
            transport=transport,
        )
        self._backoff = backoff

    @classmethod
    def from_settings(cls, settings: Settings) -> "WhatsAppClient":
        return cls(settings.require("meta_access_token"))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                resp = await self._http.request(method, url, **kw)
            except httpx.TransportError as exc:
                last = WhatsAppError(f"transport error: {type(exc).__name__}", status=None)
                retry = True
            else:
                if resp.is_success:
                    return resp
                last = _error(resp)
                retry = last.retryable
            if not retry or attempt == MAX_ATTEMPTS - 1:
                break
            delay = self._backoff * 2**attempt
            log.warning("graph api retry %s %s in %.1fs", method, url.split("?")[0], delay)
            await asyncio.sleep(delay)
        raise last or WhatsAppError("graph api request failed")

    async def _json(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        data = (await self._request(method, url, **kw)).json()
        return data if isinstance(data, dict) else {}

    # --- messages -------------------------------------------------------------------------

    async def _send(self, phone_number_id: str, to: str, payload: dict[str, Any]) -> SendResult:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to}
        data = await self._json("POST", f"/{phone_number_id}/messages", json=body | payload)
        msgs = data.get("messages") or [{}]
        wamid = msgs[0].get("id")
        if not isinstance(wamid, str):
            raise WhatsAppError("send response without a message id")
        return SendResult(wa_message_id=wamid)

    async def send_text(self, phone_number_id: str, to: str, text: str) -> SendResult:
        return await self._send(
            phone_number_id, to, {"type": "text", "text": {"body": text, "preview_url": False}}
        )

    async def send_buttons(
        self, phone_number_id: str, to: str, text: str, buttons: list[str]
    ) -> SendResult:
        """Reply buttons (≤ 3, title ≤ 20 chars); the tap comes back as an `interactive` message
        whose title is the button text."""
        interactive = {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"qr{i}", "title": b}}
                    for i, b in enumerate(buttons[:3])
                ]
            },
        }
        return await self._send(
            phone_number_id, to, {"type": "interactive", "interactive": interactive}
        )

    async def send_list(
        self, phone_number_id: str, to: str, text: str, button: str, rows: list[str]
    ) -> SendResult:
        interactive = {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": button[:20],
                "sections": [
                    {
                        "title": button[:24],
                        "rows": [{"id": f"r{i}", "title": r[:24]} for i, r in enumerate(rows[:10])],
                    }
                ],
            },
        }
        return await self._send(
            phone_number_id, to, {"type": "interactive", "interactive": interactive}
        )

    async def send_template(
        self,
        phone_number_id: str,
        to: str,
        name: str,
        language: str,
        body_params: list[str],
    ) -> SendResult:
        template: dict[str, Any] = {"name": name, "language": {"code": language}}
        if body_params:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in body_params],
                }
            ]
        return await self._send(phone_number_id, to, {"type": "template", "template": template})

    async def send_image(
        self, phone_number_id: str, to: str, link: str, caption: str | None = None
    ) -> SendResult:
        image: dict[str, Any] = {"link": link}
        if caption:
            image["caption"] = caption
        return await self._send(phone_number_id, to, {"type": "image", "image": image})

    async def mark_read(self, phone_number_id: str, wa_message_id: str) -> None:
        await self._json(
            "POST",
            f"/{phone_number_id}/messages",
            json={"messaging_product": "whatsapp", "status": "read", "message_id": wa_message_id},
        )

    # --- media (step 6.4.1) -----------------------------------------------------------------

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """`GET /{media_id}` → short-lived URL → bytes (same bearer token) → (bytes, mime)."""
        meta = await self._json("GET", f"/{media_id}")
        url, mime = meta.get("url"), str(meta.get("mime_type") or "application/octet-stream")
        size = meta.get("file_size")
        if not isinstance(url, str):
            raise WhatsAppError("media lookup without a url")
        if isinstance(size, int) and size > MEDIA_MAX_BYTES:
            raise WhatsAppError("media too large")
        resp = await self._request("GET", url)
        if len(resp.content) > MEDIA_MAX_BYTES:
            raise WhatsAppError("media too large")
        return resp.content, mime

    # --- numbers & templates (steps 6.1, 6.5.2) ----------------------------------------------

    async def phone_number(self, phone_number_id: str) -> dict[str, Any]:
        return await self._json(
            "GET",
            f"/{phone_number_id}",
            params={"fields": "display_phone_number,verified_name,quality_rating"},
        )

    async def create_template(self, waba_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._json("POST", f"/{waba_id}/message_templates", json=payload)

    async def list_templates(self, waba_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        url: str | None = f"/{waba_id}/message_templates"
        params: dict[str, Any] | None = {
            "fields": "id,name,language,status,category,rejected_reason",
            "limit": 100,
        }
        while url:
            data = await self._json("GET", url, params=params)
            out.extend(d for d in data.get("data", []) if isinstance(d, dict))
            nxt = (data.get("paging") or {}).get("next")
            url, params = (nxt, None) if isinstance(nxt, str) else (None, None)
        return out
