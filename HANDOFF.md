# RaabtaAI — HANDOFF (living execution tracker)

> **Every session reads this file first and updates it last.** Reference design: `docs/PLAN.md` (read only the §
> a step points to). Rules: `CLAUDE.md`. Claude never commits/pushes — each step ends with a one-line commit message
> for the user.

---

## §0 Current status / Next action

| Field | Value |
|---|---|
| Phase / step in progress | **Phase 0 · Step 0.3** (config, model registry, logging) — not started |
| Last completed step | 0.2 docker-compose & dev scripts (2026-11-01) |
| Last verification run | `bash scripts/verify/p0_s2.sh` → `VERIFY p0_s2: OK` (12/12), p0_s1 re-run OK (2026-11-01) |
| Next action | Start 0.3: `app/core/config.py` (pydantic-settings, fail-fast), `models_registry.py` with **D-12 hybrid keys `agent_simple`/`agent_complex`**, structlog + request_id, `/readyz`; write + run `p0_s3.sh` |
| Blocked on user | 0.6 user tasks can start in parallel now: Meta business verification, API keys (see §7 user queue) |
| Open decisions needing user confirmation | D-05 pricing (recompute after 3.9 evals with hybrid), D-01 embeddings, D-02 STT, D-03 WhatsApp number model, D-04 deploy target (see §5) |

---

## §1 How a new session starts (protocol)

1. Read **§0** of this file and the block for the **current step** in §3 (not the whole file).
2. Read `CLAUDE.md` (short).
3. Read only the `docs/PLAN.md` section(s) the step cites (`PLAN §N`). Use `grep -n "^## §N" docs/PLAN.md` to find offsets; don't read the whole plan.
4. Run the verification script of the **last completed step** (`scripts/verify/pN_sM.sh`). Green → continue. Red → fix first and log it in §6.
5. Do the step's sub-steps in order; mark each `◐` then `☑` here as you go.
6. Create the step's verify script, run it. If it cannot run (needs Meta account, API spend approval, browser check), **tell the user the exact command(s) to run and the expected output** and mark the step `◐ (awaiting user verification)`.
7. End of step / session: update §0, statuses in §3, append a §4 session-log row, add §5/§6 entries, and give the user the suggested commit message (`type(scope): message`, ≤ 72 chars).
8. Context efficiency: never `cat` large files; use `grep`/`sed -n`; read PLAN sections by number; summaries over dumps; don't re-read files you just edited.

Status legend: `☐` not started · `◐` in progress · `☑` done · `👤` needs the user (account, key/spend approval, visual check).

Verify-script conventions: `scripts/verify/pN_sM.sh` sources `scripts/verify/_lib.sh`, runs checks (pytest paths/markers, builds, curl), prints `VERIFY pN_sM: OK` and exits 0, or prints the failing check and exits 1. `scripts/verify/all.sh` runs every script of completed steps (fast subset, no live LLM).

---

## §2 Phase overview

| Phase | Goal | Steps | Status |
|---|---|---|---|
| 0 Foundations | scaffold, tooling, compose, config, CI, Meta kickoff | 0.0–0.6 (7) | ◐ (0.0 ☑) |
| 1 Data & multi-tenancy | models, migrations, RLS, auth/RBAC, seeds, isolation tests | 1.1–1.7 (7) | ☐ |
| 2 Knowledge base | ingestion, chunking, embeddings, hybrid search, facts, citations | 2.1–2.8 (8) | ☐ |
| 3 Agent core + evals | Claude wrapper, prompts, skills, tools, graph, guards, context, eval harness, CLI | 3.1–3.10 (10) | ☐ |
| 4 Widget + chat API | public chat API (SSE), widget bundle, booking/lead UI, embed tests | 4.1–4.4 (4) | ☐ |
| 5 Admin panel | Next.js foundation, onboarding, dashboard, inbox, leads, slots, KB, settings, super-admin, audit/usage, quality pass | 5.1–5.11 (11) | ☐ |
| 6 WhatsApp | Meta app, webhook, sender + 24h window, voice notes, templates, handoff, follow-ups, channel guards | 6.1–6.8 (8) | ☐ |
| 7 Fee recovery | data/import, identity, sequences, fee agent, receipts, fee UI, fee evals | 7.1–7.7 (7) | ☐ |
| 8 Hardening | security, observability, cost/limits, load, backups, privacy/compliance, docs | 8.1–8.7 (7) | ☐ |
| 9 Pilot launch kit | deploy, staging/prod, onboarding runbook, demo script, pilot ops | 9.1–9.5 (5) | ☐ |

Ordering rationale: KB (2) precedes agent (3) because grounding depends on retrieval + facts; widget (4) precedes admin (5) so there is a demo-able product early and the inbox has real conversations to show; WhatsApp (6) after admin because human takeover must exist before real parents are on WhatsApp and Meta verification (kicked off in 0.6) takes weeks; fees (7) after WhatsApp since reminders are template-driven.

---

## §3 Phases → steps → sub-steps

### Phase 0 — Foundations

#### 0.0 Planning docs — ☑ (2026-11-01)
- Files: `docs/PLAN.md`, `HANDOFF.md`, `CLAUDE.md`
- Verify: files exist. Commit: `docs: add build plan, handoff tracker and CLAUDE.md`

#### 0.1 Repo scaffold & tooling — ☑ (2026-11-01)
- PLAN §3, §4
- Sub-steps:
  - 0.1.1 ☑ `api/`: `uv init`, `pyproject.toml` (python 3.13; deps: fastapi, uvicorn, pydantic, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, redis, arq, anthropic, langgraph, langgraph-checkpoint-postgres, httpx, structlog, python-multipart, argon2-cffi, pyjwt; dev: ruff, mypy, pytest, pytest-asyncio, testcontainers, freezegun, hypothesis), `app/main.py` with `/healthz`, ruff + mypy config (strict-ish), pytest config with markers `evals`, `live`, `isolation`
  - 0.1.2 ☑ `admin/`: `pnpm create next-app` (App Router, TS, Tailwind, ESLint), add shadcn/ui init, prettier, `pnpm-workspace.yaml` at root
  - 0.1.3 ☑ `widget/`: `package.json`, esbuild config, `src/index.ts` placeholder that mounts a Shadow DOM root, size-check script
  - 0.1.4 ☑ root: `Makefile` (`dev`, `test`, `lint`, `verify`), `.editorconfig`, `.gitignore`, `.env.example`, `scripts/verify/_lib.sh`, `README.md` quickstart
- Files: as above
- Acceptance: `uv run pytest` passes a trivial test; `uv run ruff check` and `mypy` clean; `pnpm -C admin build` succeeds; `pnpm -C widget build` emits `dist/widget.js`
- Verify: `scripts/verify/p0_s1.sh` — runs ruff, mypy, pytest, both pnpm builds, checks `_lib.sh` exists
- Commit: `chore: scaffold api, admin and widget workspaces`
- Done notes: `api/` is a non-packaged uv app (`[tool.uv] package=false`), package `app/`, mypy strict, pytest default excludes `live`/`evals` markers. `admin/` = Next.js 16.4 + React 19.3 + Tailwind 4 + shadcn (style base-nova); **`admin/AGENTS.md` (from Next) says Next 16 differs from training data — read `admin/node_modules/next/dist/docs/` before admin code**; `typecheck` runs `next typegen` first (needed for global `LayoutProps`). shadcn `rtl:false` for now → enable in 5.1 for Urdu. `widget/` esbuild IIFE + gzip size check. Installed `anthropic` SDK is **2.x** — read the claude-api skill before writing 3.1.

#### 0.2 docker-compose & dev scripts — ☑ (2026-11-01)
- PLAN §2, §22
- Sub-steps:
  - 0.2.1 ☑ `docker-compose.yml`: postgres (`pgvector/pgvector:pg16`), redis, api, worker, admin; volumes; healthchecks
  - 0.2.2 ☑ `infra/Dockerfile.api`, `Dockerfile.worker`, `Dockerfile.admin` (multi-stage)
  - 0.2.3 ☑ `scripts/dev.sh` (compose up db/redis, run api+worker with reload, admin dev server); `make dev`
  - 0.2.4 ☑ DB init SQL: `CREATE EXTENSION vector, pg_trgm, unaccent`
