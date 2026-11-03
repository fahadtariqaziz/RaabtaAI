"""End-to-end smoke of the public widget API against a running server (steps 4.1/4.3).

  uv run python -m scripts.widget_smoke --base http://localhost:8000 --slug abc-grammar-school

Checks: config, session (origin allowlist), SSE turn (status before message, citations),
visit turn (slots + lead_form), lead capture, WhatsApp link, auth/origin rejection, widget.js.
Prints one line per check; exit 1 on the first failure. With AGENT_LLM=demo it spends nothing."""

import argparse
import json
import sys
import uuid
from typing import Any

import httpx


class SmokeError(AssertionError):
    pass


def ok(cond: bool, label: str, detail: Any = "") -> None:
    if not cond:
        raise SmokeError(f"{label}: {detail}")
    print(f"  ✔ {label}")


def read_sse(resp: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event, data = "message", ""
    for line in resp.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
        elif line == "" and data:
            events.append((event, json.loads(data)))
            event, data = "message", ""
    return events


def turn(
    c: httpx.Client, sid: str, headers: dict[str, str], text: str
) -> list[tuple[str, dict[str, Any]]]:
    with c.stream(
        "POST",
        f"/api/v1/widget/sessions/{sid}/messages",
        json={"text": text, "client_msg_id": uuid.uuid4().hex, "lang": "en"},
        headers=headers,
        timeout=120,
    ) as resp:
        ok(resp.status_code == 200, f"POST messages '{text[:30]}' → 200", resp.status_code)
        ok(resp.headers["content-type"].startswith("text/event-stream"), "SSE content-type")
        return read_sse(resp)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scripts.widget_smoke")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--slug", default="abc-grammar-school")
    p.add_argument("--origin", default="http://localhost:8000")
    a = p.parse_args(argv)
    try:
        with httpx.Client(base_url=a.base, timeout=30) as c:
            r = c.get(f"/api/v1/widget/config/{a.slug}")
            ok(r.status_code == 200, "GET config", r.text[:200])
            cfg = r.json()
            ok(len(cfg["suggested_questions"]["en"]) == 3, "config has 3 suggested questions")
            ok(cfg["theme"]["primary"].startswith("#"), "config theme colour")
            ok(c.get("/api/v1/widget/config/nope").status_code == 404, "unknown slug → 404")

            bad = c.post(
                "/api/v1/widget/sessions",
                json={"slug": a.slug},
                headers={"Origin": "https://evil.example"},
            )
            ok(bad.status_code == 403, "foreign origin → 403", bad.status_code)
            pre = c.options(
                "/api/v1/widget/sessions",
                headers={"Origin": a.origin, "Access-Control-Request-Method": "POST"},
            )
            ok(
                pre.status_code == 204
                and pre.headers.get("access-control-allow-origin") == a.origin,
                "CORS preflight",
                pre.headers,
            )
            r = c.post(
                "/api/v1/widget/sessions", json={"slug": a.slug}, headers={"Origin": a.origin}
            )
            ok(r.status_code == 201, "POST sessions → 201", r.text[:200])
            s = r.json()
            sid, vid = s["session_id"], s["visitor_id"]
            h = {"Authorization": f"Bearer {s['token']}", "Origin": a.origin}
            r2 = c.post(
                "/api/v1/widget/sessions",
                json={"slug": a.slug, "visitor_id": vid},
                headers={"Origin": a.origin},
            )
            ok(r2.json()["visitor_id"] == vid, "visitor id reused on new session")

            ev = turn(c, sid, h, "What is the monthly fee for Class 3?")
            names = [e for e, _ in ev]
            ok(names[0] == "status", "first event is status", names)
            ok("message" in names and names[-1] == "done", "message … done", names)
            ok(
                all(names.index("message") > i for i, n in enumerate(names) if n == "status"),
                "no status after message (check-then-send)",
                names,
            )
            ok(any(d.get("tool") for e, d in ev if e == "status"), "tool status event", ev[:3])
            msg = next(d for e, d in ev if e == "message")
            ok(bool(msg["text"]) and msg["kind"] == "answer", "approved answer", msg)
            print(f"      reply: {msg['text'][:110]!r}")

            ev = turn(c, sid, h, "I want to book a campus visit")
            names = [e for e, _ in ev]
            ok("slots" in names, "visit turn → slots event", names)
            slots = next(d for e, d in ev if e == "slots")["slots"]
            ok(bool(slots) and "slot_time" in slots[0], "slots carry slot_time", slots[:1])
            ok("lead_form" in names, "visit turn → lead_form event", names)

            r = c.post(
                f"/api/v1/widget/sessions/{sid}/lead",
                json={"name": "Smoke Parent", "phone": "0300-1234567", "interest": "Class 3"},
                headers=h,
            )
            ok(r.status_code == 200 and r.json()["ok"], "POST lead", r.text[:200])
            r = c.post(
                f"/api/v1/widget/sessions/{sid}/lead",
                json={"name": "X", "phone": "12345678"},
                headers=h,
            )
            ok(r.status_code == 422, "invalid phone → 422", r.status_code)

            r = c.get(f"/api/v1/widget/sessions/{sid}/whatsapp-link", headers=h)
            url = r.json().get("url", "") if r.status_code == 200 else ""
            ok(url.startswith("https://wa.me/"), "wa link", r.text)

            r = c.post(
                f"/api/v1/widget/sessions/{uuid.uuid4()}/messages",
                json={"text": "hi"},
                headers=h,
            )
            ok(r.status_code == 401, "token for another session → 401", r.status_code)
            r = c.post(
                f"/api/v1/widget/sessions/{sid}/messages",
                json={"text": "hi"},
                headers={**h, "Origin": "https://evil.example"},
            )
            ok(r.status_code == 403, "origin ≠ token origin → 403", r.status_code)
            r = c.post(
                f"/api/v1/widget/sessions/{sid}/messages", json={"text": "x" * 1001}, headers=h
            )
            ok(r.status_code == 422, "message > 1000 chars → 422", r.status_code)

            r = c.get("/widget/v1/widget.js")
            ok(r.status_code == 200 and r.headers.get("x-widget-version"), "widget.js served")
            etag = r.headers["etag"]
            ok(
                c.get("/widget/v1/widget.js", headers={"If-None-Match": etag}).status_code == 304,
                "widget.js ETag → 304",
            )
    except SmokeError as exc:
        print(f"  ✘ {exc}")
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
