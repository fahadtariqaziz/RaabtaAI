"""Phase 6 deterministic units: webhook signature + parsing, status ordering, 24h window,
WhatsApp composition, templates, policy gate (quiet hours / Jumma / caps), Graph client retries
and STT confidence parsing (httpx.MockTransport, no network)."""

import asyncio
import datetime as dt
import json
from typing import Any

import httpx
import pytest

from app.agent.guards import is_opt_out
from app.channels.stt.openai import OpenAISTT
from app.channels.whatsapp.client import WhatsAppClient, WhatsAppError
from app.channels.whatsapp.compose import compose, to_whatsapp_markup
from app.channels.whatsapp.policy import gate, quiet_until
from app.channels.whatsapp.templates import (
    DEFAULT_TEMPLATES,
    TemplateError,
    default_rows,
    positional_body,
    render,
    submit_payload,
    validate,
)
from app.channels.whatsapp.webhook import (
    InboundMessage,
    StatusUpdate,
    TemplateStatus,
    parse_payload,
    signature_valid,
    status_advances,
)
from app.channels.whatsapp.window import free_form_allowed
from app.models.templates import Template
from tests.channels import payloads as wp

PK = "Asia/Karachi"


def pk(y: int, mo: int, d: int, h: int, mi: int = 0) -> dt.datetime:
    from zoneinfo import ZoneInfo

    return dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PK)).astimezone(dt.UTC)


# --- webhook ---------------------------------------------------------------------------------


def test_signature() -> None:
    raw, headers = wp.signed(wp.text_msg("hi"), "s3cret")
    assert signature_valid("s3cret", raw, headers["X-Hub-Signature-256"])
    assert not signature_valid("other", raw, headers["X-Hub-Signature-256"])
    assert not signature_valid("s3cret", raw + b" ", headers["X-Hub-Signature-256"])
    assert not signature_valid("s3cret", raw, None)
    assert not signature_valid("s3cret", raw, "sha1=abc")


def test_parse_message_kinds() -> None:
    (m,) = parse_payload(wp.text_msg("Class 3 fee?"))
    assert isinstance(m, InboundMessage)
    assert (m.event_id, m.wa_id, m.name, m.kind, m.text) == (
        "wamid.TEXT1",
        wp.WA_ID,
        "Ayesha",
        "text",
        "Class 3 fee?",
    )
    (a,) = parse_payload(wp.audio_msg())
    assert isinstance(a, InboundMessage)
    assert (a.kind, a.media_id, a.text) == ("audio", "MEDIA123", None)
    assert a.mime_type == "audio/ogg; codecs=opus"
    (i,) = parse_payload(wp.interactive_msg("Book a visit"))
    assert isinstance(i, InboundMessage) and i.text == "Book a visit"
    (img,) = parse_payload(wp.image_msg(caption="fee slip"))
    assert isinstance(img, InboundMessage)
    assert (img.kind, img.text, img.media_id) == ("image", "fee slip", "MEDIAIMG")
    (loc,) = parse_payload(wp.location_msg())
    assert isinstance(loc, InboundMessage) and loc.text and "Gulberg" in loc.text


def test_parse_statuses_templates_and_junk() -> None:
    (s,) = parse_payload(wp.status_update("wamid.OUT1", "delivered"))
    assert isinstance(s, StatusUpdate)
    assert (s.event_id, s.status) == ("status:wamid.OUT1:delivered", "delivered")
    (t,) = parse_payload(wp.template_status("visit_reminder", "ur", "APPROVED"))
    assert isinstance(t, TemplateStatus)
    assert (t.waba_id, t.name, t.status, t.reason) == (wp.WABA, "visit_reminder", "APPROVED", None)
    assert parse_payload({"object": "page"}) == []
    assert (
        parse_payload({"object": "whatsapp_business_account", "entry": [None, {"changes": 3}]})
        == []
    )


def test_status_never_regresses() -> None:
    assert status_advances("queued", "sent")
    assert status_advances("sent", "read")
    assert not status_advances("read", "delivered")
    assert status_advances("sent", "failed")
    assert not status_advances("delivered", "failed")
    assert not status_advances("failed", "read")