- Acceptance: `docker compose up -d postgres redis` healthy; `curl localhost:8000/healthz` → `{"status":"ok"}`; extensions present
- Verify: `scripts/verify/p0_s2.sh` — compose up db+redis, wait healthy, `psql -c "select extname from pg_extension"` contains vector/pg_trgm/unaccent, healthz 200
- Commit: `chore: add docker-compose and dev scripts`
- Done notes: host ports **55432 (Postgres) / 56379 (Redis)** — the user's Mac already runs Homebrew Postgres/Redis on 5432/6379. api/worker/admin are in compose profile `app`; default dev = `scripts/dev.sh` (infra in Docker, apps on host with reload). `infra/db/init.sql` creates extensions + runtime role **`raabta_app` (NOSUPERUSER NOBYPASSRLS)** so RLS works in 1.3; migrations must run as owner `raabta` via `MIGRATIONS_DATABASE_URL`. init.sql only runs on a fresh volume (`docker compose down -v` to re-init). Admin uses Next `output: "standalone"`. Docker Desktop must be running (`open -a Docker`).

#### 0.3 Config, model registry, logging — ☐
- PLAN §4, §8, §19
- Sub-steps:
  - 0.3.1 ☐ `app/core/config.py` pydantic-settings: DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY, EMBEDDINGS_*, STT_*, META_*, JWT secrets, ENV, TZ default `Asia/Karachi`; fail-fast validation
  - 0.3.2 ☐ `app/core/models_registry.py`: `MODELS` (**D-12: `agent_simple` = `claude-haiku-5-5`, `agent_complex` = `claude-opus-5-5`**; extractor/vision/judge = `claude-opus-5-5`; guard/router/answer_check/tone/summarizer = `claude-haiku-5-5`), `EFFORT` per node, `MAX_TOKENS` per node, env override `RAABTA_MODEL_<NODE>`
  - 0.3.3 ☐ `app/core/logging.py` structlog JSON + request_id middleware; `/readyz` checks db+redis
- Acceptance: missing required env → startup error with clear message; registry unit test asserts pinned IDs and explicit effort for every node
- Verify: `scripts/verify/p0_s3.sh` — `pytest tests/unit/test_config.py tests/unit/test_models_registry.py`; readyz 200 with compose
- Commit: `feat(core): settings, model registry and structured logging`

#### 0.4 CI pipeline — ☐
- PLAN §20
- Sub-steps:
  - 0.4.1 ☐ `.github/workflows/ci.yml`: jobs api (ruff, mypy, pytest with postgres+redis services), admin (lint, typecheck, test, build), widget (build + size ≤ 30KB gz), security (pip-audit, pnpm audit, gitleaks)
  - 0.4.2 ☐ `.github/workflows/evals-live.yml` skeleton (manual dispatch + label `run-evals`; requires secret; no-op until Phase 3)
  - 0.4.3 ☐ pre-commit config (ruff, prettier, gitleaks)
- Acceptance: workflow YAML validates (`act -n` or `actionlint`); local `make lint test` mirrors CI
- Verify: `scripts/verify/p0_s4.sh` — `actionlint` (installed via brew) on workflows; `make lint`; `make test`
- Needs user: 👤 push to GitHub to see first green run (user commits); report the run URL
- Commit: `ci: add lint, type, test, build and security workflows`

#### 0.5 Docs & ADR scaffolding — ☐
- Sub-steps: 0.5.1 ☐ `docs/adr/0001-stack.md`, `0002-embeddings.md` (pending bake-off), `0003-whatsapp-number-model.md`; 0.5.2 ☐ `docs/runbooks/README.md` index; 0.5.3 ☐ README links to PLAN/HANDOFF/CLAUDE
- Verify: `scripts/verify/p0_s5.sh` — files exist, markdown lint (`markdownlint-cli2` optional)
- Commit: `docs: add ADR scaffold and runbook index`

#### 0.6 User kickoff tasks (external) — ☐ 👤
- PLAN §15.2, §4
- Sub-steps (user):
  - 0.6.1 ☐ Create Meta Business Manager, start **business verification** (registration docs, utility bill); create Meta app (Business type), add WhatsApp product; note App ID, App Secret
  - 0.6.2 ☐ Decide number model (D-03); buy/allocate one phone number per pilot institution (not registered on WhatsApp app); keep test number for dev
  - 0.6.3 ☐ Anthropic API key (+ monthly spend cap in console), Voyage AI key (or chosen provider), STT provider key; put in local `.env` (never in repo)
  - 0.6.4 ☐ GitHub repo secrets: `ANTHROPIC_API_KEY` (for `evals-live`), Sentry DSNs later
  - 0.6.5 ☐ Domain decision (e.g. `raabta.ai`) and Railway/Render account (D-04)
- Verify: `scripts/verify/p0_s6.sh` — checks `.env` has non-empty `ANTHROPIC_API_KEY`, `META_APP_SECRET`, `META_VERIFY_TOKEN` placeholders (does not call APIs); session asks user to confirm Meta verification status
- Commit: none (no repo changes) — record status in §7

---

### Phase 1 — Data & multi-tenancy

#### 1.1 Core tables & Alembic baseline — ☐
- PLAN §13
- Sub-steps:
  - 1.1.1 ☐ `app/db/base.py` (UUID pk, timestamps, `TenantMixin` with `institution_id`), `session.py` (async engine, request-scoped session)
  - 1.1.2 ☐ models: `institutions`, `users`, `memberships`, `plans`, `audit_log`, `usage_daily`, `webhook_events`
  - 1.1.3 ☐ Alembic async env; migration `0001_baseline`; `make migrate`
- Acceptance: `alembic upgrade head` on empty DB creates tables; `alembic downgrade base` clean; model/migration drift check (`alembic check`) passes
- Verify: `scripts/verify/p1_s1.sh` — upgrade/downgrade/upgrade on testcontainer; `pytest tests/integration/test_migrations.py`
- Commit: `feat(db): core tenant tables and alembic baseline`

#### 1.2 Auth & RBAC — ☐
- PLAN §4 (Auth), §18
- Sub-steps:
  - 1.2.1 ☐ argon2 password hashing; login/logout/refresh (rotating refresh in httpOnly cookie); access JWT 15m
  - 1.2.2 ☐ `require_role(owner|admin|staff)` dependency; `require_superadmin`; active institution from `X-Institution` validated against membership
  - 1.2.3 ☐ invitations (create, accept), lockout after 10 failures (Redis), password rules
  - 1.2.4 ☐ `app/api/auth.py`, `members.py`; audit rows on member changes
- Acceptance: tests for login, refresh rotation, role gating (403), invitation flow, lockout
- Verify: `scripts/verify/p1_s2.sh` — `pytest tests/integration/test_auth.py tests/integration/test_members.py`
- Commit: `feat(auth): jwt sessions, rbac and invitations`

#### 1.3 Tenant context & Row-Level Security — ☐
- PLAN §18
- Sub-steps:
  - 1.3.1 ☐ DB roles `app_tenant` (RLS enforced) and `app_admin` (bypass); migration enabling RLS + policies on all tenant tables (template helper `enable_rls(table)`)
  - 1.3.2 ☐ `app/core/tenancy.py`: per-request `SET LOCAL app.institution_id` + `SET LOCAL ROLE app_tenant`; worker helper `tenant_session(institution_id)`
  - 1.3.3 ☐ ORM mixin auto-filter as second layer; lint rule/test that every tenant model has RLS policy
- Acceptance: query without GUC returns zero rows; cross-tenant insert rejected; superadmin path explicit
- Verify: `scripts/verify/p1_s3.sh` — `pytest tests/isolation/test_rls_basics.py`
- Commit: `feat(db): row-level security and tenant request context`

#### 1.4 Conversation domain tables — ☐
- PLAN §13
- Sub-steps: 1.4.1 ☐ `contacts`, `conversations`, `messages`, `llm_runs`, `leads`, `slots`, `bookings`, `followups`; 1.4.2 ☐ migration `0002_conversations`; 1.4.3 ☐ repositories/services with tenant scoping; 1.4.4 ☐ LangGraph checkpoint tables created via `AsyncPostgresSaver.setup()` in migration or startup
- Acceptance: CRUD tests; unique `(institution_id, wa_id)`; indexes present
- Verify: `scripts/verify/p1_s4.sh` — `pytest tests/integration/test_conversation_models.py`
- Commit: `feat(db): contacts, conversations, messages, leads, slots`

