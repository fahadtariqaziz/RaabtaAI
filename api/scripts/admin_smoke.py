"""Smoke of the Phase 5 admin API against a running demo server (AGENT_LLM=demo → no spend).

  uv run python -m scripts.admin_smoke --base http://localhost:8010

Seeded users (`app.cli seed`, dev password): owner/staff of abc-grammar-school + super@raabta.pk.
One line per check; exit 1 on the first failure. Covers: institution/settings/onboarding, metrics,
inbox (takeover → staff reply → widget poll → note → return to AI → AI replies again), leads (+CSV),
slots (single, bulk, patch, delete) + bookings, usage limits, audit log, KB playground (agent),
superadmin (tenants, impersonation grant + revoke, platform 403 for owners)."""

import argparse
import sys
import uuid
from typing import Any

import httpx

from scripts.widget_smoke import SmokeError, ok, read_sse

PASSWORD = "Raabta-demo-2027"  # noqa: S105 (dev seed password, app.cli.DEV_DEMO_PASSWORD)
SLUG = "abc-grammar-school"
OWNER = "owner@abc.demo.raabta.pk"
STAFF = "staff@abc.demo.raabta.pk"
SUPER = "super@raabta.pk"


def login(c: httpx.Client, email: str) -> dict[str, Any]:
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    ok(r.status_code == 200, f"login {email}", r.text)
    body: dict[str, Any] = r.json()
    return body


def headers_for(c: httpx.Client, email: str) -> tuple[dict[str, str], str]:
    body = login(c, email)
    inst = next(m["institution_id"] for m in body["memberships"] if m["institution_slug"] == SLUG)
    return {"Authorization": f"Bearer {body['access_token']}", "X-Institution": inst}, inst