# --- window / compose ------------------------------------------------------------------------


def test_window() -> None:
    now = dt.datetime(2026, 11, 4, 12, tzinfo=dt.UTC)
    assert free_form_allowed(now - dt.timedelta(hours=23), now)
    assert not free_form_allowed(now - dt.timedelta(hours=23, minutes=59), now)  # margin
    assert not free_form_allowed(now - dt.timedelta(hours=25), now)
    assert not free_form_allowed(None, now)


def test_compose_markup_split_and_buttons() -> None:
    md = (
        "## Fees\n**Class 3**: PKR 12,500\n\n"
        "| Item | Fee |\n|---|---|\n| Tuition | 12,500 |\n- one\n- two"
    )
    out = to_whatsapp_markup(md)
    assert "*Fees*" in out and "*Class 3*" in out and "**" not in out
    assert "Tuition · 12,500" in out and "|" not in out and "• one" in out
    long = ("Lorem ipsum dolor sit amet. " * 300).strip()
    assert all(len(p) <= 4096 for p in compose(long).parts) and len(compose(long).parts) > 1
    c = compose("Kya visit book karein?", ["Haan", "Nahi"])
    assert c.buttons == ["Haan", "Nahi"] and not c.list_rows
    c = compose("Choose", ["Campus visit on Saturday", "Entry test", "Counselling", "Fees"])
    assert not c.buttons and len(c.list_rows) == 4 and all(len(r) <= 24 for r in c.list_rows)


# --- templates -------------------------------------------------------------------------------


def _tpl(body: str, lang: str = "en") -> Template:
    variables = validate("visit_reminder", body)
    return Template(
        name="visit_reminder",
        language=lang,
        category="utility",
        body=body,
        variables=variables,
        examples=["Ayesha"],
    )


def test_template_render_and_payload() -> None:
    t = _tpl("Dear {{name}}, see you on {{date}} at {{place}}. Code {{code}}.")
    assert (
        positional_body(t.body, t.variables) == "Dear {{1}}, see you on {{2}} at {{3}}. Code {{4}}."
    )
    text, params = render(t, {"name": "Ayesha", "date": "Sat", "place": "Gulberg", "code": "X1"})
    assert text == "Dear Ayesha, see you on Sat at Gulberg. Code X1." and params[0] == "Ayesha"
    with pytest.raises(TemplateError):
        render(t, {"name": "Ayesha"})
    p = submit_payload(t)
    assert p["name"] == "visit_reminder" and p["language"] == "en" and p["category"] == "UTILITY"
    assert len(p["components"][0]["example"]["body_text"][0]) == 4
    ru = _tpl("Mohtaram {{name}}, kal visit hai.", "roman_ur")
    assert submit_payload(ru)["name"] == "visit_reminder_ru"
    assert submit_payload(ru)["language"] == "en"
    for bad in ("{{name}} hello", "hello {{name}}", "Hi {{Name}} there", ""):
        with pytest.raises(TemplateError):
            validate("ok_name", bad)
    with pytest.raises(TemplateError):
        validate("Bad-Name", "hello")


def test_default_templates_complete() -> None:
    rows = default_rows()
    names = {d.name for d in DEFAULT_TEMPLATES}
    assert len(names) == 11 and len(rows) == 33
    for r in rows:
        validate(r["name"], r["body"])  # every default passes Meta's basic rules
        assert len(r["examples"]) == len(r["variables"])
    by = {(r["name"], r["language"]): r for r in rows}
    for name in names:  # same variables in every language (order may differ: Urdu word order)
        assert (
            len({frozenset(by[(name, lang)]["variables"]) for lang in ("en", "ur", "roman_ur")})
            == 1
        )


# --- policy gate (G6/G7/G8) ------------------------------------------------------------------


def _gate(now: dt.datetime, **kw: Any) -> Any:
    base: dict[str, Any] = {
        "tz_name": PK,
        "quiet": {"start": "20:00", "end": "09:00"},
        "opted_out": False,
        "human_mode": False,
        "sent_last_7d": 0,
        "over_plan": False,
    }
    return gate(now, **(base | kw))