#### 1.5 Seed three demo institutions — ☐
- PLAN §1 (demo data), §13
- Sub-steps:
  - 1.5.1 ☐ `seeds/abc_grammar_school/` — profile (Lahore, school, tz, hours, quiet hours), classes Playgroup→Matric, fee structure XLSX (admission PKR 25,000; security 20,000 refundable; monthly 9,500–16,500 by class; annual charges 12,000; transport routes: DHA, Gulberg, Johar Town, Model Town PKR 6,000–8,500/month), prospectus DOCX (campus, timings, uniform, policies), slots (campus visits Mon–Sat 10:00–13:00), 12 contacts/leads, session 2026–27 dates (admissions Feb–Apr 2027)
  - 1.5.2 ☐ `seeds/punjab_model_college/` — college: FSc Pre-Med, Pre-Eng, ICS, ICom; eligibility (matric ≥ 60%, pre-med ≥ 70%), fees (admission 15,000; monthly 8,000–11,000), merit-based scholarships (≥ 90% → 50%), counselling slots, admission dates after BISE results (Aug–Sep 2027), hostel: none, transport routes
  - 1.5.3 ☐ `seeds/lits_university/` — university: BS CS, BS SE, BS BBA, BS EE, MS CS; eligibility (FSc ≥ 50–60%, entry test), semester fees (BS CS PKR 145,000/semester; BBA 120,000), merit list rounds, deadlines (Fall 2027: apply by 15 Jul), hostel PKR 35,000/semester, scholarships (need-based up to 100%, merit 25–75%), online application URL
  - 1.5.4 ☐ `scripts/seed.sh` / `app/cli.py seed --institution all --reset`; demo users (owner/admin/staff per institution, superadmin)
- Acceptance: seed idempotent; 3 institutions + users + facts rows + documents files on disk (ingestion runs in Phase 2)
- Verify: `scripts/verify/p1_s5.sh` — run seed twice; counts match expected; login as each demo user via test client
- Commit: `feat(seeds): three demo institutions with realistic PKR data`

#### 1.6 Audit log & usage events plumbing — ☐
- PLAN §10 (G15), §19
- Sub-steps: 1.6.1 ☐ `audit(action, entity, before, after)` service + middleware for mutating admin routes; 1.6.2 ☐ `usage_daily` rollup job skeleton (arq cron nightly) + `record_usage()` helper; 1.6.3 ☐ `GET /audit-log`, `GET /usage`
- Acceptance: member change creates audit row; rollup aggregates sample rows
- Verify: `scripts/verify/p1_s6.sh` — `pytest tests/integration/test_audit.py tests/integration/test_usage_rollup.py`
- Commit: `feat(core): audit log and usage rollup`

#### 1.7 Tenant isolation test suite — ☐
- PLAN §18, §20
- Sub-steps: 1.7.1 ☐ `tests/isolation/` fixtures: two institutions, users per role; 1.7.2 ☐ parametrized attempts: read/update/delete other tenant's rows via every existing endpoint (auto-discovered from app routes) → expect 404/403 and zero leakage; 1.7.3 ☐ CI job `isolation` required
- Acceptance: 100% of endpoints covered (route coverage assertion), all pass
- Verify: `scripts/verify/p1_s7.sh` — `pytest -m isolation`
- Commit: `test: cross-tenant isolation suite`

---

### Phase 2 — Knowledge base

#### 2.1 Document upload & storage — ☐
- PLAN §13 (`documents`), §18 (uploads)
- Sub-steps: 2.1.1 ☐ `BlobStore` interface (local FS impl; S3-compatible impl stub); 2.1.2 ☐ `POST /kb/documents` multipart (PDF/DOCX/XLSX/CSV; MIME sniff; 25MB cap; checksum dedupe; versioning), list/get/delete; 2.1.3 ☐ status machine on `documents`
- Verify: `scripts/verify/p2_s1.sh` — `pytest tests/integration/test_kb_documents.py` (upload seed files, reject exe, version bump)
- Commit: `feat(kb): document upload, storage and versioning`

#### 2.2 Parsers — ☐
- PLAN §5 KNOW
- Sub-steps: 2.2.1 ☐ PDF via `pymupdf` (page-aware text + headings heuristics); 2.2.2 ☐ DOCX via `python-docx` (headings, tables → rows); 2.2.3 ☐ XLSX/CSV via `openpyxl`/`pandas` (sheet → table rows with header); 2.2.4 ☐ Urdu quality heuristic (ratio of replacement chars / broken Nastaleeq) → flag page; optional vision-OCR fallback: render page to PNG, Claude Opus 5.5 transcription (`parse` → `PageText`) behind `KB_VISION_OCR=1`
- Acceptance: seed docs parse with page numbers; Urdu DOCX round-trips; flagged pages logged
- Verify: `scripts/verify/p2_s2.sh` — `pytest tests/unit/test_parsers.py`
- Needs user: 👤 vision-OCR test spends tokens — ask before running on real Urdu PDFs
- Commit: `feat(kb): pdf, docx and xlsx parsers with urdu quality check`

#### 2.3 Chunking — ☐
- Sub-steps: 2.3.1 ☐ heading-aware chunker, 400–800 tokens, 15% overlap, page refs, table rows kept intact; 2.3.2 ☐ `text_norm` (lowercase, unaccent, Roman-Urdu normalization map); 2.3.3 ☐ language tag per chunk (script detection + Haiku only if ambiguous — none at ingestion by default); 2.3.4 ☐ injection-pattern pre-filter → `suspicious`
- Verify: `scripts/verify/p2_s3.sh` — `pytest tests/unit/test_chunking.py` (sizes, overlap, page refs, table rows)
- Commit: `feat(kb): heading-aware chunking and text normalization`

#### 2.4 Embedding provider + bake-off — ☐ 👤
- PLAN §4 (Embeddings), D-01
- Sub-steps: 2.4.1 ☐ `EmbeddingProvider` interface, `VoyageProvider`, `BGEM3Provider` (HTTP to local TEI/ollama-style endpoint), `FakeProvider` for tests; 2.4.2 ☐ `chunks.embedding vector(D)` migration with D from config + HNSW index; 2.4.3 ☐ `evals/datasets/retrieval.yaml` (60 Q: 20 EN/20 UR/20 RU with gold chunk ids on seed docs); 2.4.4 ☐ `scripts/bakeoff_embeddings.py` → recall@5 per provider per language → write `docs/adr/0002-embeddings.md` decision
- Acceptance: fake provider passes pipeline tests; bake-off report produced; ADR updated
- Verify: `scripts/verify/p2_s4.sh` — `pytest tests/unit/test_embeddings.py` (fake); if keys present, runs bake-off on 10-case subset and prints recall
- Needs user: 👤 provider keys + approval for bake-off spend (small: ~2k embeddings)
- Commit: `feat(kb): embedding provider interface and bake-off`

#### 2.5 Hybrid search — ☐
- PLAN §5 KNOW, §11
- Sub-steps: 2.5.1 ☐ `search.py`: vector cosine (HNSW) + FTS (`tsv`, `simple`+unaccent) + `pg_trgm` on `text_norm`; RRF fusion; top_k; per-institution filter (RLS + explicit); 2.5.2 ☐ `seeds/ru_synonyms.csv` (≈200 terms) + query expansion; 2.5.3 ☐ multi-query (1–3 queries) fused; 2.5.4 ☐ token-budgeted result packing (≤ 2k tokens)
- Acceptance: retrieval eval recall@5 ≥ 90% on seed set (with chosen provider); Roman-Urdu subset ≥ 85%
- Verify: `scripts/verify/p2_s5.sh` — `pytest tests/integration/test_search.py`; `python -m evals.run_evals --suite retrieval` (fake provider in CI; real locally)
- Commit: `feat(kb): hybrid vector + keyword + trigram search with rrf`

#### 2.6 Structured facts extraction & approval — ☐ 👤
- PLAN §5 KNOW, §7 (facts_extractor), §11 (2)
- Sub-steps: 2.6.1 ☐ models `programs`, `fee_items`, `key_dates`, `scholarships`, `transport_routes` + migration; 2.6.2 ☐ `facts_extractor.py` (Opus, effort high, `messages.parse` → `FactsBatch`, batches ≤ 20 pages, page refs, PKR normalization); 2.6.3 ☐ pending → approve/edit endpoints (`/kb/facts/{kind}`); 2.6.4 ☐ `facts_version` bump on approve (invalidates tenant cache block); 2.6.5 ☐ XLSX fee sheets map directly to `fee_items` (no LLM) when columns recognized
- Acceptance: seed fee XLSX → approved rows match expected PKR values exactly; extractor on prospectus yields programs/dates with page refs; approval flow audited
- Verify: `scripts/verify/p2_s6.sh` — `pytest tests/integration/test_facts.py` (XLSX path deterministic); extractor test replayed from cassette; live run on request
- Needs user: 👤 approve live extractor run on seed docs (~3 docs, low cost)
- Commit: `feat(kb): structured facts extraction with admin approval`

#### 2.7 Citations model — ☐
- Sub-steps: 2.7.1 ☐ `Citation{document_id,title,page,chunk_id,quote}` schema; 2.7.2 ☐ search results and fact rows carry source refs; 2.7.3 ☐ playground endpoint `POST /kb/playground` returns answer-less retrieval view (chunks + facts + citations) for now
- Verify: `scripts/verify/p2_s7.sh` — `pytest tests/unit/test_citations.py tests/integration/test_playground.py`
- Commit: `feat(kb): citation schema and playground retrieval endpoint`