def widget_turn(c: httpx.Client, sess: dict[str, Any], origin: str, text: str) -> list[Any]:
    h = {"Authorization": f"Bearer {sess['token']}", "Origin": origin}
    with c.stream(
        "POST",
        f"/api/v1/widget/sessions/{sess['session_id']}/messages",
        json={"text": text, "client_msg_id": uuid.uuid4().hex, "lang": "en"},
        headers=h,
        timeout=120,
    ) as r:
        ok(r.status_code == 200, f"widget turn '{text[:24]}'", r.status_code)
        return read_sse(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8010")
    args = ap.parse_args()
    origin = args.base
    c = httpx.Client(base_url=args.base, timeout=60)

    owner, inst_id = headers_for(c, OWNER)
    staff, _ = headers_for(c, STAFF)

    # institution / settings / onboarding (5.2, 5.8)
    r = c.get("/api/v1/institution", headers=owner)
    ok(r.status_code == 200 and r.json()["slug"] == SLUG, "GET /institution")
    r = c.patch("/api/v1/institution", json={"city": "Lahore"}, headers=staff)
    ok(r.status_code == 403, "staff cannot edit institution (403)", r.status_code)
    r = c.patch(
        "/api/v1/institution/settings",
        json={"escalation": {"keywords": ["complaint", "shikayat"]}},
        headers=owner,
    )
    ok(r.status_code == 200 and "shikayat" in r.json()["escalation"]["keywords"], "PATCH settings")
    r = c.patch(
        "/api/v1/institution/settings",
        json={"widget": {"allowed_origins": ["ftp://x"]}},
        headers=owner,
    )
    ok(r.status_code == 422, "invalid origin rejected (422)", r.status_code)
    r = c.post("/api/v1/institution/onboarding/profile", json={}, headers=owner)
    ok(r.status_code == 200 and "profile" in r.json()["completed"], "onboarding step saved")
    ok(r.json()["checklist"]["documents_ready"] >= 1, "onboarding checklist counts documents")

    # inbox flow via a real widget conversation (5.4 + I-18)
    s = c.post("/api/v1/widget/sessions", json={"slug": SLUG}, headers={"Origin": origin})
    ok(s.status_code == 201, "widget session", s.text)
    sess = s.json()
    wh = {"Authorization": f"Bearer {sess['token']}", "Origin": origin}
    evs = widget_turn(c, sess, origin, "What is the fee for Class 3?")
    ok(any(e == "message" for e, _ in evs), "AI answered in the widget")
    convs = c.get("/api/v1/conversations", params={"channel": "widget"}, headers=staff).json()
    conv = convs[0]
    ok(conv["mode"] == "ai" and conv["contact"]["id"], "inbox lists the widget conversation")
    cid = conv["id"]
    r = c.get(f"/api/v1/conversations/{cid}", headers=staff)
    ok(r.status_code == 200 and "bookings" in r.json(), "conversation detail")
    r = c.post(f"/api/v1/conversations/{cid}/takeover", headers=staff)
    ok(r.status_code == 200 and r.json()["mode"] == "human", "take over")
    evs = widget_turn(c, sess, origin, "Can I talk to a person?")
    ok(not any(e == "message" for e, _ in evs), "no AI reply while staff own the chat")
    ok(evs[-1][1].get("human") is True, "done event tells the widget a human owns the chat")
    r = c.post(
        f"/api/v1/conversations/{cid}/messages", json={"text": "Salam! Nadia here."}, headers=staff
    )
    ok(r.status_code == 201, "staff reply", r.text)
    up = c.get(f"/api/v1/widget/sessions/{sess['session_id']}/updates", headers=wh).json()
    ok(
        [m["text"] for m in up["messages"]] == ["Salam! Nadia here."],
        "widget poll gets staff reply",
    )
    r = c.post(f"/api/v1/conversations/{cid}/notes", json={"text": "VIP family"}, headers=staff)
    ok(r.status_code == 201, "internal note")
    up2 = c.get(
        f"/api/v1/widget/sessions/{sess['session_id']}/updates",
        params={"after": up["messages"][-1]["seq"]},
        headers=wh,
    ).json()
    ok(up2["messages"] == [], "notes never reach the widget")
    r = c.patch(f"/api/v1/conversations/{cid}", json={"flagged": True}, headers=staff)
    ok(r.status_code == 200 and r.json()["flagged"], "flag conversation")
    r = c.post(
        f"/api/v1/conversations/{cid}/return-to-ai",
        json={"note": "Promised a visit"},
        headers=staff,
    )
    ok(r.status_code == 200 and r.json()["mode"] == "ai", "return to AI", r.text)
    evs = widget_turn(c, sess, origin, "When can I visit?")
    ok(any(e == "message" for e, _ in evs), "AI replies again after return")
    msgs = c.get(f"/api/v1/conversations/{cid}/messages", headers=staff).json()
    ok(
        {(m["sender"], m["type"]) for m in msgs} >= {("staff", "text"), ("staff", "note")},
        "timeline",
    )
    with c.stream("GET", "/api/v1/conversations/events", headers=staff, timeout=10) as r:
        first = next(r.iter_lines())
        ok(r.status_code == 200 and first.startswith("event: ready"), "SSE events stream opens")

    # escalation keyword → human (5.8 settings take effect)
    s2 = c.post("/api/v1/widget/sessions", json={"slug": SLUG}, headers={"Origin": origin}).json()
    evs = widget_turn(c, s2, origin, "I have a complaint about the van")
    ok(evs[-1][1].get("status") == "escalated", "escalation keyword hands off to staff", evs[-1])

    # metrics (5.3)
    r = c.get("/api/v1/metrics/overview", params={"range": "7d"}, headers=staff)
    m = r.json()
    ok(r.status_code == 200 and m["kpis"]["conversations"] >= 2, "metrics overview", m.get("kpis"))
    ok(len(m["trend"]) == 7 and m["funnel"][0]["stage"] == "new", "trend + funnel")
    ok(any(a["kind"] == "flagged" and a["count"] >= 1 for a in m["attention"]), "needs attention")

    # leads (5.5)
    r = c.post(
        "/api/v1/leads", json={"student_name": "Ali", "phone": "0300 1234567"}, headers=staff
    )
    ok(r.status_code == 201 and r.json()["phone"].startswith("+92"), "create lead", r.text)
    lid = r.json()["id"]
    r = c.post("/api/v1/leads", json={"student_name": "X", "phone": "12"}, headers=staff)
    ok(r.status_code == 422, "bad phone rejected (422)")
    r = c.patch(f"/api/v1/leads/{lid}", json={"status": "contacted"}, headers=staff)
    ok(r.status_code == 200 and r.json()["status"] == "contacted", "move lead")
    r = c.get(f"/api/v1/leads/{lid}", headers=staff)
    ok(any("contacted" in t["text"] for t in r.json()["timeline"]), "lead timeline shows change")
    r = c.get("/api/v1/leads/export.csv", headers=staff)
    ok(r.status_code == 200 and "student_name" in r.text.splitlines()[0], "CSV export")

    # slots + bookings (5.6)
    bulk = {
        "kind": "test",
        "date_from": "2031-03-03",
        "date_to": "2031-03-09",
        "weekdays": ["mon", "wed"],
        "times": ["09:00", "11:00"],
        "duration_minutes": 45,
        "capacity": 2,
    }
    r = c.post("/api/v1/slots/bulk", json=bulk, headers=owner)
    ok(r.status_code == 201 and r.json()["created"] == 4, "bulk slots", r.text)
    r2 = c.post("/api/v1/slots/bulk", json=bulk, headers=owner)
    ok(r2.json() == {"created": 0, "skipped": 4}, "bulk is idempotent")
    slots = c.get(
        "/api/v1/slots",
        params={"from": "2031-03-03T00:00:00Z", "to": "2031-03-10T00:00:00Z"},
        headers=staff,
    ).json()
    ok(len(slots) == 4, "list slots in range")
    r = c.post(
        "/api/v1/slots",
        json={
            "kind": "visit",
            "starts_at": "2031-03-04T05:00:00Z",
            "ends_at": "2031-03-04T06:00:00Z",
            "capacity": 1,
        },
        headers=staff,
    )
    ok(r.status_code == 403, "staff cannot create slots (403)")
    r = c.patch(f"/api/v1/slots/{slots[0]['id']}", json={"capacity": 3}, headers=owner)
    ok(r.status_code == 200 and r.json()["capacity"] == 3, "edit slot")
    r = c.delete(f"/api/v1/slots/{slots[-1]['id']}", headers=owner)
    ok(r.status_code == 204, "delete empty slot")
    books = c.get("/api/v1/bookings", headers=staff).json()
    if books:
        r = c.patch(
            f"/api/v1/bookings/{books[0]['id']}", json={"status": "confirmed"}, headers=staff
        )
        ok(r.status_code in (200, 409), "confirm booking", r.text)
    else:
        print("  · no bookings in the demo data (skipped booking patch)")

    # usage + audit (5.10)
    r = c.get("/api/v1/usage/limits", headers=owner)
    ok(r.status_code == 200 and r.json()["seats"]["used"] >= 3, "usage limits")
    r = c.get("/api/v1/audit-log", params={"action": "conversation."}, headers=owner)
    acts = {a["action"] for a in r.json()}
    ok({"conversation.takeover", "conversation.return_to_ai"} <= acts, "audit has takeover/return")
    ok(all(a["actor_email"] for a in r.json()), "audit rows carry actor email")
    r = c.get("/api/v1/audit-log", headers=staff)
    ok(r.status_code == 403, "staff cannot read audit log (403)")

    # KB playground full agent run (5.7.4, demo LLM)
    r = c.post("/api/v1/kb/playground/agent", json={"query": "Class 3 fee?"}, headers=staff)
    ok(r.status_code == 200 and r.json()["reply"], "playground agent run", r.text[:200])
    convs = c.get("/api/v1/conversations", headers=staff).json()
    ok(
        all(not (x["contact"].get("name") or "").startswith("sandbox") for x in convs),
        "sandbox hidden",
    )

    # superadmin (5.9)
    sa = {"Authorization": f"Bearer {login(c, SUPER)['access_token']}"}
    r = c.get("/api/v1/superadmin/institutions", headers=sa)
    ok(r.status_code == 200 and any(t["slug"] == SLUG for t in r.json()), "tenants list")
    r = c.get("/api/v1/superadmin/institutions", headers=owner)
    ok(r.status_code == 403, "owner cannot use platform routes (403)")
    tenant_h = {**sa, "X-Institution": inst_id}
    ok(c.get("/api/v1/leads", headers=tenant_h).status_code == 403, "no tenant access before grant")
    r = c.post(f"/api/v1/superadmin/impersonate/{inst_id}", headers=sa)
    ok(r.status_code == 200, "impersonate")
    ok(
        c.get("/api/v1/leads", headers=tenant_h).status_code == 200,
        "tenant access while impersonating",
    )
    ok(c.delete(f"/api/v1/superadmin/impersonate/{inst_id}", headers=sa).status_code == 204, "stop")
    ok(c.get("/api/v1/leads", headers=tenant_h).status_code == 403, "access revoked after stop")
    slug = f"smoke-{uuid.uuid4().hex[:6]}"
    r = c.post(
        "/api/v1/superadmin/institutions",
        json={
            "slug": slug,
            "name": "Smoke School",
            "type": "school",
            "city": "Multan",
            "owner_email": f"{slug}@raabta-test.pk",
            "owner_name": "Owner",
        },
        headers=sa,
    )
    ok(
        r.status_code == 201 and "/invite/accept#token=" in (r.json()["owner_invite_url"] or ""),
        "create tenant + owner invite link",
        r.text,
    )
    print("ADMIN SMOKE: OK")


if __name__ == "__main__":
    try:
        main()
    except SmokeError as exc:
        print(f"  ✘ {exc}")
        sys.exit(1)