def test_policy_gate() -> None:
    wed_noon = pk(2026, 11, 4, 12)
    assert _gate(wed_noon).action == "send"
    assert _gate(wed_noon, opted_out=True).action == "cancel"
    assert _gate(wed_noon, human_mode=True).action == "cancel"
    assert _gate(wed_noon, over_plan=True).action == "hold"
    late = _gate(pk(2026, 11, 4, 22))
    assert late.action == "reschedule" and late.when == pk(2026, 11, 5, 9)
    early = _gate(pk(2026, 11, 5, 7))
    assert early.action == "reschedule" and early.when == pk(2026, 11, 5, 9)
    jumma = _gate(pk(2026, 11, 6, 13))  # Friday 1 pm
    assert jumma.action == "reschedule" and jumma.when == pk(2026, 11, 6, 14, 30)
    assert _gate(pk(2026, 11, 6, 15)).action == "send"
    assert (
        quiet_until(pk(2026, 11, 6, 13), PK, {"start": "20:00", "end": "09:00", "jumma": False})
        is None
    )
    capped = _gate(wed_noon, sent_last_7d=3)
    assert capped.action == "reschedule" and capped.when == wed_noon + dt.timedelta(days=1)


def test_opt_out_keywords() -> None:
    for t in ("STOP", "stop!", "band karo", "msg na karen", "بند کریں", "Unsubscribe please"):
        assert is_opt_out(t), t
    for t in (
        "bus stop kahan hai?",
        "fee kitni hai",
        "please don't stop the transport service now",
    ):
        assert not is_opt_out(t), t


# --- Graph client & STT over MockTransport ---------------------------------------------------


def test_client_retries_then_maps_errors() -> None:
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content or b"{}"))
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "rate", "code": 130429}})
        if calls[-1].get("to") == "bad":
            return httpx.Response(
                400, json={"error": {"message": "Re-engagement message", "code": 131047}}
            )
        return httpx.Response(200, json={"messages": [{"id": "wamid.OK"}]})

    async def go() -> None:
        c = WhatsAppClient("tok", transport=httpx.MockTransport(handler), backoff=0)
        res = await c.send_buttons(wp.PNID, wp.WA_ID, "Visit?", ["Haan", "Nahi"])
        assert res.wa_message_id == "wamid.OK" and len(calls) == 2
        assert calls[-1]["interactive"]["action"]["buttons"][1]["reply"]["title"] == "Nahi"
        with pytest.raises(WhatsAppError) as err:
            await c.send_text(wp.PNID, "bad", "hi")
        assert err.value.outside_window and not err.value.retryable
        await c.aclose()

    asyncio.run(go())


def test_openai_stt_confidence_and_fallback() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.content.decode(errors="ignore")
        model = (
            "gpt-4o-transcribe" if 'name="model"\r\n\r\ngpt-4o-transcribe' in body else "whisper-1"
        )
        seen.append(model)
        if model == "gpt-4o-transcribe" and len(seen) > 1:
            return httpx.Response(500)
        if model == "gpt-4o-transcribe":
            return httpx.Response(
                200,
                json={"text": "Fee kitni hai", "logprobs": [{"logprob": -0.05}, {"logprob": -0.1}]},
            )
        return httpx.Response(
            200,
            json={
                "text": "Fee",
                "language": "urdu",
                "segments": [{"avg_logprob": -2.0, "no_speech_prob": 0.5}],
            },
        )

    async def go() -> None:
        stt = OpenAISTT("k", transport=httpx.MockTransport(handler))
        good = await stt.transcribe(b"ogg", "audio/ogg; codecs=opus")
        assert (
            good.text == "Fee kitni hai"
            and good.confidence > 0.9
            and good.model == "gpt-4o-transcribe"
        )
        low = await stt.transcribe(b"ogg", "audio/ogg")  # primary 500 → whisper fallback
        assert low.model == "whisper-1" and low.confidence < 0.6
        await stt.aclose()

    asyncio.run(go())