#### 2.8 Ingestion pipeline (arq) & KB evals — ☐
- PLAN §5 STEER (workflows), §12
- Sub-steps: 2.8.1 ☐ arq task chain upload→parse→chunk→embed→extract→ready with status updates and error capture; re-index endpoint; supersede old version chunks; 2.8.2 ☐ idempotent, resumable per stage; 2.8.3 ☐ `make ingest-seeds`; 2.8.4 ☐ retrieval eval wired into `evals-smoke`
- Acceptance: all seed docs reach `ready`; re-index replaces chunks atomically; failures surface in `documents.error`
- Verify: `scripts/verify/p2_s8.sh` — run worker in test mode, ingest seeds, assert statuses + chunk counts + retrieval eval ≥ threshold
- Commit: `feat(kb): ingestion pipeline with re-index and retrieval evals`

---

### Phase 3 — Agent core + eval harness

#### 3.1 Claude client wrapper — ☐
- PLAN §8; CLAUDE.md API rules
- Sub-steps: 3.1.1 ☐ `app/llm/claude.py`: `complete/parse/stream`, node-keyed model+effort, Opus via `client.beta.messages` with `betas=["server-side-fallback-2026-07-01"], fallbacks="default"`, Haiku via `client.messages`; explicit `output_config.effort`; no sampling params; no prefill; `tool_choice auto` only; 3.1.2 ☐ typed exception handling + jittered retries (RateLimitError, 5xx/529 APIStatusError, APIConnectionError), per-node timeouts; 3.1.3 ☐ `stop_reason` handling (refusal/max_tokens/tool_use/end_turn) + `stop_details` logging; 3.1.4 ☐ cost table `cost.py` + `llm_runs` write incl. cache tokens + `fallback_used`; 3.1.5 ☐ record/replay cassettes (`RAABTA_LLM_RECORD/REPLAY`) keyed by request hash; 3.1.6 ☐ dev assert: prefix hash unchanged within a turn; cache-hit assertion test
- Acceptance: unit tests with mocked SDK for every branch; one live smoke (`scripts/llm_smoke.py`) shows `cache_read_input_tokens > 0` on second call
- Verify: `scripts/verify/p3_s1.sh` — `pytest tests/unit/test_claude_wrapper.py`; live smoke only if `ANTHROPIC_API_KEY` set and `--live`
- Needs user: 👤 approve live smoke (cents)
- Commit: `feat(llm): anthropic client wrapper with retries, fallback and cost logging`

#### 3.2 Prompt files & loader — ☐
- PLAN §9.1
- Sub-steps: 3.2.1 ☐ loader with front-matter validation + content hash; 3.2.2 ☐ write `system_global.md`, `agent_admissions.md`, `agent_fees.md`, `router.md` (12 few-shot), `guard_in.md`, `answer_check.md`, `tone_check.md`, `summarizer.md`, `tenant_block.md.j2`; 3.2.3 ☐ fallback phrases per language constants; 3.2.4 ☐ test: no dates/timestamps in cacheable prompts; tenant block deterministic (sorted keys)
- Verify: `scripts/verify/p3_s2.sh` — `pytest tests/unit/test_prompts.py`
- Commit: `feat(agent): versioned prompt files and loader`

#### 3.3 Skills loader & skill packs — ☐
- PLAN §9.2
- Sub-steps: 3.3.1 ☐ `skills_loader.py` (parse `skill.yaml`, `select(institution_type, module, intents, channel, language)`, deterministic order, token cap); 3.3.2 ☐ write the 9 SKILL.md packs (≤ 1.2k tokens each) with Pakistani context; 3.3.3 ☐ tests: selection matrix, cap enforcement
- Verify: `scripts/verify/p3_s3.sh` — `pytest tests/unit/test_skills.py`; token count per skill ≤ cap (via `count_tokens` cassette or tiktoken-free heuristic)
- Commit: `feat(agent): skills loader and skill packs`

#### 3.4 Tool registry & tools — ☐
- PLAN §9.3, §5 DO
- Sub-steps: 3.4.1 ☐ `registry.py` (Pydantic in/out → strict JSON schema with `additionalProperties:false`, permission, side_effect, modules, `list_tools(module)` name-sorted, `execute` with `ToolContext`, error → `is_error`); 3.4.2 ☐ admissions tools (`search_knowledge`, `get_fee_table`, `get_programs`, `get_key_dates`, `get_scholarships`, `get_transport_routes`, `save_lead`, `get_visit_slots`, `book_visit`, `schedule_followup`); 3.4.3 ☐ common tools (`handoff_to_human`, `set_contact_language`); fee tools stubbed with permission gate (implemented 7.x); 3.4.4 ☐ `GET /internal/tools` manifest
- Acceptance: schema snapshot test; every tool has tests incl. tenant scoping and permission denial
- Verify: `scripts/verify/p3_s4.sh` — `pytest tests/unit/test_registry.py tests/integration/test_tools_admissions.py`
- Commit: `feat(agent): strict tool registry and admissions tools`

#### 3.5 LangGraph inbound graph — ☐
- PLAN §6.1
- Sub-steps: 3.5.1 ☐ `state.py`, `graph.py` with `AsyncPostgresSaver`, thread id `institution:contact`; 3.5.2 ☐ nodes: `ingest`, `guard_in`, `router`, `load_context`, `agent` (tool loop, append-only, ≤ 6 iters, parallel tool results in one message), `answer_check`, `repair`, `safe_fallback`, `compose`, `persist`, `summarize`, `handoff` (interrupt); 3.5.3 ☐ human-mode gate + resume via `Command(resume=...)`; 3.5.4 ☐ `run_inbound(event)` entrypoint used by widget + WhatsApp
- Acceptance: graph tests with fake LLM provider covering every edge (blocked, simple, complex, handoff, repair, fallback)
- Verify: `scripts/verify/p3_s5.sh` — `pytest tests/unit/test_graph.py`
- Commit: `feat(agent): langgraph inbound graph with human takeover`

#### 3.6 Context assembly & compaction — ☐
- PLAN §7
- Sub-steps: 3.6.1 ☐ `context.py` builder: cache-ordered blocks (tools → global → tenant → skills), first user block (date/profile/verified), summary, history text (6 turns, tool calls collapsed), new message; budgets + priority truncation; 3.6.2 ☐ simple compaction across turns (no thinking replay); mid-turn operator notes as appended `role:system`; 3.6.3 ☐ tests: budgets, determinism (same inputs → same bytes), no timestamp in cached blocks, prefix stable across loop iterations
- Verify: `scripts/verify/p3_s6.sh` — `pytest tests/unit/test_context.py`
- Commit: `feat(agent): deterministic context assembly with cache-stable prefix`

#### 3.7 Guardrails — ☐
- PLAN §10
- Sub-steps: 3.7.1 ☐ `guards/`: opt-out keywords, injection pre-filter, identity gate helper, language/script detector, loop/cost caps, per-contact rate limit (Redis); 3.7.2 ☐ `answer_check` claim extraction + numeric exact-match verifier + repair feedback format; 3.7.3 ☐ safe replies per language; 3.7.4 ☐ guardrails eval dataset (40 cases)
- Verify: `scripts/verify/p3_s7.sh` — `pytest tests/unit/test_guards.py`; `evals --suite guardrails` (replay)
- Commit: `feat(agent): input guard, grounding check and safety fallbacks`

#### 3.8 Summarizer & LTM updates — ☐
- PLAN §5 KNOW (STM/LTM), §7 (summarize)
- Sub-steps: 3.8.1 ☐ `Summary` schema + summarizer node; 3.8.2 ☐ contact profile deltas (name, language, student, stage) written to `contacts.profile`; lead upsert from summary when phone known; 3.8.3 ☐ idle > 7 days history reset rule; 3.8.4 ☐ `goal_status` tracking
- Verify: `scripts/verify/p3_s8.sh` — `pytest tests/unit/test_summarizer.py`
- Commit: `feat(agent): structured rolling summary and contact memory`

#### 3.9 Eval harness — ☐ 👤
- PLAN §12
- Sub-steps: 3.9.1 ☐ `evals/run_evals.py` (suites, graders, thresholds, JSON+MD report, PR comment format); 3.9.2 ☐ datasets: `router` (80), `admissions_school/college/university` (60 each), `guardrails` (40), `tone` (30); 3.9.3 ☐ graders: deterministic + judge (Opus, `parse`); 3.9.4 ☐ cassettes recorded for smoke; 3.9.5 ☐ `evals-live.yml` completed: triggers (label, nightly, prompt/skill/registry paths), threshold gate, report artifact; 3.9.6 ☐ baseline report committed to `evals/reports/baseline.md`
- Acceptance: smoke runs offline in CI < 3 min; live run meets thresholds or failing cases listed with fixes
- Verify: `scripts/verify/p3_s9.sh` — `python -m evals.run_evals --replay --all`; live with `--live` on approval
- Needs user: 👤 approve first live eval run (~400 cases ≈ $15–25)
- Commit: `feat(evals): eval harness, datasets and ci gates`

