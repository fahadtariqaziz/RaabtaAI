# RaabtaAI

AI admissions & fee-recovery assistant for Pakistani schools, colleges and universities —
answers enquiries 24/7 in English, Urdu and Roman Urdu on the institution's website and WhatsApp.

- Design: [`docs/PLAN.md`](docs/PLAN.md) · Progress: [`HANDOFF.md`](HANDOFF.md) · Agent rules: [`CLAUDE.md`](CLAUDE.md)

## Quickstart (dev)

Requirements: Python 3.13 + [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, Docker.

```bash
cp .env.example .env      # fill in keys locally; never commit .env
make install
make lint test build
make verify               # runs verification scripts of completed steps
cd api && uv run uvicorn app.main:app --reload   # http://localhost:8000/healthz
```

| Workspace | What |
|---|---|
| `api/` | FastAPI + LangGraph backend (Python) |
| `admin/` | Next.js admin panel for institutions |
| `widget/` | Embeddable website chat widget (vanilla TS) |
