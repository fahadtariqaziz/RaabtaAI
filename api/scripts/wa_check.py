"""Live WhatsApp Cloud API checks (step 6.1 / 6.3 verification — needs the Meta token).

    uv run python -m scripts.wa_check                       # number + display name + quality
    uv run python -m scripts.wa_check --webhook https://<public-host>/api/v1/webhooks/whatsapp
    uv run python -m scripts.wa_check --send-test 923001234567   # one text (inside 24h window)
    uv run python -m scripts.wa_check --templates           # templates on the WABA + statuses

`--send-test` only reaches a number that messaged the business in the last 24 hours (or a test
number added in the Meta dashboard)."""

import argparse
import asyncio
import secrets
import sys

import httpx

from app.channels.whatsapp.client import WhatsAppClient, WhatsAppError
from app.core.config import get_settings


async def main(args: argparse.Namespace) -> int:
    s = get_settings()
    client = WhatsAppClient(s.require("meta_access_token"))
    pnid = s.require("meta_phone_number_id")
    ok = True
    try:
        info = await client.phone_number(pnid)
        print(
            f"✔ number {info.get('display_phone_number')} · name "
            f"{info.get('verified_name')!r} · quality {info.get('quality_rating')}"
        )
        if args.templates:
            waba = s.require("meta_waba_id")
            for t in await client.list_templates(waba):
                print(f"  {t.get('name'):28} {t.get('language'):6} {t.get('status')}")
        if args.send_test:
            res = await client.send_text(pnid, args.send_test, "RaabtaAI test message ✅")
            print(f"✔ sent test message {res.wa_message_id} → check the phone")
    except WhatsAppError as exc:
        print(f"✘ Graph API: {exc} (code {exc.code}, HTTP {exc.status})")
        ok = False
    finally:
        await client.aclose()
    if args.webhook:
        challenge = secrets.token_hex(4)
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(
                args.webhook,
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": s.require("meta_verify_token"),
                    "hub.challenge": challenge,
                },
            )
        if r.status_code == 200 and r.text == challenge:
            print(f"✔ webhook verify round-trip via {args.webhook}")
        else:
            print(f"✘ webhook verify: HTTP {r.status_code} {r.text[:80]!r}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--webhook")
    ap.add_argument("--send-test", metavar="WA_ID")
    ap.add_argument("--templates", action="store_true")
    sys.exit(asyncio.run(main(ap.parse_args())))