#### 3.10 Local chat CLI & end-to-end smoke — ☐ 👤
- Sub-steps: 3.10.1 ☐ `scripts/chat.py --institution abc-grammar --lang ru` interactive REPL over `run_inbound` (shows tools, citations, check verdict, cost); 3.10.2 ☐ scripted 3 conversations per institution type (EN/UR/RU) saved as transcripts in `docs/demo/`
- Verify: `scripts/verify/p3_s10.sh` — replay-mode scripted conversations assert tool calls + citations; live on approval
- Needs user: 👤 try the CLI with real key; confirm answers feel right in Roman Urdu
- Commit: `feat(agent): local chat cli and demo transcripts`

---

### Phase 4 — Web widget + chat API

#### 4.1 Public chat API (SSE) — ☐
- PLAN §14 (Widget), §15.1 (security)
- Sub-steps: 4.1.1 ☐ `GET /widget/config/{slug}` (theme, languages, suggested questions, WhatsApp number); 4.1.2 ☐ `POST /widget/sessions` (origin allowlist, visitor id, session JWT 24h); 4.1.3 ☐ `POST /widget/sessions/{id}/messages` SSE with **check-then-send** (`status` events while tools run → `message` with the answer_check-approved text → `citation`, `quick_replies`, `slots`, `lead_form`, `done`); never stream the unchecked draft (D-11); test asserts no `message` event is emitted before the check verdict; 4.1.4 ☐ rate limits (IP + session), message cap, abuse lockout; 4.1.5 ☐ `POST /widget/sessions/{id}/lead`, `GET .../whatsapp-link` (session code)
- Verify: `scripts/verify/p4_s1.sh` — `pytest tests/integration/test_widget_api.py` (fake LLM streaming)
- Commit: `feat(widget-api): public session and streaming chat endpoints`

#### 4.2 Widget bundle — ☐ 👤
- PLAN §15.1
- Sub-steps: 4.2.1 ☐ Shadow DOM mount, launcher, panel (mobile full-screen), theme via CSS vars from config; 4.2.2 ☐ message list, status line ("searching prospectus…"), progressive client-side render of the approved reply, typing indicator, citation chips, quick replies, slot picker, lead mini-form; 4.2.3 ☐ language toggle EN/UR/RU, RTL + Noto Nastaliq lazy-load; 4.2.4 ☐ "Continue on WhatsApp" (wa.me link w/ session code); 4.2.5 ☐ build ≤ 30KB gz, versioned output `dist/v1/widget.js`, size check in CI
- Verify: `scripts/verify/p4_s2.sh` — build + size check + Vitest unit tests for state/renderer
- Needs user: 👤 visual check on desktop + phone (test page URL printed)
- Commit: `feat(widget): shadow-dom chat widget with rtl and whatsapp handoff`

#### 4.3 Widget served by API + embed test pages — ☐
- Sub-steps: 4.3.1 ☐ api serves `/widget/v1/widget.js` with long cache + version header (CDN later); 4.3.2 ☐ `widget/test-pages/` plain.html, wordpress-like.html, rtl.html; 4.3.3 ☐ Playwright e2e: open, ask seed question, see citation, book slot, lead form
- Verify: `scripts/verify/p4_s3.sh` — `pnpm -C widget e2e` against local api (fake LLM mode)
- Needs user: 👤 confirm on a real WordPress/Wix page if available
- Commit: `feat(widget): embed test pages and e2e`

#### 4.4 Widget docs & install guides — ☐
- Sub-steps: 4.4.1 ☐ `docs/widget/install.md` (WordPress, Wix, custom HTML, CSP notes); 4.4.2 ☐ theming reference
- Verify: `scripts/verify/p4_s4.sh` — docs exist; snippet in docs matches `GET /institution/widget-snippet` output
- Commit: `docs(widget): install and theming guides`

---

### Phase 5 — Admin panel foundation

#### 5.1 Next.js foundation — ☐
- PLAN §17, §4
- Sub-steps: 5.1.1 ☐ app shell (sidebar/topbar, responsive), shadcn/ui install, design tokens (light/dark, CSS vars), fonts (Inter + Noto Nastaliq Urdu); 5.1.2 ☐ auth: login page, cookie session, middleware guard, `useMe`; 5.1.3 ☐ TanStack Query client + OpenAPI-generated TS client (`openapi-typescript`); 5.1.4 ☐ next-intl EN/UR with RTL `dir` switch; 5.1.5 ☐ error boundaries, toasts, skeleton primitives, empty-state component
- Verify: `scripts/verify/p5_s1.sh` — lint, typecheck, Vitest, build; Playwright login smoke (fake api or seeded api)
- Needs user: 👤 visual check light/dark + UR RTL
- Commit: `feat(admin): next.js shell, auth, i18n and design system`

#### 5.2 Onboarding wizard — ☐
- Sub-steps: 5.2.1 ☐ steps: profile → documents upload (progress, statuses) → facts review/approve → WhatsApp status card (placeholder until 6.x) → widget snippet + theme picker + live preview → checklist; 5.2.2 ☐ API `POST /institution/onboarding/{step}`; resume where left; 5.2.3 ☐ e2e
- Verify: `scripts/verify/p5_s2.sh` — Playwright onboarding flow on seeded api
- Needs user: 👤 visual check
- Commit: `feat(admin): onboarding wizard`

#### 5.3 Overview dashboard & metrics API — ☐
- Sub-steps: 5.3.1 ☐ `GET /metrics/*` (from `usage_daily` + live counts); 5.3.2 ☐ KPI tiles, funnel, trends, channel split, "needs attention"; 5.3.3 ☐ chart palette/theme consistent (light/dark)
- Verify: `scripts/verify/p5_s3.sh` — `pytest tests/integration/test_metrics.py`; admin build + component tests
- Commit: `feat(admin): overview dashboard and metrics api`

#### 5.4 Live inbox with human takeover — ☐
- PLAN §6.1 (takeover), §17
- Sub-steps: 5.4.1 ☐ conversations API filters + SSE events stream; 5.4.2 ☐ 3-pane inbox UI, viewer (bubbles, media, transcript, citations, tool calls, summary card, contact card); 5.4.3 ☐ Take over / Return to AI / assign / resolve / flag; staff composer + internal notes; 5.4.4 ☐ keyboard shortcuts; 5.4.5 ☐ e2e: AI replies → takeover → staff reply → return to AI → AI resumes with context
- Verify: `scripts/verify/p5_s4.sh` — `pytest tests/integration/test_inbox.py`; Playwright inbox e2e (fake LLM)
- Needs user: 👤 visual/UX check
- Commit: `feat(admin): live inbox with takeover and return-to-ai`

#### 5.5 Leads pipeline — ☐
- Sub-steps: 5.5.1 ☐ leads API (filters, status, owner, export CSV); 5.5.2 ☐ kanban (dnd) + table views, lead drawer (timeline, bookings, notes); 5.5.3 ☐ e2e
- Verify: `scripts/verify/p5_s5.sh` — api tests + Playwright
- Commit: `feat(admin): leads kanban and table with export`

#### 5.6 Slot calendar — ☐
- Sub-steps: 5.6.1 ☐ slots/bookings API incl. bulk recurring creation; 5.6.2 ☐ week calendar UI, create/edit, bookings list, reschedule/cancel/no-show; 5.6.3 ☐ booking confirmation message hook (widget now, WhatsApp template in 6.x)
- Verify: `scripts/verify/p5_s6.sh` — api tests + Playwright
- Commit: `feat(admin): visit, test and counselling slot calendar`

#### 5.7 Knowledge base manager & playground — ☐
- Sub-steps: 5.7.1 ☐ documents table (status chips, re-index, delete, version), upload dropzone; 5.7.2 ☐ chunk viewer; 5.7.3 ☐ facts tabs with approve/edit/add; 5.7.4 ☐ playground: question → full agent run (answer, citations, retrieved chunks, check verdict, cost) using `POST /kb/playground` extended to run graph in "sandbox contact" mode
- Verify: `scripts/verify/p5_s7.sh` — api tests + Playwright (fake LLM)
- Needs user: 👤 try playground with real key on seed institutions
- Commit: `feat(admin): knowledge base manager and playground`

