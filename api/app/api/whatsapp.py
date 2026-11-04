"""WhatsApp Cloud API webhook (step 6.2.1, PLAN §15.2, G12).

`GET` echoes `hub.challenge` when the verify token matches. `POST` checks
`X-Hub-Signature-256` over the raw body (403 on mismatch), stores each item in `webhook_events`
(unique per event id → duplicates are no-ops), enqueues `whatsapp_event_job` per new row and
returns 200 immediately — all processing happens in the worker."""

import json
import logging
import secrets

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.api.deps import RedisDep, SettingsDep
from app.channels.whatsapp.webhook import parse_payload, signature_valid
from app.services.whatsapp import record_events

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
MAX_BODY = 1_000_000


@router.get("", response_class=PlainTextResponse)
async def verify(
    settings: SettingsDep,
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
) -> str:
    expected = settings.meta_verify_token
    if (
        mode != "subscribe"
        or expected is None
        or not secrets.compare_digest(token.encode(), expected.get_secret_value().encode())
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "verification failed")
    return challenge


@router.post("")
async def receive(request: Request, settings: SettingsDep, redis: RedisDep) -> dict[str, int]:
    secret = settings.meta_app_secret
    if secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook not configured")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "payload too large")
    if not signature_valid(
        secret.get_secret_value(), raw, request.headers.get("x-hub-signature-256")
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid json") from None
    items = parse_payload(payload if isinstance(payload, dict) else {})
    new = await record_events(request.app.state.resources.sessionmaker, items)
    for event_id in new:
        await redis.enqueue_job("whatsapp_event_job", str(event_id))
    return {"received": len(items), "queued": len(new)}
