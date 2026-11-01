# ADR 0001 — Free hosting: Netlify for frontends, separate free backend host

- Date: 2026-11-01 · Status: accepted (backend host to be picked in HANDOFF 9.1) · Supersedes: D-04 (Railway)

## Context
The user wants to deploy free at the end, on Netlify. RaabtaAI has two kinds of components:

| Component | Nature | Fits Netlify? |
|---|---|---|
| `admin/` (Next.js) | web app | **Yes** — Netlify supports Next.js |
| `widget/` (static JS file) | static asset | **Yes** — static hosting/CDN |
| `api/` (FastAPI) | always-on Python server; receives WhatsApp webhooks; holds DB/Redis connections | **No** — Netlify runs static sites and short-lived serverless functions, not a long-running Python server |
| `worker` (arq) | always-on background process: reminders, follow-ups, ingestion | **No** |
| Postgres + pgvector, Redis | stateful services | **No** |

## Decision
- Admin + widget → **Netlify** (free tier).
- API + worker + Postgres + Redis → a **separate free host**, chosen in step 9.1 from options such as
  an always-free cloud VM running our `docker-compose.yml`, or a free web-service host plus free managed
  Postgres (with pgvector) and Redis. Re-check current free-tier terms at that time.
- Requirement for the backend host: **must not sleep when idle** — Meta expects WhatsApp webhooks to be
  answered quickly, and reminders/follow-ups run on a schedule. Hosts that sleep after inactivity are
  acceptable only for demos.

## Consequences
- Admin calls the API cross-origin → API needs a CORS allowlist for the Netlify domain (step 5.1/9.1).
- Widget is served from Netlify's CDN; API keeps the origin allowlist per institution (PLAN §15.1).
- No code is coupled to a host: everything ships as Docker images + env vars.