#### 5.8 Settings — ☐
- Sub-steps: 5.8.1 ☐ institution profile, languages, quiet hours, escalation rules (keywords → human; max AI turns), CTAs; 5.8.2 ☐ team & roles (invite, change role, remove) with audit; 5.8.3 ☐ widget theme/origins; 5.8.4 ☐ WhatsApp connection panel (read-only status until 6.x)
- Verify: `scripts/verify/p5_s8.sh` — api tests + Playwright
- Commit: `feat(admin): settings, team and roles`

#### 5.9 Super-admin — ☐
- Sub-steps: 5.9.1 ☐ `/superadmin/*` API (tenants, plans, status, impersonate with audit + banner, global usage); 5.9.2 ☐ UI pages; 5.9.3 ☐ isolation tests extended for superadmin paths
- Verify: `scripts/verify/p5_s9.sh` — `pytest tests/integration/test_superadmin.py -m isolation`; Playwright
- Commit: `feat(admin): super-admin tenant management`

#### 5.10 Usage & billing + audit log pages — ☐
- Sub-steps: 5.10.1 ☐ usage page (messages, template sends, AI cost, plan limit bars); 5.10.2 ☐ audit log table with filters + diff view
- Verify: `scripts/verify/p5_s10.sh` — Playwright + api tests
- Commit: `feat(admin): usage, billing and audit log pages`

#### 5.11 UI quality pass — ☐ 👤
- Sub-steps: 5.11.1 ☐ axe accessibility on all pages (no serious violations), focus management, aria; 5.11.2 ☐ mobile layouts (inbox, leads); 5.11.3 ☐ loading/empty/error states everywhere; 5.11.4 ☐ Lighthouse ≥ 90 perf/a11y on dashboard + inbox; 5.11.5 ☐ Urdu UI translation review
- Verify: `scripts/verify/p5_s11.sh` — Playwright axe suite; Lighthouse CI budget
- Needs user: 👤 Urdu copy review; visual QA
- Commit: `feat(admin): accessibility, responsive and polish pass`

---

### Phase 6 — WhatsApp channel

#### 6.1 Meta app & number setup — ☐ 👤
- PLAN §15.2
- Sub-steps (user, guided by session): 6.1.1 ☐ WABA created, phone number added, display name approved; 6.1.2 ☐ permanent system-user token with `whatsapp_business_messaging` + `whatsapp_business_management`; 6.1.3 ☐ webhook URL (ngrok/cloudflared for dev) + verify token; subscribe fields `messages`, `message_template_status_update`; 6.1.4 ☐ `.env`: `META_APP_SECRET`, `META_ACCESS_TOKEN`, `META_VERIFY_TOKEN`, `META_PHONE_NUMBER_ID` (dev); institution row gets `wa_phone_number_id`
- Verify: `scripts/verify/p6_s1.sh` — `GET /{phone_number_id}` via Graph API returns display name (needs token); webhook GET verify round-trip via public URL
- Needs user: 👤 all of it; expected output printed by script
- Commit: none / `docs: whatsapp setup notes`

#### 6.2 Webhook receiver — ☐
- Sub-steps: 6.2.1 ☐ `GET /webhooks/whatsapp` verify; `POST` signature check (`X-Hub-Signature-256`, raw body), `webhook_events` idempotency, enqueue, 200 fast; 6.2.2 ☐ payload parsing for text/audio/image/interactive/button/document/location + statuses; tenant by `phone_number_id`; 6.2.3 ☐ contact upsert by `wa_id`, conversation open/reuse, `last_inbound_at`; 6.2.4 ☐ worker task → `run_inbound`
- Verify: `scripts/verify/p6_s2.sh` — `pytest tests/channels/test_whatsapp_webhook.py` (fixtures of real payload shapes; bad signature → 403; duplicate ignored)
- Commit: `feat(whatsapp): signed webhook receiver with idempotency`

#### 6.3 Sender & 24-hour window — ☐
- Sub-steps: 6.3.1 ☐ Graph API client (text, interactive buttons/list, template, image), retries/backoff, error mapping; 6.3.2 ☐ `window.py` (free-form allowed iff `now - last_inbound_at < 24h`), sender refuses free-form otherwise; 6.3.3 ☐ status webhooks → `messages.status`; 6.3.4 ☐ compose for WhatsApp (length, no tables, buttons ≤ 3)
- Verify: `scripts/verify/p6_s3.sh` — `pytest tests/channels/test_sender.py tests/unit/test_window.py` (httpx mock); live: send test text to user's number on approval
- Needs user: 👤 confirm receipt of test message on phone
- Commit: `feat(whatsapp): outbound sender with 24h window enforcement`

#### 6.4 Voice notes (STT) & media — ☐ 👤
- PLAN §4 (STT), D-02
- Sub-steps: 6.4.1 ☐ media download (`GET /{media_id}` → URL → bytes) + storage; 6.4.2 ☐ `SpeechToTextProvider` interface, `OpenAIProvider` (`gpt-4o-transcribe`, fallback `whisper-1`), `FakeProvider`; 6.4.3 ☐ `scripts/bakeoff_stt.py` on 20 sample voice notes (user-provided) → ADR `0004-stt.md`; 6.4.4 ☐ transcript into graph; confidence < 0.6 → ask to type; transcript visible in inbox
- Verify: `scripts/verify/p6_s4.sh` — unit tests with fake provider; live transcription of one sample on approval
- Needs user: 👤 STT key + 20 sample voice notes (UR/RU) for bake-off
- Commit: `feat(whatsapp): voice note transcription behind stt interface`

#### 6.5 Template manager — ☐ 👤
- Sub-steps: 6.5.1 ☐ `templates` CRUD, variables, language variants; 6.5.2 ☐ submit via Graph API `/{waba_id}/message_templates`, status sync (webhook + poll); 6.5.3 ☐ seed templates EN/UR/RU: `admission_followup_1/2`, `visit_confirmation`, `visit_reminder`, `fee_reminder_1..4`, `promise_followup`, `receipt_received`, `daily_summary`; 6.5.4 ☐ admin UI: list, editor, preview, submit, sync
- Verify: `scripts/verify/p6_s5.sh` — api tests (mock Graph); live: submit one template and show status
- Needs user: 👤 review template wording (tone) before submission; approvals take hours–days
- Commit: `feat(whatsapp): message template manager with meta sync`

#### 6.6 Widget → WhatsApp continuity — ☐
- Sub-steps: 6.6.1 ☐ session code in prefilled text; on first WA message containing code → link contact to widget session, import summary; 6.6.2 ☐ tests
- Verify: `scripts/verify/p6_s6.sh` — `pytest tests/channels/test_handoff_link.py`
- Commit: `feat(whatsapp): link widget sessions to whatsapp conversations`

#### 6.7 Admissions follow-ups & daily summary — ☐
- PLAN §6.2
- Sub-steps: 6.7.1 ☐ followups scheduler (24h/72h no-reply, `schedule_followup` dates, booking reminders day-before) → policy gate → template send; 6.7.2 ☐ daily principal summary 18:00 PKT (counts, top questions, leads, bookings, flagged) via WhatsApp template to configured numbers + in-app; 6.7.3 ☐ tests with frozen clock
- Verify: `scripts/verify/p6_s7.sh` — `pytest tests/unit/test_followups.py tests/unit/test_daily_summary.py`
- Commit: `feat(followups): scheduled admissions follow-ups and daily summary`

#### 6.8 Channel guardrails & Meta policy checklist — ☐
- PLAN §10 (G6–G8, G12), §21
- Sub-steps: 6.8.1 ☐ opt-out keywords multi-language + confirmation + sequence cancellation; 6.8.2 ☐ quiet hours + Jumma window in policy gate; 6.8.3 ☐ per-contact caps; 6.8.4 ☐ privacy line on first reply; 6.8.5 ☐ `docs/runbooks/meta-policy-checklist.md`
- Verify: `scripts/verify/p6_s8.sh` — `pytest tests/unit/test_policy_gate.py tests/channels/test_optout.py`
- Commit: `feat(whatsapp): opt-out, quiet hours and policy gate`

---

### Phase 7 — Module 2: Fee recovery

#### 7.1 Fee data model & import — ☐
- PLAN §16, §13
- Sub-steps: 7.1.1 ☐ tables `fee_accounts`, `fee_imports`, `payment_promises`, `payment_proofs`, `reminder_sequences`, `reminder_runs` + migration; 7.1.2 ☐ importer: XLSX/CSV parse, column auto-guess, mapping API, validation (phone → +92, duplicates, blanks), preview, commit upsert by `student_ref`; 7.1.3 ☐ manual entry + mark paid; 7.1.4 ☐ seed defaulter lists for 3 institutions
- Verify: `scripts/verify/p7_s1.sh` — `pytest tests/unit/test_fee_importer.py tests/integration/test_fee_accounts.py` (hypothesis on messy sheets)
- Commit: `feat(fees): fee accounts and defaulter import`

#### 7.2 Parent identity verification — ☐
- PLAN §10 (G4), §9.3
- Sub-steps: 7.2.1 ☐ `verify_parent` tool: phone-on-file match + student name + class/roll (fuzzy on name), 3 attempts/24h then human; `contacts.verified` with expiry (30 days); 7.2.2 ☐ registry permission `verified_parent` enforced for fee tools; 7.2.3 ☐ `answer_check` identity rule tests; guardrails eval cases added
- Verify: `scripts/verify/p7_s2.sh` — `pytest tests/unit/test_verify_parent.py`; `evals --suite guardrails --replay`
- Commit: `feat(fees): parent identity verification gate`

#### 7.3 Reminder sequences & scheduler — ☐
- PLAN §6.2, §16
- Sub-steps: 7.3.1 ☐ sequence model + default 4-step sequence per institution (templates from 6.5); 7.3.2 ☐ arq cron collect_due → policy_gate → window_check → render → send → schedule_next; stop rules; 7.3.3 ☐ `POST /fees/sequences/{id}/preview` (who gets what, when) + `start` (requires confirm; audit) + `stop`; 7.3.4 ☐ tests with frozen clock across quiet hours/weekly caps/stop rules
- Verify: `scripts/verify/p7_s3.sh` — `pytest tests/unit/test_sequences.py tests/integration/test_reminder_scheduler.py`
- Commit: `feat(fees): template reminder sequences with policy gate`

#### 7.4 Fee agent & promises — ☐
- PLAN §16, §9
- Sub-steps: 7.4.1 ☐ fee tools: `get_fee_status`, `record_payment_promise`, `request_receipt`, `raise_dispute`; 7.4.2 ☐ `agent_fees.md` + `fee-recovery-etiquette` skill finalized; router fee intents; 7.4.3 ☐ promise track (follow-up at date+1, kept/broken, resume sequence); 7.4.4 ☐ tone_check on any LLM-generated outbound fee text; 7.4.5 ☐ fee eval dataset (60) incl. "salary 10 ko aayegi", "already paid", "ye galat hai", hardship
- Verify: `scripts/verify/p7_s4.sh` — `pytest tests/integration/test_fee_agent.py`; `evals --suite fees --replay`
- Needs user: 👤 live fee eval run approval
- Commit: `feat(fees): fee agent, payment promises and dispute handoff`

#### 7.5 Receipt verification (vision) — ☐ 👤
- PLAN §7 (receipt_reader), §16
- Sub-steps: 7.5.1 ☐ `submit_payment_proof` → `receipt_reader` (Opus vision, `parse` → `ReceiptExtraction`) → `payment_proofs(pending)`; 7.5.2 ☐ admin queue API confirm/reject → status paid + `receipt_received` template / polite re-request; 7.5.3 ☐ `receipt-verification` skill; 7.5.4 ☐ test images (synthetic HBL/JazzCash/Easypaisa slips) with cassettes
- Verify: `scripts/verify/p7_s5.sh` — `pytest tests/integration/test_receipts.py` (replay); live on 3 sample images on approval
- Needs user: 👤 a few real (redacted) receipt images; spend approval
- Commit: `feat(fees): receipt extraction with staff confirmation`

#### 7.6 Fee admin UI & recovery report — ☐ 👤
- PLAN §17 (Fees)
- Sub-steps: 7.6.1 ☐ defaulters table + import wizard (mapping, preview); 7.6.2 ☐ sequence builder + preview/start/stop; 7.6.3 ☐ promises list, receipts queue (image viewer + fields + confirm/reject); 7.6.4 ☐ recovery report (`GET /fees/report`: recovered vs outstanding, by class/step, response rate, promises kept, days-to-pay; charts + CSV); 7.6.5 ☐ dashboard tiles wired
- Verify: `scripts/verify/p7_s6.sh` — api tests + Playwright fee flows
- Needs user: 👤 visual check
- Commit: `feat(admin): fee module ui and recovery report`

#### 7.7 Fee end-to-end scenarios — ☐
- Sub-steps: 7.7.1 ☐ e2e: import → start sequence → simulated inbound "salary 10 ko aayegi" → promise → follow-up → receipt image → confirm → paid → report updated; 7.7.2 ☐ opt-out mid-sequence; dispute → human; quiet hours shift
- Verify: `scripts/verify/p7_s7.sh` — `pytest tests/e2e/test_fee_recovery_flow.py` (fake LLM + mocked Graph)
- Commit: `test(fees): end-to-end recovery scenarios`

---

### Phase 8 — Hardening

#### 8.1 Security pass — ☐
- PLAN §18, §10
- Sub-steps: 8.1.1 ☐ OWASP checklist walkthrough documented (`docs/security.md`); headers (CSP, HSTS, frame options; widget exceptions), CORS review; 8.1.2 ☐ dependency audit clean; gitleaks; 8.1.3 ☐ webhook replay/ordering tests; upload hardening; 8.1.4 ☐ prompt-injection red-team eval set extended (20 more cases incl. document-embedded instructions); 8.1.5 ☐ secrets rotation runbook
- Verify: `scripts/verify/p8_s1.sh` — security tests + `pip-audit` + `pnpm audit` + header checks via httpx
- Commit: `chore(security): hardening pass and red-team evals`

#### 8.2 Observability — ☐ 👤
- PLAN §19
- Sub-steps: 8.2.1 ☐ OTel instrumentation + LLM spans; OTLP exporter config; Langfuse compose profile (optional); 8.2.2 ☐ Sentry in api/worker/admin/widget; 8.2.3 ☐ alerts list + health dashboard doc; 8.2.4 ☐ PII scrubbing in logs
- Verify: `scripts/verify/p8_s2.sh` — spans emitted to in-memory exporter in tests; Sentry DSN config test
- Needs user: 👤 Sentry project + DSNs
- Commit: `feat(obs): opentelemetry llm tracing and sentry`

#### 8.3 Cost tracking & plan limits — ☐
- PLAN §19 (cost model)
- Sub-steps: 8.3.1 ☐ `usage_daily` complete rollup incl. template sends + cost; 8.3.2 ☐ plan limits soft (80% alert) / hard (hold outbound, widget notice); superadmin override; 8.3.3 ☐ Haiku fast-path for greetings/thanks; effort `low` routing for simple intents validated by evals; 8.3.4 ☐ cost report per tenant in superadmin
- Verify: `scripts/verify/p8_s3.sh` — `pytest tests/unit/test_plan_limits.py tests/integration/test_usage.py`
- Commit: `feat(billing): per-tenant cost tracking and plan limits`

#### 8.4 Performance & load — ☐
- Sub-steps: 8.4.1 ☐ k6 scripts (widget chat 50 concurrent, webhook burst 200/min) with fake LLM; 8.4.2 ☐ DB index review, connection pool sizing, N+1 audit; 8.4.3 ☐ p95 targets: widget first token < 2.5s (live), webhook ack < 300ms, inbox list < 400ms
- Verify: `scripts/verify/p8_s4.sh` — run k6 locally, assert thresholds
- Commit: `perf: load tests and query tuning`

#### 8.5 Backups & restore drill — ☐ 👤
- PLAN §21
- Sub-steps: 8.5.1 ☐ nightly `pg_dump` job (worker cron or platform backup) to object storage; media bucket versioning; 8.5.2 ☐ `scripts/restore_drill.sh` (restore into scratch DB, run smoke); 8.5.3 ☐ retention policy jobs (media 180d)
- Verify: `scripts/verify/p8_s5.sh` — local dump + restore drill succeeds
- Needs user: 👤 object storage bucket + creds
- Commit: `chore(ops): backups and restore drill`

#### 8.6 Privacy & compliance docs — ☐
- PLAN §21
- Sub-steps: 8.6.1 ☐ `docs/privacy.md` (PECA notes, consent, retention, export/delete, no-training), DPA template; 8.6.2 ☐ export/delete endpoints per institution (superadmin) + tests; 8.6.3 ☐ Meta policy checklist signed off; consent/privacy line copy in 3 languages
- Verify: `scripts/verify/p8_s6.sh` — export/delete tests; docs present
- Commit: `feat(privacy): data export/delete and compliance docs`

#### 8.7 Docs & runbooks — ☐
- Sub-steps: 8.7.1 ☐ `docs/api/` (OpenAPI export), `docs/runbooks/` (incidents, webhook failures, template rejected, cache hit rate low, model upgrade procedure), ADRs updated; 8.7.2 ☐ README full quickstart
- Verify: `scripts/verify/p8_s7.sh` — docs lint; OpenAPI export matches app
- Commit: `docs: runbooks, api docs and adr updates`

---

### Phase 9 — Pilot launch kit

#### 9.1 Production deploy — ☐ 👤
- PLAN §22, D-04
- Sub-steps: 9.1.1 ☐ prod Dockerfiles finalized; Railway/Render config (api, worker, admin, Postgres pgvector, Redis), release command runs migrations; 9.1.2 ☐ domains + TLS, widget on CDN path with cache headers; 9.1.3 ☐ env/secrets set; 9.1.4 ☐ `scripts/smoke_prod.sh`
- Verify: `scripts/verify/p9_s1.sh` — runs smoke against `$PROD_URL` (health, login, widget config, webhook GET)
- Needs user: 👤 accounts, DNS, secrets
- Commit: `chore(deploy): production configuration`

#### 9.2 Staging environment & release flow — ☐ 👤
- Sub-steps: 9.2.1 ☐ staging mirror; 9.2.2 ☐ `deploy.yml` (tag → build → deploy → smoke); 9.2.3 ☐ release checklist doc incl. evals-live gate
- Verify: `scripts/verify/p9_s2.sh` — smoke against staging
- Commit: `ci: staging and release workflow`

#### 9.3 Institution onboarding runbook — ☐
- Sub-steps: 9.3.1 ☐ `docs/runbooks/onboard-institution.md`: intake checklist (docs to collect, fee sheet format, slots, team), WhatsApp number provisioning + display name, template approval timeline, widget install walkthrough per CMS, go-live checklist, first-week monitoring; 9.3.2 ☐ intake form template (DOCX/MD)
- Verify: `scripts/verify/p9_s3.sh` — docs exist; a dry run onboarding a 4th fictional institution via UI succeeds (Playwright)
- Commit: `docs: institution onboarding runbook`

#### 9.4 Demo script & data refresh — ☐ 👤
- Sub-steps: 9.4.1 ☐ 10-minute scripted demo per institution type (widget + WhatsApp + admin), with Roman Urdu moments and a fee recovery arc; 9.4.2 ☐ `make demo-reset` (reseed + warm cache); 9.4.3 ☐ sales one-pager (positioning vs ERPs)
- Verify: `scripts/verify/p9_s4.sh` — demo reset succeeds; scripted conversations pass in replay
- Needs user: 👤 rehearse demo
- Commit: `docs: demo script and reset tooling`

#### 9.5 Pilot operations — ☐
- Sub-steps: 9.5.1 ☐ support rotation + incident playbook; 9.5.2 ☐ weekly metrics report job (per institution) to operator; 9.5.3 ☐ feedback capture (flag answer → eval case) loop; 9.5.4 ☐ pilot success criteria doc (leads, bookings, PKR recovered, CSAT)
- Verify: `scripts/verify/p9_s5.sh` — weekly report job test; docs exist
- Commit: `feat(ops): pilot operations tooling and docs`

---

## §4 Session log

| Date | Session | Step(s) | What was done | Verification | Commit suggested |
|---|---|---|---|---|---|
| 2026-11-01 | S1 | 0.2 | docker-compose (pgvector pg16, redis, api/worker/admin profile), Dockerfiles, init.sql (extensions + non-owner `raabta_app` role), arq worker with `ping` job, `scripts/dev.sh`, `p0_s2.sh`; recorded D-12 = hybrid (user) | `p0_s2.sh` OK 12/12 | `chore: add docker-compose and dev scripts` |
| 2026-11-01 | S1 | 0.1 | Scaffolded api (uv, FastAPI /healthz, ruff/mypy/pytest), admin (Next 16 + shadcn), widget (esbuild + size check), root Makefile/.gitignore/.env.example/README, `scripts/verify/_lib.sh`, `p0_s1.sh`, `all.sh` | `p0_s1.sh` OK 14/14 | `chore: scaffold api, admin and widget workspaces` |
| 2026-11-01 | S1 | 0.0 | Plan drafted by Fable 5.1; reviewed by Opus 5.5: fixed widget streaming-before-check gap (D-11), flagged agent-model cost vs market (D-12, D-05) | files exist; review checklist (anatomy 16/16, 74 steps all have verify + commit) | `docs: add build plan, handoff tracker and CLAUDE.md` |

---

## §5 Decisions log

| ID | Date | Decision | Status | Notes |
|---|---|---|---|---|
| D-01 | 2026-11-01 | Embeddings: interface + default Voyage `voyage-3.5`, alt `bge-m3`; final by Phase 2 bake-off | **needs user confirm** | PLAN §4 |
| D-02 | 2026-11-01 | STT: interface + default OpenAI `gpt-4o-transcribe` (fallback `whisper-1`); bake-off in 6.4 | **needs user confirm** | PLAN §4 |
| D-03 | 2026-11-01 | WhatsApp: RaabtaAI-owned WABA, one number per institution; Embedded Signup deferred | **needs user confirm** | PLAN §4, §15.2 |
| D-04 | 2026-11-01 | Deploy target: Railway (fallback Render / VPS+compose) | **needs user confirm** | PLAN §22 |
| D-05 | 2026-11-01 | Plan pricing & caps: draft suggested PKR 30k/60k/120k tiers — review flagged this is far above Pakistani market (competitors PKR 1.5k–9k/month); depends on D-12 | **needs user decision** | PLAN §19 |
| D-06 | 2026-11-01 | Opus 5.5 for agent (effort low/medium by complexity), Haiku 5.5 for classifiers; official SDK; no langchain-anthropic | decided | PLAN §4, §8 |
| D-07 | 2026-11-01 | Context: append-only within turn; simple compaction across turns; no thinking replay | decided | PLAN §7 |
| D-08 | 2026-11-01 | Numbers only from approved facts tables, never from chunks | decided | PLAN §11 |
| D-09 | 2026-11-01 | Fee reminders are templates (no LLM); LLM only for replies, tone-checked | decided | PLAN §6.2, §16 |
| D-10 | 2026-11-01 | Phase order: KB → agent → widget → admin → WhatsApp → fees | decided | HANDOFF §2 |
| D-11 | 2026-11-01 | Widget uses check-then-send (status events, then approved text) — never stream the unchecked draft | decided (plan review) | PLAN §8, §15.1 |
| D-12 | 2026-11-01 | **Hybrid agent routing**: router `complexity=simple` (FAQ: fees, timings, transport, greetings) → `claude-haiku-5-5` agent with the same tools + answer_check; `complex` (booking, fee module, multi-step, unhappy/escalation, low router confidence) → `claude-opus-5-5`. Eval gate in 3.9 compares simple-route quality Haiku vs Opus; if Haiku fails thresholds, try `claude-sonnet-5-5` for simple route. Implemented via `models_registry` keys `agent_simple` / `agent_complex` | **decided by user 2026-11-01** | PLAN §7, §19; unblocks D-05 |

---

## §6 Known issues / open questions

| ID | Raised | Issue / question | Status |
|---|---|---|---|
| I-01 | 2026-11-01 | Urdu PDF text extraction quality unknown until real prospectuses are tested; vision-OCR fallback planned (2.2.4) | open |
| I-02 | 2026-11-01 | Meta per-message template rates for Pakistan must be checked on the current rate card before pricing plans | open |
| I-03 | 2026-11-01 | Haiku 5.5 has no server-side refusal fallback — classifier nodes use safe-default verdicts on `refusal` | noted |
| I-04 | 2026-11-01 | Minimum cacheable prefix is 512 tokens on Opus/Haiku 5.5 per current docs; design keeps global prompt > 1k anyway | noted |
| I-05 | 2026-11-01 | Preserved-thinking prefix check is enforced for accounts created on/after 2026-08-31 — confirm account age; design is append-only regardless | open |

---

## §7 User action queue (external tasks, no repo changes)

| # | Task | Needed by | Status |
|---|---|---|---|
| U-01 | Meta Business Manager + business verification started | Phase 6 (start now) | ☐ |
| U-02 | Meta app (Business) with WhatsApp product; App ID/Secret | 6.1 | ☐ |
| U-03 | Phone numbers for pilots + dev test number | 6.1 | ☐ |
| U-04 | Anthropic API key + spend cap; GitHub secret for evals-live | 3.1 / 3.9 | ☐ |
| U-05 | Voyage (or chosen) embeddings key | 2.4 | ☐ |
| U-06 | STT provider key + 20 sample voice notes | 6.4 | ☐ |
| U-07 | Confirm decisions D-01…D-05 | Phase 2 | ☐ |
| U-08 | Domain + hosting account | 9.1 | ☐ |
| U-09 | Sentry projects | 8.2 | ☐ |
| U-10 | Sample redacted fee receipts (HBL/JazzCash/Easypaisa) | 7.5 | ☐ |
