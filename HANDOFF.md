# RaabtaAI — HANDOFF (living execution tracker)

> **Every session reads this file first and updates it last.** Reference design: `docs/PLAN.md` (read only the §
> a step points to). Rules: `CLAUDE.md`. Claude never commits/pushes — each step ends with a one-line commit message
> for the user.

---

## §0 Current status / Next action

| Field | Value |
|---|---|
| Phase / step in progress | **Phase 6 code complete** (2026-11-04) · 👤 6.1 Meta setup (blocked by business verification U-01), 6.4 STT bake-off (key + samples), 6.5 template wording review + submission |
| Last completed step | Phase 5 verified on the DB (`p5_s4`, `p5_s11` OK — fixed staff-reply 422, a11y, e2e races) · Phase 6 (2026-11-04): signed webhook + idempotent events → worker → `run_inbound`; single queued→deliver outbound path with 24h window; statuses; voice notes behind STT interface; templates (0005) + admin page + Meta submit/sync; widget-code linking; follow-ups/booking reminders/daily summary cron; policy gate (opt-out, quiet hours + Jumma, weekly cap, plan hold); privacy line; runbook |
| Last verification run | 2026-11-04 (end of S7): `p5_s1` OK, `p5_s4` OK, `p5_s11` OK (incl. templates page + WhatsApp settings), `p6_s2` OK. Not run: `p6_s1` (needs Meta token + public URL) |
| Next action | 👤 Meta: finish business verification (U-01) → token + webhook → `bash scripts/verify/p6_s1.sh https://<public-host>/api/v1/webhooks/whatsapp`; 👤 review default templates (Admin → Templates → "Add default set") then submit; 👤 STT bake-off (U-06). Then **Phase 7 (fee recovery)** — does not need Meta to build (templates + FakeLLM). Still pending: `bash scripts/verify/p3_s9.sh --live` (first live eval) |
| Blocked on user | Live WhatsApp (U-01/I-07), STT key + samples (U-06), Voyage billing (U-14) and prospectus (U-12) before pilots |
| Open decisions needing user confirmation | D-05 pricing (after 3.9 evals), D-02 STT, D-03 WhatsApp number model; D-01 decided (Voyage), D-04 decided |

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
| 0 Foundations | scaffold, tooling, compose, config, CI, Meta kickoff | 0.0–0.6 (7) | ☑ |
| 1 Data & multi-tenancy | models, migrations, RLS, auth/RBAC, seeds, isolation tests | 1.1–1.7 (7) | ☑ (2026-11-02) |
| 2 Knowledge base | ingestion, chunking, embeddings, hybrid search, facts, citations | 2.1–2.8 (8) | ☑ (2026-11-02) |
| 3 Agent core + evals | Claude wrapper, prompts, skills, tools, graph, guards, context, eval harness, CLI | 3.1–3.10 (10) | ◐ all ☑ except first live eval (2026-11-03) |
| 4 Widget + chat API | public chat API (SSE), widget bundle, booking/lead UI, embed tests | 4.1–4.4 (4) | ☑ (2026-11-03) · 👤 visual check |
| 5 Admin panel | Next.js foundation, onboarding, dashboard, inbox, leads, slots, KB, settings, super-admin, audit/usage, quality pass | 5.1–5.11 (11) | ☑ (2026-11-04; `p5_s4` + `p5_s11` OK) · 👤 visual/Urdu review |
| 6 WhatsApp | Meta app, webhook, sender + 24h window, voice notes, templates, handoff, follow-ups, channel guards | 6.1–6.8 (8) | ◐ code ☑ (2026-11-04, `p6_s2`); 👤 6.1 Meta, 6.4 bake-off, 6.5 submission |
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

#### 0.3 Config, model registry, logging — ☑ (2026-11-01)
- PLAN §4, §8, §19
- Sub-steps:
  - 0.3.1 ☑ `app/core/config.py` pydantic-settings: DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY, EMBEDDINGS_*, STT_*, META_*, JWT secrets, ENV, TZ default `Asia/Karachi`; fail-fast validation
  - 0.3.2 ☑ `app/core/models_registry.py`: `MODELS` (**D-12: `agent_simple` = `claude-haiku-5-5`, `agent_complex` = `claude-opus-5-5`**; extractor/vision/judge = `claude-opus-5-5`; guard/router/answer_check/tone/summarizer = `claude-haiku-5-5`), `EFFORT` per node, `MAX_TOKENS` per node, env override `RAABTA_MODEL_<NODE>`
  - 0.3.3 ☑ `app/core/logging.py` structlog JSON + request_id middleware; `/readyz` checks db+redis
- Acceptance: missing required env → startup error with clear message; registry unit test asserts pinned IDs and explicit effort for every node
- Verify: `scripts/verify/p0_s3.sh` — `pytest tests/unit/test_config.py tests/unit/test_models_registry.py`; readyz 200 with compose
- Commit: `feat(core): settings, model registry and structured logging`
- Done notes: `Settings` (pydantic-settings) reads env + repo-root `.env`; **env vars override `.env`**; empty values = unset; prod validator requires real JWT secret + provider keys; `get_settings()` raises `SettingsError` naming fields only (never values). `models_registry.spec_for(node)`: hybrid D-12 keys, explicit effort for all 10 nodes, `RAABTA_MODEL_<NODE>` override. structlog JSON + `X-Request-ID` ASGI middleware. `/readyz` checks DB + Redis (503 on failure). Test env in `tests/conftest.py` (unit tests never need `.env`); new pytest marker `integration` (excluded by default, run by verify scripts with `IT_DATABASE_URL`/`IT_REDIS_URL`).

#### 0.4 CI pipeline — ☑ (2026-11-01)
- PLAN §20
- Sub-steps:
  - 0.4.1 ☑ `.github/workflows/ci.yml`: jobs api (ruff, mypy, pytest with postgres+redis services), admin (lint, typecheck, test, build), widget (build + size ≤ 30KB gz), security (pip-audit, pnpm audit, gitleaks)
  - 0.4.2 ⏭ deferred (user: minimal CI) → `.github/workflows/evals-live.yml` skeleton (manual dispatch + label `run-evals`; requires secret; no-op until Phase 3)
  - 0.4.3 ⏭ deferred (user: minimal CI) → pre-commit config (ruff, prettier, gitleaks)
- Acceptance: workflow YAML validates (`act -n` or `actionlint`); local `make lint test` mirrors CI
- Verify: `scripts/verify/p0_s4.sh` — `actionlint` (installed via brew) on workflows; `make lint`; `make test`
- Needs user: 👤 push to GitHub to see first green run (user commits); report the run URL
- Commit: `ci: add minimal lint, type, test and build workflow`
- Done notes (scope cut by user: "very minimal CI"): one workflow `.github/workflows/ci.yml`, jobs `api` (ruff, format, mypy, unit pytest) and `web` (admin lint/typecheck/build, widget typecheck/build/size). Deferred to Phase 8: security scans (pip-audit/pnpm audit/gitleaks), service-backed integration tests, `evals-live`, pre-commit. Verify lints the workflow with actionlint via Docker (no local install).

#### 0.5 Docs & ADR scaffolding — ☑ (2026-11-01)
- Sub-steps: 0.5.1 ☑ `docs/adr/0001-stack.md`, `0002-embeddings.md` (pending bake-off), `0003-whatsapp-number-model.md`; 0.5.2 ⏭ deferred to 8.7 `docs/runbooks/README.md` index; 0.5.3 ☑ README links to PLAN/HANDOFF/CLAUDE
- Verify: `scripts/verify/p0_s5.sh` — files exist, markdown lint (`markdownlint-cli2` optional)
- Commit: `docs: add ADR index and free-hosting ADR`
- Done notes: decisions stay in §5; ADRs only when rationale is long. ADR 0001: Netlify can host admin + widget only; API/worker/DB/Redis need a separate always-on free host (pick in 9.1).

#### 0.6 User kickoff tasks (external) — ☑ (2026-11-02)
- PLAN §15.2, §4
- Sub-steps (user):
  - 0.6.1 ☐ Create Meta Business Manager, start **business verification** (registration docs, utility bill); create Meta app (Business type), add WhatsApp product; note App ID, App Secret
  - 0.6.2 ☐ Decide number model (D-03); buy/allocate one phone number per pilot institution (not registered on WhatsApp app); keep test number for dev
  - 0.6.3 ☐ Anthropic API key (+ monthly spend cap in console), Voyage AI key (or chosen provider), STT provider key; put in local `.env` (never in repo)
  - 0.6.4 ☐ GitHub repo secrets: `ANTHROPIC_API_KEY` (for `evals-live`), Sentry DSNs later
  - 0.6.5 ☐ Domain decision (e.g. `raabta.ai`) and Railway/Render account (D-04)
- Verify: `scripts/verify/p0_s6.sh` — checks `.env` has non-empty `ANTHROPIC_API_KEY`, `META_APP_SECRET`, `META_VERIFY_TOKEN` placeholders (does not call APIs); session asks user to confirm Meta verification status
- Commit: `chore: add env template and provider key checker`
- Progress: `.env` created from `.env.example` (git-ignored, chmod 600); `api/scripts/check_keys.py` (run `cd api && uv run python -m scripts.check_keys [--live]`) shows which keys are set and **whether they come from the shell or `.env`**; `--live` validates the Anthropic key + pinned models via the free Models API.
- ⚠ The user's `~/.zshrc` exports `ANTHROPIC_API_KEY`, which **overrides `.env`** (env > dotenv). User to decide which key RaabtaAI uses (see I-06). `scripts/dev.sh` no longer sources `.env` (would blank shell keys).
- Done 2026-11-02: user added keys; `LIVE=1 bash scripts/verify/p0_s6.sh` → OK (key valid, both pinned models available). Meta: developer app `RaabtaAi` + new business portfolio created; **business verification deliberately postponed** (user clicked "Verify later"); required before pilots go live (tracked U-01, step 6.1). **Correction 2026-11-02:** the test number is blocked too — see I-07.

---

### Phase 1 — Data & multi-tenancy

#### 1.1 Core tables & Alembic baseline — ☑ (2026-11-02)
- PLAN §13
- Sub-steps:
  - 1.1.1 ☑ `app/db/base.py` (UUID pk, timestamps, `TenantMixin` with `institution_id`), `session.py` (async engine, request-scoped session)
  - 1.1.2 ☑ models: `institutions`, `users`, `memberships`, `plans`, `audit_log`, `usage_daily`, `webhook_events`
  - 1.1.3 ☑ Alembic async env; migration `0001_baseline`; `make migrate`
- Acceptance: `alembic upgrade head` on empty DB creates tables; `alembic downgrade base` clean; model/migration drift check (`alembic check`) passes
- Verify: `scripts/verify/p1_s1.sh` — upgrade/downgrade/upgrade on testcontainer; `pytest tests/integration/test_migrations.py`
- Commit: `feat(db): core tenant tables and alembic baseline`
- Done notes: `app/db/base.py` (naming convention for stable constraint names, `UUIDPkMixin` w/ `gen_random_uuid()`, `TimestampsMixin`, `TenantMixin`, `enum_check` = VARCHAR+CHECK; allowed values in `app/models/enums.py`). Models in `app/models/core.py` (+ `users.email` must be lowercase CHECK; `usage_daily` PK (institution_id, date)). `app/db/session.py` `get_session` dependency (one transaction per request); `Resources` now holds `sessionmaker`. Alembic async in `api/migrations/` (URL: `-x url=` > `MIGRATIONS_DATABASE_URL` > .env; post-write hook runs ruff format); migration `0001` also creates extensions (not dropped on downgrade). Tests use a disposable DB `raabta_test` (recreated by the verify script); dev DB migrated with `make migrate`. Verify uses compose Postgres instead of testcontainers (faster, same image).

#### 1.2 Auth & RBAC — ☑ (2026-11-02)
- PLAN §4 (Auth), §18
- Sub-steps:
  - 1.2.1 ☑ argon2 password hashing; login/logout/refresh (rotating refresh in httpOnly cookie); access JWT 15m
  - 1.2.2 ☑ `require_role(owner|admin|staff)` dependency; `require_superadmin`; active institution from `X-Institution` validated against membership
  - 1.2.3 ☑ invitations (create, accept), lockout after 10 failures (Redis), password rules
  - 1.2.4 ☑ `app/api/auth.py`, `members.py`; audit rows on member changes
- Acceptance: tests for login, refresh rotation, role gating (403), invitation flow, lockout
- Verify: `scripts/verify/p1_s2.sh` — `pytest tests/integration/test_auth.py tests/integration/test_members.py`
- Commit: `feat(auth): jwt sessions, rbac and invitations`
- Done notes: `app/core/security.py` (argon2id, rules: ≥10 chars, letters+digits, ≠ email; HS256 access JWT `sub/typ/iat/exp/jti`, no institution claim). `app/services/auth_tokens.py`: refresh tokens = opaque, Redis (`auth:rt:<sha256>`), rotation via atomic GETDEL, **reuse of a consumed token revokes the whole login family**; lockout per email-hash (10 fails / 15 min → 429 + Retry-After). Cookie `raabta_rt` httpOnly, SameSite=strict, Path=/api/v1/auth, Secure in prod. `app/api/deps.py`: `SessionDep` uses `Depends(get_session, scope="function")` — **commit before the response is sent** (FastAPI 0.162 default would commit after); `StaffCtx/AdminCtx/OwnerCtx` (rank owner>admin>staff); `X-Institution` missing/invalid → 400, not a member → 403. Invites: token hash + expiry on `memberships` (migration 0002); API returns `invite_url` (admin `/invite/accept#token=…`) — **no email sending in MVP**, admin shares the link; existing users accept with their current password. Owner rules: only owners grant/change/remove owner; ≥1 active owner kept (409). All routes under `/api/v1`.
#### 1.3 Tenant context & Row-Level Security — ☑ (2026-11-02)
- PLAN §18
- Sub-steps:
  - 1.3.1 ☑ DB roles `app_tenant` (RLS enforced) and `app_admin` (bypass); migration enabling RLS + policies on all tenant tables (template helper `enable_rls(table)`)
  - 1.3.2 ☑ `app/core/tenancy.py`: per-request `SET LOCAL app.institution_id` + `SET LOCAL ROLE app_tenant`; worker helper `tenant_session(institution_id)`
  - 1.3.3 ☑ ORM mixin auto-filter as second layer; lint rule/test that every tenant model has RLS policy
- Acceptance: query without GUC returns zero rows; cross-tenant insert rejected; superadmin path explicit
- Verify: `scripts/verify/p1_s3.sh` — `pytest tests/isolation/test_rls_basics.py`
- Commit: `feat(db): row-level security and tenant request context`
- Done notes: migration `0002` creates roles if missing (never dropped): `app_tenant` NOBYPASSRLS, `app_admin` BYPASSRLS, granted to `raabta_app` (admin WITH INHERIT FALSE) — **creating a BYPASSRLS role needs a superuser migration role** (true in compose; check at 9.1 hosting). SQL fn `app_current_institution()` = `NULLIF(current_setting('app.institution_id', true),'')::uuid`; `app/db/rls.py` `enable_rls(table)` = ENABLE + FORCE + one policy (USING + WITH CHECK); `GLOBAL_TABLES` allowlist (plans, users, webhook_events, LangGraph tables). `institutions` policy is on `id`. `users` is global on purpose (identity); tenants reach users only via memberships. Tenancy modes per transaction: `scope_to_tenant` (role + GUC via `set_config(..., true)` + ORM filter) / `scope_to_admin` (explicit, grep-able); switching tenant→admin or tenant A→B raises `TenancyError`; scope is cleared on outermost transaction end (event). ORM layer: `with_loader_criteria(TenantMixin, …)` on SELECT/UPDATE/DELETE + `before_flush` stamps/validates `institution_id` (AuditLog/UsageDaily are not TenantMixin → routes filter explicitly + RLS). Coverage lint: `test_every_tenant_table_has_rls_policy` (any table with `institution_id` must have forced RLS + policy).
#### 1.4 Conversation domain tables — ☑ (2026-11-02)
- PLAN §13
- Sub-steps: 1.4.1 ☑ `contacts`, `conversations`, `messages`, `llm_runs`, `leads`, `slots`, `bookings`, `followups`; 1.4.2 ☑ migration `0003_conversation_domain_tables` (0002 went to auth/RLS); 1.4.3 ☑ repositories/services with tenant scoping; 1.4.4 ☑ LangGraph checkpoint tables created in migration
- Acceptance: CRUD tests; unique `(institution_id, wa_id)`; indexes present
- Verify: `scripts/verify/p1_s4.sh` — `pytest tests/integration/test_conversation_models.py`
- Commit: `feat(db): contacts, conversations, messages, leads, slots`
- Done notes: models in `app/models/conversations.py`; all 8 tables RLS'd in 0003. `messages.seq` (BIGINT identity) = transcript order (timestamps tie inside a transaction). `conversations.thread_id = "{institution_id}:{contact_id}"` (not unique: shared across a contact's conversations). `messages.wa_message_id` unique; `(conversation_id, client_msg_id)` unique (widget idempotency). Slots: CHECK `0 ≤ booked_count ≤ capacity`; `services/bookings.book_slot` = one atomic `UPDATE … WHERE booked_count < capacity RETURNING` (6-char codes without 0/O/1/I). `services/conversations.py`: get_or_create_contact / open_conversation / add_message / list_messages (tenant session required). **LangGraph tables**: `PostgresSaver.setup()` uses `CREATE INDEX CONCURRENTLY`, which deadlocks inside a migration → 0003 replays the library's `MIGRATIONS` list without CONCURRENTLY and records versions in `checkpoint_migrations` (later `setup()` = no-op / only newer migrations); excluded from autogenerate via `include_name` in `migrations/env.py`.
#### 1.5 Seed three demo institutions — ☑ (2026-11-02)
- PLAN §1 (demo data), §13
- Sub-steps:
  - 1.5.1 ☑ `seeds/abc_grammar_school/` — profile (Lahore, school, tz, hours, quiet hours), classes Playgroup→Matric, fee structure XLSX (admission PKR 25,000; security 20,000 refundable; monthly 9,500–16,500 by class; annual charges 12,000; transport routes: DHA, Gulberg, Johar Town, Model Town PKR 6,000–8,500/month), prospectus DOCX (campus, timings, uniform, policies), slots (campus visits Mon–Sat 10:00–13:00), 12 contacts/leads, session 2026–27 dates (admissions Feb–Apr 2027)
  - 1.5.2 ☑ `seeds/punjab_model_college/` — college: FSc Pre-Med, Pre-Eng, ICS, ICom; eligibility (matric ≥ 60%, pre-med ≥ 70%), fees (admission 15,000; monthly 8,000–11,000), merit-based scholarships (≥ 90% → 50%), counselling slots, admission dates after BISE results (Aug–Sep 2027), hostel: none, transport routes
  - 1.5.3 ☑ `seeds/lits_university/` — university: BS CS, BS SE, BS BBA, BS EE, MS CS; eligibility (FSc ≥ 50–60%, entry test), semester fees (BS CS PKR 145,000/semester; BBA 120,000), merit list rounds, deadlines (Fall 2027: apply by 15 Jul), hostel PKR 35,000/semester, scholarships (need-based up to 100%, merit 25–75%), online application URL
  - 1.5.4 ☑ `scripts/seed.sh` / `app/cli.py seed --institution all --reset`; demo users (owner/admin/staff per institution, superadmin)
- Acceptance: seed idempotent; 3 institutions + users + facts rows + documents files on disk (ingestion runs in Phase 2)
- Verify: `scripts/verify/p1_s5.sh` — run seed twice; counts match expected; login as each demo user via test client
- Commit: `feat(seeds): three demo institutions with realistic PKR data`
- Done notes: one `api/seeds/<name>/seed.yaml` per institution (validated by `app/seeds/schema.py`) = single source for profile, users, slot rules, contacts+leads, **facts** (fee_items, programs, transport, key dates, scholarships) and prospectus text; `docs/fee_structure.xlsx` + `docs/prospectus.docx` are generated from it (`uv run python -m app.cli seed-docs [--force]`; Urdu sections right-aligned). Facts **rows** can't exist until the facts tables in 2.6 — 2.6.5 should load `seed.yaml` facts / the XLSX into them. Load: `scripts/seed.sh` / `make seed` (`--reset`, `--institution <slug>`): upserts institution/users/memberships, replaces demo tenant data; slots = rule × N weeks from next Monday (local tz → UTC). Counts: ABC 12 contacts/72 visit slots, PMC (Faisalabad) 8/90 counselling, LITS 10/8 entry-test slots. Demo logins: `owner|admin|staff@{abc,pmc,lits}.demo.raabta.pk`, superadmin `super@raabta.pk`, password = `SEED_DEMO_PASSWORD` or dev default `Raabta-demo-2027` (prod refuses without env). Dev DB is seeded.
#### 1.6 Audit log & usage events plumbing — ☑ (2026-11-02)
- PLAN §10 (G15), §19
- Sub-steps: 1.6.1 ☑ `audit(action, entity, before, after)` service + middleware for mutating admin routes; 1.6.2 ☑ `usage_daily` rollup job skeleton (arq cron nightly) + `record_usage()` helper; 1.6.3 ☑ `GET /audit-log`, `GET /usage`
- Acceptance: member change creates audit row; rollup aggregates sample rows
- Verify: `scripts/verify/p1_s6.sh` — `pytest tests/integration/test_audit.py tests/integration/test_usage_rollup.py`
- Commit: `feat(core): audit log and usage rollup`
- Done notes: `services/audit.py` `audit()/audit_ctx()/snapshot()` (redacts password/token fields). "Middleware" = router dependency `audit_mutations` (in `api/deps.py`, scope=function): a successful POST/PUT/PATCH/DELETE that didn't call `audit()` gets a generic `"<METHOD> <route>"` row **in the same transaction**; failed requests leave no rows. **Every tenant router must include `dependencies=[audit_mutations]`.** `services/usage.py`: `record_usage()` = upsert-increment (live counters); `rollup_usage(day)` = one SQL statement recomputing the day for all institutions using each institution's timezone, overwrites (idempotent), keeps `fee_recovered_pkr`. Worker: `rollup_usage_job` cron 00:30 Asia/Karachi (yesterday), worker now has DB startup/shutdown. `GET /audit-log` (admin+, newest first, `entity/action/before/limit≤200`), `GET /usage?from&to` (admin+, ≤366 days, + totals).
#### 1.7 Tenant isolation test suite — ☑ (2026-11-02; 1.7.3 deferred)
- PLAN §18, §20
- Sub-steps: 1.7.1 ☑ `tests/isolation/` fixtures: two institutions, users per role; 1.7.2 ☑ parametrized attempts: read/update/delete other tenant's rows via every existing endpoint (auto-discovered from app routes) → expect 404/403 and zero leakage; 1.7.3 ⏭ CI job `isolation` — deferred to Phase 8 with the other service-backed CI jobs (minimal-CI decision 2026-11-01; see I-08)
- Acceptance: 100% of endpoints covered (route coverage assertion), all pass
- Verify: `scripts/verify/p1_s7.sh` — `pytest -m isolation`
- Commit: `test: cross-tenant isolation suite`
- Done notes: shared fixtures in `tests/support.py` (`Factory.tenant()/atenant()`, `as_admin`, `as_tenant`, `auth_headers`); integration/isolation conftests re-export them. `tests/isolation/test_endpoints.py` discovers routes from the **OpenAPI schema** (FastAPI 0.162 wraps included routers lazily, `app.routes` doesn't list them). Per tenant route: foreign `X-Institution` → 403 with B unchanged; foreign path ids → 404 with B unchanged; list GETs contain none of B's ids/emails. `test_every_route_is_classified` fails on any new route until it is listed in `PUBLIC_ROUTES` or has `ID_RESOLVERS`/`SAMPLE_BODIES`. Mutation check done: removing the membership filter in `get_tenant` makes 6 cases fail.
---

### Phase 2 — Knowledge base

#### 2.1 Document upload & storage — ☑ (2026-11-02)
- PLAN §13 (`documents`), §18 (uploads)
- Sub-steps: 2.1.1 ☑ `BlobStore` interface (local FS impl; S3-compatible impl stub); 2.1.2 ☑ `POST /kb/documents` multipart (PDF/DOCX/XLSX/CSV; MIME sniff; 25MB cap; checksum dedupe; versioning), list/get/delete; 2.1.3 ☑ status machine on `documents`
- Verify: `scripts/verify/p2_s1.sh` — `pytest tests/integration/test_kb_documents.py` (upload seed files, reject exe, version bump) + 0004 round-trip/drift
- Commit: `feat(kb): document upload, storage and versioning`
- Done notes: migration `0004` = `documents`, `chunks`, 5 fact tables, all RLS'd. `app/kb/blobstore.py` (`LocalBlobStore` atomic writes + path-escape guard under `BLOB_DIR`, default `var/blobs` (git-ignored); `S3BlobStore` raises until 9.1). `app/kb/sniff.py` decides type from bytes (PDF magic, OOXML zip entries, CSV only with `.csv` name), never the client MIME. `services/kb_documents.py`: `create_document` (dedupe = same sha256 not superseded/failed → 409 with existing id; same title → version+1 + `supersedes_id`; refuses while previous version is in progress) + `upload` (audited). Upload/reindex enqueue the arq job via `BackgroundTasks` (= after commit). Statuses: uploaded → parsing → chunking → embedding → extracting → ready | failed | superseded. `Resources.redis` is now an `ArqRedis`; `Resources.blobstore` added.

#### 2.2 Parsers — ☑ (2026-11-02; PDF lib switched to pdfplumber + pypdfium2; vision-OCR not live-tested)
- PLAN §5 KNOW
- Sub-steps: 2.2.1 ☑ PDF via `pdfplumber` (layout, headings, tables) + `pypdfium2` (Urdu line text, page rendering) — PyMuPDF dropped (AGPL, I-11); 2.2.2 ☑ DOCX via `python-docx` (headings, tables → rows); 2.2.3 ☑ XLSX/CSV via `openpyxl`/stdlib csv (sheet → table rows with header); 2.2.4 ☑ Urdu quality heuristic → flag page; vision-OCR fallback `app/kb/ocr.py` behind `KB_VISION_OCR=1` (unit-tested plumbing only)
- Verify: `scripts/verify/p2_s2.sh` — `pytest tests/unit/test_parsers.py`
- Needs user: 👤 vision-OCR on a real scanned/InPage Urdu PDF spends tokens — ask before running (no such PDF in seeds)
- Commit: `feat(kb): pdf, docx and xlsx parsers with urdu quality check`
- Done notes: `app/kb/parsers/` → `ParsedDoc{blocks[Block(page, kind heading|para|row, text, level, table)], pages, flagged_pages, notes}` (JSON round-trip; stored as `parsed.json` next to the original). PDF headings = font ≥1.2× body median or short all-bold line; page flagged if replacement/PUA/presentation-form chars >5% of Urdu chars, or <30 chars on an image page. PDF (after the switch): pdfplumber groups words into lines (font size/bold → headings, wrapped headings merged, paragraph gaps from the page's median line gap) and `find_tables()` → row blocks; any line with Arabic script is re-read from its bbox with PDFium `get_text_bounded` (pdfminer returns Urdu reversed/presentation forms/NULs). Tested on Chrome-printed fixtures `tests/fixtures/prospectus_{naskh,nastaliq}.pdf` (`make_pdfs.sh`): **Naskh Urdu extracts cleanly; Nastaliq does not extract cleanly with any library (PyMuPDF included) → caught by the new fragmentation score (share of 1-letter Urdu tokens > 25%) and flagged for vision OCR**; known PDFium glitch: a short word in a heading may come out letter-swapped ("کا"→"اک"). `urdu_quality` = max(broken-glyph ratio incl. NUL, fragment ratio). Table rows rendered `Header: value | …` (self-describing for retrieval); header row = first all-text row with ≥60% width; single-cell rows above it = titles. DOCX page = 1 + page breaks. CSV numeric strings → ints (not with leading 0). Licences now: pdfplumber/pdfminer.six MIT, pypdfium2 BSD-3/Apache-2.0, Pillow MIT-CMU.

#### 2.3 Chunking — ☑ (2026-11-02)
- Sub-steps: 2.3.1 ☑ heading-aware chunker, 400–800 tokens, 15% overlap, page refs, table rows kept intact; 2.3.2 ☑ `text_norm` (lowercase, unaccent, Roman-Urdu normalization map); 2.3.3 ☑ language tag per chunk (script detection + Roman-Urdu marker words; no LLM); 2.3.4 ☑ injection-pattern pre-filter → `suspicious`
- Verify: `scripts/verify/p2_s3.sh` — `pytest tests/unit/test_chunking.py` (sizes, overlap, page refs, table rows)
- Commit: `feat(kb): heading-aware chunking and text normalization`
- Done notes: `app/kb/chunking.py`: small sections merge until ≥400 tokens (heading lines stay inline), a table is never merged with the section after it; overlap carries trailing units (or trailing sentences of one long paragraph) of the same section. Token count = estimate (Latin ≈4 chars/token, Urdu ≈2.5) — no tokenizer dep. `app/kb/text.py`: `normalize()` (NFKC, Arabic→Urdu letter folding, Urdu digits, diacritics, thousands separators, Roman-Urdu canon map e.g. dakhila→dakhla, fees→fee) used for chunks **and** queries; `detect_lang` → en/ur/roman_ur/mixed; `looks_like_injection` (EN/UR/RU patterns). Suspicious chunks are stored but excluded from search. Seed docs give ~2 chunks each (corpus is small).

#### 2.4 Embedding provider + bake-off — ☑ (2026-11-02; D-01 = Voyage)
- PLAN §4 (Embeddings), D-01
- Sub-steps: 2.4.1 ☑ `EmbeddingProvider` interface, `VoyageProvider`, `BGEM3Provider` (TEI endpoint), `FakeProvider`; 2.4.2 ☑ `chunks.embedding vector(1024)` + HNSW (cosine) in 0004; 2.4.3 ☑ `evals/datasets/retrieval.yaml` (60 Q: 20 EN/20 UR/20 RU; gold = verbatim substrings, not chunk UUIDs — stable across re-ingest); 2.4.4 ☑ `scripts/bakeoff_embeddings.py` run live (fake vs voyage, 60 Q): voyage hybrid recall@1 0.88 / MRR 0.94 / Urdu r@1 0.85 vs fake 0.83 / 0.91 / 0.70 → `docs/adr/0002-embeddings.md` **accepted**
- Verify: `scripts/verify/p2_s4.sh` — `pytest tests/unit/test_embeddings.py`; with `RAABTA_BAKEOFF=1` also seeds+ingests the test DB and runs the bake-off subset (fake vs voyage)
- Done (user approved 2026-11-02): `.env` → `EMBEDDING_PROVIDER=voyage`; dev DB re-embedded with `uv run python -m app.cli reembed` (new command); `make evals-retrieval` on dev: recall@1 0.92, Urdu 0.90, Roman Urdu 0.90
- Commit: `feat(kb): embedding provider interface and bake-off`
- Done notes: `EMBEDDING_DIM=1024` lives in `app/models/kb.py` (both candidates are 1024-d); provider picked by `EMBEDDING_PROVIDER` (default `fake`; prod refuses `fake`). Voyage via httpx REST (batches of 128, retries 429/5xx, client errors not retried, re-sorts by `index`, counts `total_tokens`). Chunks store `embedding_model`; `stage_embed` re-embeds rows whose model differs → provider switch = `reembed_all` / `app.cli reembed`. Voyage account has no billing → 3 RPM: provider waits ≥21 s on 429 (honours `retry-after`), evals pre-embed all queries in one call (`PrecomputedQueries`); `search.dense_query_text()` is the single definition of what the dense leg embeds.

#### 2.5 Hybrid search — ☑ (2026-11-02; gate met with the fake provider)
- PLAN §5 KNOW, §11
- Sub-steps: 2.5.1 ☑ `app/kb/search.py`: vector cosine (HNSW) + FTS (`tsv` generated from `text_norm`, `simple`) + `pg_trgm` word similarity per query word; RRF (k=60); top_k; RLS + explicit `institution_id`; 2.5.2 ☑ `seeds/ru_synonyms.csv` (~270 RU/Urdu→EN terms) + query expansion; 2.5.3 ☑ multi-query (1–3) fused; 2.5.4 ☑ `pack()` ≤ 2k tokens
- Acceptance: recall@5 ≥ 90%, Roman Urdu ≥ 85% — **met: 1.00 / 1.00** (recall@1 0.85, MRR 0.92; Urdu-script recall@1 0.75) with fake embeddings; saturated by the tiny corpus (I-12)
- Verify: `scripts/verify/p2_s5.sh` — `pytest tests/integration/test_search.py`; seeds+ingests the test DB; `python -m evals.run_evals --suite retrieval` (gate)
- Commit: `feat(kb): hybrid vector + keyword + trigram search with rrf`
- Done notes: FTS query = OR of normalized content words + synonym expansions (stopwords EN+RU removed), ranked `ts_rank_cd`; trigram leg = `sum(word_similarity(term, text_norm))` over `term <% text_norm` (threshold 0.5 via transaction-local `set_config`), GIN trgm index. Only chunks of `ready` docs and not `suspicious`. If the embedding API errors, the dense leg is skipped (lexical legs still answer). `make evals-retrieval` runs the gate on the dev DB.

#### 2.6 Structured facts extraction & approval — ☑ (2026-11-02; live run done)
- PLAN §5 KNOW, §7 (facts_extractor), §11 (2)
- Sub-steps: 2.6.1 ☑ `programs`, `fee_items`, `key_dates`, `scholarships`, `transport_routes` (in 0004); 2.6.2 ☑ `app/kb/facts_extractor.py` (Opus `facts_extractor` node, effort high, `parse` → `FactsBatch`, ≤20 pages / ≤40k tokens per batch, page refs + quotes; amounts as text → `app/kb/pkr.py`); 2.6.3 ☑ `GET /kb/facts/{kind}`, `PATCH /kb/facts/{kind}` (bulk approve/reject), `PATCH /kb/facts/{kind}/{fact_id}` (edit/status); 2.6.4 ☑ `facts_version` bump whenever served (approved) data changes; 2.6.5 ☑ XLSX/CSV → `fee_items`/`transport_routes` with no LLM when columns are recognized
- Acceptance: seed fee XLSX → rows match seed.yaml PKR exactly ✔; extractor ✔ **live Opus run** on the 3 seed prospectuses (user-approved; 3 calls, $0.16 total, ~15–25 s each, no refusal/fallback, 0 dropped rows): all 17 key dates match seed.yaml exactly, every fee amount correct (incl. 2 ABC heads present in the prospectus but not in seed.yaml), no invented scholarships; approval audited ✔
- Verify: `scripts/verify/p2_s6.sh` — `pytest tests/unit/test_facts_unit.py tests/integration/test_facts.py`
- Cassettes: real responses recorded in `api/evals/cassettes/facts_extractor/` (commit them); `test_recorded_real_extractor_cassettes_replay` replays them per institution — a prompt/schema/model/effort/parser change → missing cassette → re-record with `KB_FACTS_LLM=1 RAABTA_LLM_RECORD=1 uv run python -m app.cli ingest-seeds --no-approve` on a fresh DB (= a release)
- Commit: `feat(kb): structured facts extraction with admin approval`
- Done notes: `app/llm/claude.py` (early slice of 3.1): `ClaudeClient.parse(node, …)` — registry model/effort/max_tokens, Opus via `client.beta.messages.parse` + `server-side-fallback-2026-07-01` + `fallbacks="default"`, Haiku via `messages.parse`, `stop_reason` refusal → `RefusalError`, `max_tokens` → one retry ×1.5, SDK retries off + own backoff, cassettes keyed by sha256(model, effort, system, messages, schema) under `evals/cassettes/<node>/` (`RAABTA_LLM_RECORD/REPLAY`). `app/llm/cost.py` price table; extractor runs logged to `llm_runs`. Prompt `app/prompts/facts_extractor.md` (v1) + loader `app/prompts/__init__.py`. Fact rows: `status` pending/approved/rejected/superseded, `origin` table/llm/seed/manual, `ordinal` (source order), source doc/page/quote. Re-ingest replaces only *pending* rows of the same origin; a new document version supersedes the old version's approved facts (no longer served, bump) and drops its pending/rejected ones. Seeds: without `KB_FACTS_LLM`, `ingest-seeds` loads prospectus facts from `seed.yaml` (origin `seed`) and approves everything (demo only).

#### 2.7 Citations model — ☑ (2026-11-02)
- Sub-steps: 2.7.1 ☑ `app/kb/citations.py` `Citation{document_id,title,page,chunk_id,quote}` + `label()`/`make_quote()`; 2.7.2 ☑ `SearchHit.citation()`; `FactOut.source` citation; 2.7.3 ☑ `POST /kb/playground` (staff+) → fused chunks with leg ranks + citations, matching approved facts (ranked by matched terms), `packed_tokens`
- Verify: `scripts/verify/p2_s7.sh` — `pytest tests/unit/test_citations.py tests/integration/test_playground.py`
- Commit: `feat(kb): citation schema and playground retrieval endpoint`
- Done notes: playground marks itself audited (read-only POST → no audit row). Facts lookup there is lexical (ILIKE + whole-word scoring); typed `get_*` tools for the agent come in 3.4.

#### 2.8 Ingestion pipeline (arq) & KB evals — ☑ (2026-11-02)
- PLAN §5 STEER (workflows), §12
- Sub-steps: 2.8.1 ☑ `app/kb/ingest.py` stages parse→chunk→embed→extract→finalize(ready) with status + error capture; re-index endpoint; supersede atomically at ready; 2.8.2 ☑ idempotent + resumable per stage (`meta.failed_stage`; embeddings committed per batch of 64); 2.8.3 ☑ `make ingest-seeds` (`app.cli ingest-seeds`, idempotent); 2.8.4 ◐ retrieval eval runnable (`make evals-retrieval`, verify scripts) — wiring into the `evals-smoke` CI job waits for 3.9 (CI has no DB yet, I-08)
- Verify: `scripts/verify/p2_s8.sh` — pipeline tests; ingest-seeds (6 docs ready) twice (idempotent); real `arq --burst` worker consumes an enqueued job; retrieval gate
- Commit: `feat(kb): ingestion pipeline with re-index and retrieval evals`
- Done notes: worker job `ingest_document_job(institution_id, document_id)` with Redis lock `kb:ingest-lock:<doc>` (30 min). Re-index of a `ready` doc = new version of the same file (old keeps serving until the new one is ready); of a `failed` doc = resume same row; refused (409) while processing or when a newer version exists. Dev DB: migrated to 0004 and `make ingest-seeds` done (fake embeddings).

---

### Phase 3 — Agent core + eval harness

#### 3.1 Claude client wrapper — ☑ (2026-11-03; live smoke OK)
- PLAN §8; CLAUDE.md API rules
- Sub-steps: 3.1.1 ☑ `app/llm/claude.py`: `parse` (unchanged cassette key) + `complete` + `stream` (streaming endpoint, `on_tool_start` hook for widget status events); Opus via `client.beta.messages` + `server-side-fallback-2026-07-01` + `fallbacks="default"`, Haiku via `client.messages`; explicit effort; `tool_choice auto` only when tools; no sampling/thinking/prefill; 3.1.2 ☑ jittered backoff (429, ≥500 incl. 529, connection/timeouts), 4xx raised, per-node timeouts (`TIMEOUTS`); 3.1.3 ☑ `refusal` → `RefusalError(category)` + structlog `llm.refusal`, `max_tokens` → one retry ×1.5 then `LLMError`; 3.1.4 ☑ `LLMResult.usage_record()` + `app/llm/runs.py` (`run_record` JSON for graph state → `to_row` LlmRun incl. cache tokens, fallback flag, prompt hash, skill tags, error); 3.1.5 ☑ cassettes for `complete` (hash of model/effort/system/messages/tools without cache markers); 3.1.6 ☑ `TurnPrefixGuard` (tools/system identical + messages append-only within a turn; cache markers ignored) used by the agent loop; `with_message_breakpoint` adds the 4th cache breakpoint on the last user block
- Also: `app/llm/base.py` `LLMProvider` protocol; `app/llm/fake.py` `FakeLLM` (scripted per node; `tool_call`/`text_reply` helpers) for tests
- Verify: `scripts/verify/p3_s1.sh` (mocked SDK, 12 tests); `p3_s1.sh --live` runs `uv run python -m scripts.llm_smoke` (2 identical-prefix Haiku calls + 1 router parse; expects `OK: cache hit on second call`)
- Live smoke (user-approved): call 1 cache_write 2707 → call 2 cache_read 2707 (cost $0.00003); router parse OK → `OK: cache hit on second call`
- Commit: `feat(llm): anthropic client wrapper with retries, fallback and cost logging`

#### 3.2 Prompt files & loader — ☑ (2026-11-03)
- Sub-steps: 3.2.1 ☑ loader validates front-matter (`name, version semver, model_key, cacheable, changelog`; effort/max_tokens must equal the registry), body hash, `tag`; 3.2.2 ☑ `system_global.md`, `agent_admissions.md`, `agent_fees.md`, `router.md` (12 code-mixed few-shot), `guard_in.md`, `answer_check.md`, `tone_check.md`, `summarizer.md`, `tenant_block.md.j2` (jinja2, StrictUndefined, `dictsort`), + `judge_admissions.md` (3.9); `facts_extractor.md` front-matter migrated (body untouched → recorded cassettes still replay); 3.2.3 ☑ `app/agent/phrases.py` (fallback/blocked/off_topic/handoff/rate_limited/daily_cap/opted_out/error × en/ur/roman_ur; `mixed`→roman_ur); 3.2.4 ☑ tests
- Verify: `scripts/verify/p3_s2.sh`
- Commit: `feat(agent): versioned prompt files and loader`

#### 3.3 Skills loader & skill packs — ☑ (2026-11-03)
- Sub-steps: 3.3.1 ☑ `app/agent/skills_loader.py` (`skill.yaml` strict schema, `select(TurnFacts)` = rule match ∪ router hints that fit institution/module/node, order priority desc + name, 1.5k-token budget; `available_for_router`); 3.3.2 ☑ 9 packs (240–440 tokens each); 3.3.3 ☑ selection matrix + cap tests
- Verify: `scripts/verify/p3_s3.sh`
- Commit: `feat(agent): skills loader and skill packs`

#### 3.4 Tool registry & tools — ☑ (2026-11-03)
- Sub-steps: 3.4.1 ☑ `app/agent/registry.py` (strict schema = SDK `transform_schema` + all properties required/nullable + `additionalProperties:false`; permission gate; module subsets name-sorted; each call in its own `tenant_session`; `ToolError` → model-facing `is_error`, other exceptions → generic `is_error`; `execute_all` = `asyncio.gather` in order; `Source` registry on `ToolContext`); 3.4.2 ☑ admissions tools (`app/agent/tools/{knowledge,facts,leads,booking}.py`); 3.4.3 ☑ `handoff_to_human`, `set_contact_language`; fee tools registered with gates, implementation raises "not enabled → hand off" (Phase 7); 3.4.4 ☑ `GET /api/v1/internal/tools` (staff+, MCP-style manifest; auto-covered by the isolation suite)
- Verify: `scripts/verify/p3_s4.sh` — schema snapshot `tests/unit/snapshots/tool_schemas.json` (`UPDATE_SNAPSHOTS=1` to accept = release) + DB tests (approved-only facts, tenant scoping, lead dedupe, capacity, follow-ups)
- Commit: `feat(agent): strict tool registry and admissions tools`
- Done notes: the model never sees DB ids: sources are `S-xxxxxx`/`F-xxxxxx` (sha1 of content → stable across re-ingest), slots are local `slot_time` strings ("2026-11-04 10:00") passed back to `book_visit`. Facts filtering is deterministic whole-word matching; school-wide "All classes" heads are added to a class query; no match → full table + note. Phones normalized to E.164 (`normalize_pk_phone`); invalid → `is_error`, nothing saved.

#### 3.5 LangGraph inbound graph — ☑ (2026-11-03)
- Sub-steps: 3.5.1 ☑ `app/agent/state.py` (JSON-only; `turn_input` resets per-turn keys), `app/agent/graph.py` (`build_graph(deps, checkpointer)`; nodes are closures over `AgentDeps`), `app/agent/inbound.py` `postgres_checkpointer` (psycopg pool, tables from migration 0003); 3.5.2 ☑ nodes guard_in · safe_reply · router · load_context · agent (≤ 6 model calls, append-only, parallel tool_results in one message, repair via appended `role:system` note) · answer_check · safe_fallback · handoff · compose · persist · summarize · await_staff (`interrupt()`); 3.5.3 ☑ human-mode gate in `run_inbound`; `resume_after_handoff` (mode=ai + `Command(resume={"staff_note"})`, falls back to the last staff messages); 3.5.4 ☑ `run_inbound(deps, graph, InboundEvent)` → `TurnResult` (dedupe, opt-out/in, rate limit, daily cap, per-thread Redis lock)
- Verify: `scripts/verify/p3_s5.sh` — `tests/integration/test_graph.py` (11 tests, FakeLLM + real RLS DB + Postgres checkpointer; was planned as unit — needs DB for persist/tools)
- Commit: `feat(agent): langgraph inbound graph with human takeover`
- Done notes: LLM failures degrade (guard → block, router → general/simple, checker → fail, agent refusal → fallback phrase, API error → error phrase); `CassetteMissingError`/`PrefixViolationError` always raise. Router confidence < 0.6 or module fees → `agent_complex` (Opus). All llm_runs of a turn are written in `persist` (summarizer row in `summarize`); outbound message gets `llm_run_id` of the last agent call. Fallback after a failed check sets `conversations.flagged`. Handoff sets `mode=human`, `status=pending` (+flag when urgency high). Widget gets a CTA quick reply by institution type.

#### 3.6 Context assembly & compaction — ☑ (2026-11-03)
- Sub-steps: 3.6.1 ☑ `app/agent/context.py` (system[0] global+persona, [1] tenant block, [2] skills — all cached; first user message = `<turn_context>` (date/time, academic year, channel, profile, verified, reply language) + `<conversation_summary>` + `<recent_history>` + `<new_message>`; budgets message 2k > summary 400 > history 1.2k > skills 1.5k; tool results ≤ 2.5k in registry); 3.6.2 ☑ history = last 6 turns text with collapsed tool lines, idle > 7 days → history reset, operator notes appended; 3.6.3 ☑ tests
- Verify: `scripts/verify/p3_s6.sh`
- Commit: `feat(agent): deterministic context assembly with cache-stable prefix`

#### 3.7 Guardrails — ☑ offline · ◐ guardrails eval live run (with 3.9)
- Sub-steps: 3.7.1 ☑ `app/agent/guards/__init__.py` (opt-out/opt-in keywords on short messages only, injection pre-filter (no LLM call when it fires), script check, Redis per-contact 20/10 min, per-conversation 40 AI turns/day, inbound dedupe); 3.7.2 ☑ `guards/grounding.py` (numbers in the draft must appear in sources/tool outputs/contact text/turn context — exact integer match, Urdu digits, booking codes ignored, 0–3 allowed; checker input ≤ 5k tokens; repair note format); 3.7.3 ☑ safe replies (phrases); 3.7.4 ☑ `evals/datasets/guardrails.yaml` (40: injection 10, abuse 4, PII 5, off-topic 5, identity 6, safe 10)
- Verify: `scripts/verify/p3_s7.sh`
- Commit: `feat(agent): input guard, grounding check and safety fallbacks`

#### 3.8 Summarizer & LTM updates — ☑ (2026-11-03)
- Sub-steps: 3.8.1 ☑ `Summary` schema + summarize node (Haiku); 3.8.2 ☑ `app/agent/memory.py` `apply_summary` → `conversations.summary`, `contacts.profile` (guardian/student/class/stage), `preferred_language`, `name`; lead upsert only if the phone's digits occur in what the contact typed; 3.8.3 ☑ idle reset (context.py); 3.8.4 ☑ `goal_status` from deterministic events (lead w/ phone, booking, follow-up, handoff), monotonic
- Verify: `scripts/verify/p3_s8.sh`
- Commit: `feat(agent): structured rolling summary and contact memory`

#### 3.9 Eval harness — ☑ offline · ◐ 👤 first live run awaiting approval (~$15–25)
- Sub-steps: 3.9.1 ☑ `evals/run_evals.py` (suites router/tone/guardrails/admissions_* + `agent`; modes live/record/replay; `--validate`, `--limit`, `--no-judge`, `--report` → JSON + MD (PR comment body); exit 1 on gate failure); 3.9.2 ☑ datasets router 80 · admissions_school/college/university 60 each (20 EN/20 UR/20 RU; PKR expectations validated against seed.yaml) · guardrails 40 · tone 30; 3.9.3 ☑ graders `evals/graders/agent.py` (deterministic + Opus judge `JudgeVerdict`, prompt `judge_admissions.md`); 3.9.4 ◐ cassettes get recorded by the first live run (`--mode record`; writes `evals/cassettes/suites/<suite>.json` markers — CI/verify replay only marked suites); 3.9.5 ☑ `.github/workflows/evals-live.yml` (dispatch / nightly / PR label `run-evals` on prompts·skills·registry·agent·search paths; needs `ANTHROPIC_API_KEY` secret; postgres+redis services, seed+ingest, report artifact + PR comment) and `evals-smoke` step in ci.yml (validate + router/tone replay once cassettes exist); 3.9.6 ☐ `evals/reports/baseline.md` after the live run
- Verify: `scripts/verify/p3_s9.sh` (offline); `p3_s9.sh --live` = record all suites on the seeded test DB
- Needs user: 👤 approve first live eval run
- Commit: `feat(evals): eval harness, datasets and ci gates`

#### 3.10 Local chat CLI & end-to-end smoke — ☑ (2026-11-03; live transcripts recorded) · 👤 user to try the CLI
- Sub-steps: 3.10.1 ☑ `api/scripts/chat.py` REPL over `run_inbound` (route, tools, check verdict, sources, cost per turn); 3.10.2 ☑ `docs/demo/scripts.yaml` (9 conversations: 3 types × EN/UR/RU, expected tools) → transcripts `docs/demo/<id>.md` (live, 27 turns, $0.13 total: 25 answered + check pass, 2 safe fallbacks from checker false negatives — both pass on rerun)
- Live findings fixed: (1) API rejects `role: system` right after an assistant text turn → `context.append_operator_note` (system message after user/tool results, else a marked `<operator_note>` user turn) (I-15); (2) checker flagged the institution's own name/apply URL and the agent's offers/CTAs → tenant block passed as source `profile` + `answer_check.md` 1.1.0 (offers/CTAs are not claims); numeric corpus includes the tenant block. Demo-run cassettes not committed (I-14)
- Verify: `scripts/verify/p3_s10.sh` (FakeLLM transcript test); `--live` writes the 9 transcripts
- Needs user: 👤 try `cd api && uv run python -m scripts.chat --institution abc-grammar-school` with the real key; confirm Roman Urdu feels right
- Commit: `feat(agent): local chat cli and demo transcripts`

---

### Phase 4 — Web widget + chat API

#### 4.1 Public chat API (SSE) — ☑ (2026-11-03)
- PLAN §14 (Widget), §15.1 (security)
- Sub-steps: 4.1.1 ☑ `GET /widget/config/{slug}` (theme, languages, welcome, 3 suggested questions by type × language, whatsapp flag; from `institutions.settings.widget` — a dict, so it never enters the cached tenant prompt block); 4.1.2 ☑ `POST /widget/sessions` (Origin must be in `settings.widget.allowed_origins`, localhost always allowed outside prod; visitor id `v_…` reused or minted; contact created up front; 24h HS256 JWT `typ=widget` bound to session/institution/contact/visitor/origin); 4.1.3 ☑ `POST /widget/sessions/{id}/messages` SSE: `status` (thinking + per-tool lines via `AgentDeps.status_hooks`) → `message` (only after the graph incl. `answer_check` finished) → `citation`, `slots` (parsed from the `get_visit_slots` tool output; `TurnResult.tool_outputs` added), `quick_replies` (dropped when slots shown), `lead_form` (booking intents/slots and no lead-with-phone/booking yet), `error`, `done`; the turn runs as a detached task so a closed tab still persists; 4.1.4 ☑ Redis fixed windows: sessions 30/h/IP, messages 60/10 min/IP + 30/10 min/session, 1000-char cap (422), 3 guard-blocked turns → session locked 1 h; 4.1.5 ☑ `POST …/lead` (deterministic `upsert_lead`, PK phone normalisation → 422), `GET …/whatsapp-link` (wa.me + `W…` code → Redis `widget:wa_code:*` 30 days for Phase 6 linking); `GET /institution/widget-snippet` (staff+)
- Also: `app/agent/runtime.py` (lazy `AgentDeps` + graph on the Postgres checkpointer, closed in lifespan; tests inject via `app.state.agent.set`); `AGENT_LLM=claude|demo` — `app/llm/demo.py` is a deterministic zero-spend agent for local widget work (refused in prod); `WidgetCorsMiddleware` (any origin may preflight `/api/v1/widget/*`; allowlist enforced in the endpoint + token); `psycopg[binary]` added (API image had no libpq once the API imports the checkpointer)
- Verify: `scripts/verify/p4_s1.sh` — `tests/integration/test_widget_api.py` (D-11: failed-check draft never streamed; approved reply after tool status) + `scripts.widget_smoke` against a live demo API (27 checks: config, origin 403, CORS, session, SSE order, slots, lead form, lead 422, wa link, 401/403/422)
- Commit: `feat(widget-api): public session and streaming chat endpoints`

#### 4.2 Widget bundle — ☑ (2026-11-03) · 👤 visual check
- PLAN §15.1
- Sub-steps: 4.2.1 ☑ Shadow DOM mount (`:host{all:initial}`), launcher, panel (≤ 480 px full-screen), theme via CSS vars from config, `data-lang/-position/-primary/-api/-open`; 4.2.2 ☑ message list, status line with dots, progressive client-side reveal of the approved reply (cosmetic; respects reduced motion), safe mini-markdown → DOM (no innerHTML of model text; bold, lists, tables), citation chips (expand to quote), quick replies, slot picker → "I'd like the slot on …", lead mini-form (422 → inline error; after a slot pick it sends the details so the agent books); 4.2.3 ☑ EN/اردو/Roman toggle, RTL + Noto Nastaliq lazy-loaded into the document head; 4.2.4 ☑ "Continue on WhatsApp" (shown when configured); 4.2.5 ☑ esbuild → `dist/v1/widget.js` **7.3 KB gz** (≤ 30 KB, CI size check); localStorage = visitor id + session token only, transcript in sessionStorage
- Verify: `scripts/verify/p4_s2.sh` — typecheck + prettier + build + size (behaviour covered by the browser e2e in p4_s3; no Vitest per user preference: minimal tests)
- Needs user: 👤 `bash scripts/verify/p4_s3.sh --headed` (or open `http://localhost:8010/widget/test/plain.html` while the demo API runs) and look on desktop + phone; screenshots in `/tmp/raabta-shots`
- Commit: `feat(widget): shadow-dom chat widget with rtl and whatsapp handoff`

#### 4.3 Widget served by API + embed test pages — ☑ (2026-11-03)
- Sub-steps: 4.3.1 ☑ `GET /widget/v1/widget.js` (`Cache-Control: public, max-age=3600, stale-while-revalidate=86400`, ETag/`X-Widget-Version` = content hash, 304) — CDN later; 4.3.2 ☑ `widget/test-pages/` plain.html, wordpress-like.html (hostile `!important` theme CSS, fixed header, left position), rtl.html (Urdu, `dir=rtl`) served at `/widget/test/<page>` outside prod; 4.3.3 ☑ `widget/scripts/e2e.mjs` (playwright-core + system Chrome, no browser download): ask → answer, slots, lead form (bad phone → error → good phone), host CSS isolation, left position, RTL + Nastaliq, mobile full-screen, language toggle, no JS errors (19 checks)
- Verify: `scripts/verify/p4_s3.sh` (`--headed` to watch)
- Needs user: 👤 confirm on a real WordPress/Wix page if available (needs the API reachable from that site + its origin in `allowed_origins`)
- Commit: `feat(widget): embed test pages and e2e`

#### 4.4 Widget docs & install guides — ☑ (2026-11-03)
- Sub-steps: 4.4.1 ☑ `docs/widget/install.md` (snippet, allowed origins, WordPress plugin/theme, Wix custom code, other builders, attributes, CSP, troubleshooting); 4.4.2 ☑ `docs/widget/theming.md` (settings.widget keys, CSS vars)
- Verify: `scripts/verify/p4_s4.sh` — docs exist + the documented snippet equals `snippet()` (the `/institution/widget-snippet` output) for the prod script URL
- Commit: `docs(widget): install and theming guides`

---

### Phase 5 — Admin panel foundation

> Verification is consolidated (user: minimal tests, verify with scripts): **`p5_s1`** = admin lint/types/prettier/build + OpenAPI client in sync + EN/UR keys; **`p5_s4`** = isolation suite over every route + `test_inbox.py` (takeover invariant, FakeLLM) + `test_superadmin.py` + `scripts.admin_smoke` (every admin endpoint on the demo API); **`p5_s11`** = built admin + demo API in system Chrome (`admin/scripts/e2e.mjs`: login/guard, every page, inbox flow, leads, settings, RTL, dark, mobile, superadmin, axe on every page). Steps below point at these.

#### 5.1 Next.js foundation — ☑ (2026-11-04; `p5_s1` OK) · 👤 visual check
- PLAN §17, §4
- Sub-steps: 5.1.1 ☑ shell (sidebar groups daily/manage, mobile sheet, topbar: institution switcher, اردو/English, theme, logout), shadcn (base-nova) components, teal brand primary, chart tokens = validated dataviz reference palette (light + dark steps), Inter + Noto Nastaliq (lazy); 5.1.2 ☑ login + invite-accept (`/invite/accept#token=`), access token in memory + httpOnly refresh cookie (single-flight refresh, 401 → refresh → retry → login), `raabta_auth` hint cookie for the Next 16 `proxy.ts` optimistic guard, client auth gate in `(app)/layout`, `useAuth`/`useMe` (role `can()`); 5.1.3 ☑ TanStack Query + `openapi-fetch` client typed from `openapi-typescript` (`pnpm -C admin gen:api` ← `api/scripts/dump_openapi.py`, no server needed); 5.1.4 ☑ next-intl client-side EN/UR (`src/messages/*.json`), `<html lang dir>` switch; 5.1.5 ☑ error boundary, sonner toasts, skeletons, `EmptyState`/`ErrorState`/`QueryView`
- Same-origin: Next rewrites `/api/v1/*` and `/widget/v1/*` to `API_URL` (baked at build) → refresh cookie works, no CORS
- Needs user: 👤 visual check light/dark + UR RTL (screenshots from `p5_s11` in `/tmp/raabta-admin-shots`)
- Commit: `feat(admin): next.js shell, auth, i18n and design system`

#### 5.2 Onboarding wizard — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.2.1 ☑ steps profile → documents (dropzone, live pipeline statuses) → facts review/approve → WhatsApp status card → widget (theme, origins, wa number, snippet copy, live preview iframe `public/widget-preview.html`) → done checklist; 5.2.2 ☑ `GET /institution/onboarding` (completed + computed checklist) and `POST /institution/onboarding/{step}` (profile/widget steps carry their form; resume = first incomplete step; stored in `settings.onboarding`, a dict → never in the prompt); 5.2.3 ☑ e2e (page render + axe in `p5_s11`)
- Commit: `feat(admin): onboarding wizard`

#### 5.3 Overview dashboard & metrics API — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.3.1 ☑ `GET /metrics/overview?range=7d|30d|90d` (KPIs + previous period, daily trend in the institution tz, channel split, cumulative funnel, needs-attention), `/metrics/funnel`, `/metrics/response-times` — live from source tables (today included), sandbox contacts excluded, fee KPIs null until Phase 7; 5.3.2 ☑ KPI tiles with deltas, trend line chart (2 series, one axis, legend, crosshair tooltip, table view), funnel (ordinal blue ramp), channels, attention list with deep links; 5.3.3 ☑ palette from the dataviz reference instance (validated; not re-stepped)
- Commit: `feat(admin): overview dashboard and metrics api`

#### 5.4 Live inbox with human takeover — ☑ (2026-11-04; `p5_s4`, `p5_s11`) · 👤 UX check
- PLAN §6.1 (takeover), §17
- Sub-steps: 5.4.1 ☑ `/conversations` (filters channel/mode/status/assigned/flagged/awaiting/q), detail (contact, lead, bookings, summary, assignee), messages (author names), `GET /conversations/events` fetch-SSE (DB-polled every 2 s, 5-min lifetime, client reconnects; 20 s query polling fallback); 5.4.2 ☑ 3-pane UI (list / bubbles with citations + collapsible tool calls + system notes / context pane); 5.4.3 ☑ take over, return to AI (dialog with note → `resume_after_handoff`; manual takeovers now also carry the note into thread state via `aupdate_state(as_node="await_staff")`), assign to me, flag, resolve/reopen (`PATCH /conversations/{id}`), staff reply (auto-takeover; optimistic), internal notes (`type=note`, never delivered); 5.4.4 ☑ j/k, r, n, t; 5.4.5 ☑ `test_inbox.py`: AI reply → takeover → no AI reply while human → staff reply reaches `GET /widget/sessions/{id}/updates` → note not delivered → return with note → next agent call contains the note
- Also (I-18): widget `done` event carries `human: true`; the widget polls `/updates` every 4 s while staff own the chat (state in sessionStorage; 7.5 KB gz)
- Commit: `feat(admin): live inbox with takeover and return-to-ai`

#### 5.5 Leads pipeline — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.5.1 ☑ `/leads` (status/owner/source/q, sort), `POST` (PK phone normalisation → 422), `PATCH` (owner must be an active member; audited before/after), `GET /leads/{id}` (bookings, conversations, timeline incl. audited changes), `export.csv` (BOM for Excel/Urdu, formula-injection neutralised); 5.5.2 ☑ kanban (native drag-and-drop + per-card status select as keyboard alternative), sortable table with bulk status, drawer (owner, follow-up, notes, timeline), new-lead dialog; 5.5.3 ☑ e2e (create + move in `p5_s11`)
- Commit: `feat(admin): leads kanban and table with export`

#### 5.6 Slot calendar — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.6.1 ☑ `/slots` (range, kind), `POST`/`PATCH`/`DELETE` (admin+; delete refused while active bookings), `POST /slots/bulk` (weekly pattern in institution tz, idempotent on kind+start, ≤ 500), `/bookings`, `PATCH /bookings/{id}` (confirm/attended/no-show/cancel; reschedule = atomic capacity take on target + release); 5.6.2 ☑ week view (Karachi), slot sheet (edit/delete/bookings), bookings list with actions; 5.6.3 ☑ booking changes post a staff message into the contact's latest conversation (widget delivers via poll; WhatsApp template in 6.x)
- Commit: `feat(admin): visit, test and counselling slot calendar`

#### 5.7 Knowledge base manager & playground — ☑ (2026-11-04; `p5_s4`, `p5_s11`) · 👤 try playground with the real key
- Sub-steps: 5.7.1 ☑ documents table (status chips, polling while in pipeline, re-index, delete), multi-file dropzone; 5.7.2 ☑ chunk viewer sheet (page, lang, tokens, suspicious, RTL for Urdu); 5.7.3 ☑ facts tabs per kind with approve/reject/edit (+ approve all pending); 5.7.4 ☑ playground: retrieval-only (free) or `POST /kb/playground/agent` full graph run as a sandbox widget contact `sandbox-{user}-{key}` (hidden from inbox + metrics) → answer, citations, check, route, per-node runs + cost
- Commit: `feat(admin): knowledge base manager and playground`

#### 5.8 Settings — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.8.1 ☑ `GET/PATCH /institution` (name, type, city, tz, languages, quiet hours) + `GET/PATCH /institution/settings`: "details" = top-level string settings the assistant sees (key/value editor), escalation keywords (**now enforced** in `run_inbound` → static handoff, `mode=human`, flagged, status `escalated`), CTA; 5.8.2 ☑ team & roles on the existing members API (invite → shareable link, role change, remove); 5.8.3 ☑ widget theme/position/origins/wa number + snippet + live preview (resolves I-20); 5.8.4 ☑ WhatsApp status card (read-only until 6.x)
- Commit: `feat(admin): settings, team and roles`

#### 5.9 Super-admin — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.9.1 ☑ `/superadmin/plans`, `/institutions` (plan, status, members, 30-day conversations/cost, last activity), `POST /institutions` (trial tenant + owner invite link), `PATCH` (plan/status), `POST|DELETE /impersonate/{id}` (Redis grant `imp:{user}:{inst}` 1 h → `get_tenant` admits the superadmin as owner with `membership_id=None`; start/stop audited in the tenant's own log), `/usage`; 5.9.2 ☑ platform page + amber impersonation banner with Stop; 5.9.3 ☑ isolation: superadmin routes excluded from the tenant matrix and covered by `test_superadmin.py` (owners get 403 everywhere; no tenant access without a grant; grant is per institution; revoked on stop) — resolves I-10
- Commit: `feat(admin): super-admin tenant management`

#### 5.10 Usage & billing + audit log pages — ☑ (2026-11-04; `p5_s4`, `p5_s11`)
- Sub-steps: 5.10.1 ☑ `GET /usage/limits?month=` (live month-to-date conversations + AI cost, template sends from `usage_daily`, seats) → limit bars + daily table; 5.10.2 ☑ `/audit-log` gains `actor`, `since`, action-prefix filter, `actor_email`; table with infinite paging + field-level before/after diff
- Commit: `feat(admin): usage, billing and audit log pages`

#### 5.11 UI quality pass — ◐ (axe ☑ on every page; 👤 Lighthouse + Urdu review)
- Sub-steps: 5.11.1 ☑ axe on every page incl. login, dark mode, superadmin (`p5_s11` fails on serious/critical), labelled controls, focus rings, `aria-current`/`aria-pressed`/`aria-selected`; 5.11.2 ☑ mobile inbox (list ↔ conversation with back), responsive grids, horizontal kanban scroll; 5.11.3 ☑ loading/empty/error states via `QueryView` everywhere; 5.11.4 ☐ Lighthouse not automated (I-23); 5.11.5 ☐ 👤 Urdu copy review (`admin/src/messages/ur.json`)
- Verify: `bash scripts/verify/p5_s11.sh [--headed]`
- Commit: `feat(admin): accessibility, responsive and polish pass`

---

### Phase 6 — WhatsApp channel

> Verification is consolidated like Phase 5 (D-26): **`p6_s1`** = live Meta (👤: number, display name, quality, webhook handshake via a public URL); **`p6_s2`** = the whole pipeline with zero spend — `tests/unit/test_whatsapp_units.py` (signature, payload shapes, status order, window, compose, templates, policy gate, Graph retries, STT confidence) + `tests/integration/test_whatsapp.py` (FakeLLM + FakeSTT + recording Graph over `httpx.MockTransport`) + isolation over every route + worker job registration + lint/types/unit; the admin side (templates page, inbox window banner, WhatsApp settings) runs in **`p5_s11`**. Code: `api/app/channels/whatsapp/` (client, webhook, window, compose, templates, policy), `api/app/channels/stt/`, `api/app/services/{whatsapp,followups,daily_summary}.py`, `api/app/api/{whatsapp,templates}.py`, worker jobs, migration 0005.

#### 6.1 Meta app & number setup — ☐ 👤
- PLAN §15.2 · runbook `docs/runbooks/meta-policy-checklist.md`
- Sub-steps (user): 6.1.1 ☐ WABA + number + display name (blocked by business verification U-01 / I-07); 6.1.2 ☐ permanent system-user token (`whatsapp_business_messaging` + `whatsapp_business_management`) → `META_ACCESS_TOKEN`; 6.1.3 ☐ public webhook URL `https://<host>/api/v1/webhooks/whatsapp` (ngrok/cloudflared in dev) + `META_VERIFY_TOKEN`, subscribe `messages` + `message_template_status_update`; 6.1.4 ☐ set the tenant row: `UPDATE institutions SET wa_phone_number_id='<id>', waba_id='<waba>' WHERE slug='<slug>'`
- Verify: 👤 `bash scripts/verify/p6_s1.sh https://<public-host>/api/v1/webhooks/whatsapp` → `✔ number … · name '…' · quality GREEN`, template list, `✔ webhook verify round-trip`
- Commit: none

#### 6.2 Webhook receiver — ☑ (2026-11-04; `p6_s2`)
- Sub-steps: 6.2.1 ☑ `GET /api/v1/webhooks/whatsapp` (verify token, constant-time) / `POST` (HMAC `X-Hub-Signature-256` over the raw body → 403; 503 until `META_APP_SECRET` set; 1 MB cap) → one `webhook_events` row per item (`ON CONFLICT DO NOTHING` on provider+event_id; unknown number → `ignored`) → `whatsapp_event_job` per new row → 200; 6.2.2 ☑ parser for text/audio/voice/image/document/interactive/button/location + statuses + template status, tenant by `metadata.phone_number_id` (template events by WABA id); 6.2.3 ☑ contact by `wa_id` (profile name), conversation reuse, `last_inbound_at`; 6.2.4 ☑ `process_event` → `run_inbound` (channel whatsapp) → delivery; row marked processed/failed (error type only, no PII)
- Commit: `feat(whatsapp): signed webhook receiver with idempotency`

#### 6.3 Sender & 24-hour window — ☑ (2026-11-04; `p6_s2`) · 👤 live test send after 6.1
- Sub-steps: 6.3.1 ☑ `WhatsAppClient` (text, reply buttons, list, template, image, mark-read, media download, phone number, template create/list) with 429/5xx/transport retries + typed `WhatsAppError` (`outside_window` = 131047); 6.3.2 ☑ `window.py` (24 h − 2 min margin); **one outbound path**: every WhatsApp message is a `queued` row first, `deliver_message` sends it or fails it with `messages.error` (new column); staff send outside the window → 409, inside → `deliver_message_job` after commit; booking-change notes go the same way; 6.3.3 ☑ status webhooks → `messages.status` (never regress read → delivered; failed keeps Meta's error); 6.3.4 ☑ `compose.py` (WhatsApp markup, tables → lines, ≤ 4096 split, quick replies → ≤ 3 buttons or a ≤ 10-row list); inbox shows window state + "Not delivered — reason"
- Needs user: 👤 `cd api && uv run python -m scripts.wa_check --send-test 92300XXXXXXX` after messaging the business number from that phone
- Commit: `feat(whatsapp): outbound sender with 24h window enforcement`

#### 6.4 Voice notes (STT) & media — ◐ (code ☑; bake-off 👤)
- PLAN §4 (STT), D-02
- Sub-steps: 6.4.1 ☑ media download (`GET /{media_id}` → URL → bytes, 16 MB cap) → blob `wa/<inst>/<wamid>.<ext>` for an allowlist of audio/image/pdf types (G16); 6.4.2 ☑ `SpeechToTextProvider` + `OpenAISTT` (httpx; `gpt-4o-transcribe` with logprob confidence, fallback `whisper-1` verbose_json) + `FakeSTT`, `STT_PROVIDER=fake|openai`; 6.4.3 ◐ `api/scripts/bakeoff_stt.py` (WER/CER per language, confidence calibration, latency → `evals/reports/stt-bakeoff-*.md`) written — needs samples + key → then ADR `0004-stt.md`; 6.4.4 ☑ transcript stored on the message (inbox shows 🎙), reply prefixed "Aap ka voice note mil gaya —", confidence < 0.6 / STT failure → "please type"; image/document without caption → static "what is this about?" (fee proofs: 7.5)
- Needs user: 👤 `STT_API_KEY` + ~20 voice notes (`<name>.ogg` + `<name>.txt`), then `cd api && uv run python -m scripts.bakeoff_stt --dir ~/raabta-voice-samples` (cents)
- Commit: `feat(whatsapp): voice note transcription behind stt interface`

#### 6.5 Template manager — ◐ (code ☑; wording review + submission 👤)
- Sub-steps: 6.5.1 ☑ `templates` table (0005, RLS; name+language unique; named `{{vars}}` → positional on submit/send; Roman Urdu = `<name>_ru` under Meta code `en`); 6.5.2 ☑ `POST /templates/{id}/submit` (admin, audited) → Graph `/{waba_id}/message_templates`; status via webhook + `POST /templates/sync`; 6.5.3 ☑ `POST /templates/seed` → 11 defaults × EN/UR/RU = 33 drafts (all pass Meta's start/end-variable rule — a unit test caught 15 that ended in `{{institution}}`); 6.5.4 ☑ admin `/templates` (table, editor with live WhatsApp-style preview, seed, submit, sync; staff read-only)
- Needs user: 👤 review the default wording (EN/UR/RU) with a pilot institution, then submit; approvals take minutes–days
- Commit: `feat(whatsapp): message template manager with meta sync`

#### 6.6 Widget → WhatsApp continuity — ☑ (2026-11-04; `p6_s2`) — resolves I-19
- Sub-steps: 6.6.1 ☑ inbound text containing `W` + 6 hex → Redis `widget:wa_code:*` (same institution only, single use) → WhatsApp contact gets the widget contact's name/language + `profile.linked_widget_contact_id` + `profile.widget_summary`; 6.6.2 ☑ integration test
- Commit: `feat(whatsapp): link widget sessions to whatsapp conversations`

#### 6.7 Admissions follow-ups & daily summary — ☑ (2026-11-04; `p6_s2`)
- PLAN §6.2
- Sub-steps: 6.7.1 ☑ after each AI reply on an admissions WhatsApp conversation: `admission_followup_1/2` at +24 h / +72 h (any inbound cancels + re-arms); `schedule_followup` tool rows; booking reminders created from 10:00 local the day before (once per booking); cron `dispatch_followups_job` every minute (Redis lock) → policy gate → `send_template` (inside the window: same text free-form; outside: approved template or fail with reason) → followup `sent/failed/cancelled/held/rescheduled`; 6.7.2 ☑ `daily_summary_job` 18:00 PKT → `daily_summary` template to `settings.daily_summary.numbers` (Settings → WhatsApp; ≤ 5, PK numbers normalised) + in-app `GET /metrics/daily-summary`; 6.7.3 ☑ tests with explicit clocks (quiet hours, Friday, cap)
- Commit: `feat(followups): scheduled admissions follow-ups and daily summary`

#### 6.8 Channel guardrails & Meta policy checklist — ☑ (2026-11-04; `p6_s2`)
- PLAN §10 (G6–G8, G12), §21
- Sub-steps: 6.8.1 ☑ opt-out (existing EN/RU/UR words) now cancels every pending/held follow-up and confirms **once**; staff replies to opted-out contacts → 409; 6.8.2 ☑ `policy.py` gate: opted out / staff mode → cancel, plan template limit → hold, quiet hours (institution tz) + Friday 12:30–14:30 → reschedule to window end; 6.8.3 ☑ ≤ 3 proactive messages / contact / 7 days → +1 day; 6.8.4 ☑ privacy line appended to the first AI/system reply of each WhatsApp conversation; 6.8.5 ☑ `docs/runbooks/meta-policy-checklist.md`
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
| 2026-11-04 | S7 | 5.x verify, 6.2–6.8 | Phase 5 DB verification: started Docker; fixed `_lib.sh` background-subshell pipe hang, `check` now prints failing sub-checks; real bugs: inbox staff reply sent `""` (TanStack v5 re-applies options to the in-flight mutation → text now a mutation variable), contrast (`--muted-foreground` 0.5, bubble meta, sonner rich colours), nested-interactive listbox → list of buttons, focusable context pane, `aria-expanded` on `<tr>`, language button label; e2e races. Phase 6: `app/channels/whatsapp/*` (Graph client, webhook parse + HMAC, window, compose, templates, policy), `app/channels/stt/*`, services `whatsapp`/`followups`/`daily_summary`, routers `webhooks/whatsapp` + `templates`, `metrics/daily-summary`, settings `daily_summary`, worker jobs + 2 crons, migration 0005 (templates, messages.error, followups.payload/error/held), opt-out cancels follow-ups, admin `/templates` + inbox window banner + failure reasons + WhatsApp settings form, `bakeoff_stt.py`, `wa_check.py`, policy runbook; isolation ids resolved before snapshot + readable paired diffs; intermittent isolation snapshot flake seen twice, unresolved (I-27) | `p5_s4` OK, `p5_s11` OK, `p6_s2` OK; `p6_s1` 👤 | `feat(whatsapp): phase 6 webhook, sender, templates, follow-ups, policy` |
| 2026-11-04 | S6 | 5.1–5.11 | Phase 5: admin API (institution/settings/onboarding, metrics, conversations + takeover/return/notes/flag/assign + fetch-SSE events, leads + CSV, slots/bulk/bookings + change notices, superadmin + Redis impersonation grant, usage limits, audit filters, playground agent run), escalation keywords enforced, manual-takeover note carried into the thread, widget `/updates` poll for staff replies (I-18); Next.js admin: shell, auth (memory token + refresh cookie, proxy guard), typed OpenAPI client, EN/UR RTL, dark mode, 11 pages; isolation suite extended; `test_inbox.py`, `test_superadmin.py`, `scripts.admin_smoke`, `admin/scripts/e2e.mjs` (+ axe) | `p5_s1` OK; API ruff/mypy/unit OK; **`p5_s4`/`p5_s11` not run — Docker engine down** | see 5.x blocks; one-shot: `feat(admin): phase 5 admin panel, inbox takeover and admin api` |
| 2026-11-03 | S5 | 4.1–4.4 | Phase 4: widget API (`/widget/config`, sessions w/ origin allowlist + 24h JWT, SSE turn with status hooks → approved message → citation/slots/quick_replies/lead_form, lead + wa-link, IP/session limits + abuse lockout, `/institution/widget-snippet`), lazy agent runtime in the API + `AGENT_LLM=demo` zero-spend agent, widget bundle (Shadow DOM, i18n EN/UR/RU + RTL + Nastaliq, slot picker, lead form, citations, WhatsApp), `/widget/v1/widget.js` + test pages, Chrome e2e via playwright-core, install/theming docs. Found: API image lacked libpq → `psycopg[binary]`. Minimal tests per user (1 integration test for D-11; rest via smoke/e2e scripts) | `all.sh` (see below) · p4_s1 smoke 27/27 · p4_s3 e2e 19/19 | per step blocks; one-shot: `feat: phase 4 — widget chat api, embeddable widget, embed e2e, docs` |
| 2026-11-03 | S4 | 3.1–3.10 | Phase 3 (agent core) offline: wrapper `complete`/`stream` + prefix guard + cost rows, FakeLLM; 10 prompts + loader; 9 skills + loader; strict registry + 12 admissions/common tools + 6 gated fee stubs + `/internal/tools`; LangGraph inbound graph (guard → router → context → agent tool loop → check → repair/fallback → compose → persist → summarize → handoff interrupt/resume) + `run_inbound` gates; context builder; guards + numeric grounding; summarizer/LTM; eval harness (6 suites, 330 cases, judge, reports, evals-live workflow, CI smoke); chat CLI + 9 demo scripts | `all.sh` OK (31 scripts); live smoke ✔ (cache hit), 9 live demo transcripts ($0.13; 2 live bugs fixed: system-role placement, checker profile/CTA); live eval deferred by user | per step blocks; one-shot: `feat: phase 3 — agent core, tools, langgraph graph, guards, eval harness` |
| 2026-11-02 | S3b | 2.4, 2.6, 2.2 | User decisions applied: D-01 Voyage (live bake-off; `.env` switched; `app.cli reembed`; 429-aware Voyage provider + batched eval queries), live Opus extractor run ($0.16) recorded as cassettes + replay test, PDF parser rewritten on pdfplumber + pypdfium2 (PyMuPDF removed) with Urdu fragmentation check and Chrome-printed Naskh/Nastaliq fixtures | `all.sh` OK (28 scripts) | `feat(kb): voyage embeddings, recorded extractor cassettes, permissive pdf parser` |
| 2026-11-02 | S3 | 2.1–2.8 | Phase 2 (knowledge base): migration 0004 (documents, chunks w/ vector(1024)+HNSW+tsv+trgm, 5 fact tables, RLS); blob store + sniffed uploads with dedupe/versioning; PDF/DOCX/XLSX/CSV parsers + Urdu quality flags + vision-OCR fallback (opt-in); heading-aware chunker + normalization + lang + injection filter; embedding providers (fake/Voyage/bge-m3) + bake-off script + ADR 0002 (proposed); hybrid search (vector+FTS+trigram+synonyms, RRF, packing); facts (XLSX deterministic, Opus extractor via `ClaudeClient.parse` w/ cassettes, approval API, facts_version, supersede); citations + playground; arq ingestion pipeline + `ingest-seeds`; 60-Q retrieval eval. Bugs fixed on the way: re-index while newer version processing, fact ordering (ordinal), seed-facts duplication on re-run | `all.sh` OK (p0–p2, 28 scripts); retrieval recall@5 1.00 / recall@1 0.85 (fake) | per step blocks; one-shot: `feat: phase 2 — knowledge base ingestion, hybrid search, facts, citations` |
| 2026-11-02 | S2 | 1.2–1.7 | Phase 1 completed: auth (argon2, JWT, Redis rotating refresh + reuse detection, lockout, invites), RBAC deps, roles + RLS (0002) + ORM tenant layer, conversation domain tables + LangGraph tables (0003), demo seeds (3 YAML + generated XLSX/DOCX, `seed` CLI), audit dependency + usage rollup cron + `/audit-log` `/usage`, OpenAPI-driven isolation suite. Fixed along the way: commit-after-response (scope=function), tenant scope cleared before final flush, LangGraph CONCURRENTLY deadlock, message ordering (`seq`) | `all.sh` OK (p0_s1–s6, p1_s1–s7) | see step blocks; one-shot: `feat: phase 1 — auth, rbac, rls, conversation tables, seeds, audit, isolation` |
| 2026-11-02 | S1 | 0.6, 1.1 | 0.6 closed (keys OK, Meta app created, verification postponed); core models, Alembic async baseline 0001 with extensions, migration round-trip + constraint tests, `make migrate` | `p0_s6` OK (user), `p1_s1` OK 7/7 | `feat(db): core tenant tables and alembic baseline` |
| 2026-11-01 | S1 | 0.3–0.6 | Settings/registry/logging/readyz (+ secret-safe settings errors); minimal CI (1 workflow, 2 jobs); ADR 0001 Netlify hosting; `.env` + `check_keys`; D-04 updated (Netlify at end, personal email for now) | `all.sh` p0_s1–s5 OK; p0_s6 awaiting user keys | 0.3 `feat(core): settings, model registry and structured logging` · 0.4 `ci: add minimal lint, type, test and build workflow` · 0.5 `docs: add ADR index and free-hosting ADR` · 0.6 `chore: add env template and provider key checker` |
| 2026-11-01 | S1 | 0.2 | docker-compose (pgvector pg16, redis, api/worker/admin profile), Dockerfiles, init.sql (extensions + non-owner `raabta_app` role), arq worker with `ping` job, `scripts/dev.sh`, `p0_s2.sh`; recorded D-12 = hybrid (user) | `p0_s2.sh` OK 12/12 | `chore: add docker-compose and dev scripts` |
| 2026-11-01 | S1 | 0.1 | Scaffolded api (uv, FastAPI /healthz, ruff/mypy/pytest), admin (Next 16 + shadcn), widget (esbuild + size check), root Makefile/.gitignore/.env.example/README, `scripts/verify/_lib.sh`, `p0_s1.sh`, `all.sh` | `p0_s1.sh` OK 14/14 | `chore: scaffold api, admin and widget workspaces` |
| 2026-11-01 | S1 | 0.0 | Plan drafted by Fable 5.1; reviewed by Opus 5.5: fixed widget streaming-before-check gap (D-11), flagged agent-model cost vs market (D-12, D-05) | files exist; review checklist (anatomy 16/16, 74 steps all have verify + commit) | `docs: add build plan, handoff tracker and CLAUDE.md` |

---

## §5 Decisions log

| ID | Date | Decision | Status | Notes |
|---|---|---|---|---|
| D-01 | 2026-11-01 | Embeddings: Voyage `voyage-3.5` (alt `bge-m3` behind the interface) | **decided by user 2026-11-02** after live bake-off (Urdu recall@1 0.85 vs 0.70) | PLAN §4, `docs/adr/0002-embeddings.md` |
| D-02 | 2026-11-01 | STT: interface + default OpenAI `gpt-4o-transcribe` (fallback `whisper-1`); bake-off in 6.4 | **needs user confirm** | PLAN §4 |
| D-03 | 2026-11-01 | WhatsApp: RaabtaAI-owned WABA, one number per institution; Embedded Signup deferred | **needs user confirm** | PLAN §4, §15.2 |
| D-04 | 2026-11-01 | Hosting (user): **free, at the end** — admin + widget on **Netlify**; API/worker/Postgres/Redis need a separate always-on free host (Netlify can't run them), chosen in 9.1 | **decided by user** (backend host open) | `docs/adr/0001-free-hosting-netlify.md` |
| D-05 | 2026-11-01 | Plan pricing & caps: draft suggested PKR 30k/60k/120k tiers — review flagged this is far above Pakistani market (competitors PKR 1.5k–9k/month); depends on D-12 | **needs user decision** | PLAN §19 |
| D-06 | 2026-11-01 | Opus 5.5 for agent (effort low/medium by complexity), Haiku 5.5 for classifiers; official SDK; no langchain-anthropic | decided | PLAN §4, §8 |
| D-07 | 2026-11-01 | Context: append-only within turn; simple compaction across turns; no thinking replay | decided | PLAN §7 |
| D-08 | 2026-11-01 | Numbers only from approved facts tables, never from chunks | decided | PLAN §11 |
| D-09 | 2026-11-01 | Fee reminders are templates (no LLM); LLM only for replies, tone-checked | decided | PLAN §6.2, §16 |
| D-10 | 2026-11-01 | Phase order: KB → agent → widget → admin → WhatsApp → fees | decided | HANDOFF §2 |
| D-11 | 2026-11-01 | Widget uses check-then-send (status events, then approved text) — never stream the unchecked draft | decided (plan review) | PLAN §8, §15.1 |
| D-13 | 2026-11-02 | Tenancy: runtime login `raabta_app` + per-transaction `SET LOCAL ROLE app_tenant` (RLS) or explicit `app_admin` (BYPASSRLS) for auth lookups/superadmin/seeds/platform jobs; ORM filter as 2nd layer; `users` global | decided (impl.) | PLAN §18; HANDOFF 1.3 notes |
| D-14 | 2026-11-02 | Refresh tokens + lockout in Redis (no DB table); invites return a shareable link (no email provider in MVP) | decided (impl.) — revisit if email needed | HANDOFF 1.2 notes |
| D-15 | 2026-11-02 | KB: retrieval eval gold = verbatim substrings (not chunk UUIDs); numbers only from approved fact rows (D-08) — chunks may *show* fees but the agent must cite facts; suspicious chunks excluded from search; dense leg optional at query time (lexical fallback) | decided (impl.) | HANDOFF 2.3–2.6 notes |
| D-16 | 2026-11-02 | Seed demo facts: without `KB_FACTS_LLM`, prospectus facts come from `seed.yaml` (origin `seed`) and `ingest-seeds` auto-approves (demo only); real tenants always go pending → admin approval | decided (impl.) | HANDOFF 2.6 notes |
| D-17 | 2026-11-02 | PDF parsing on permissive libs: pdfplumber (layout/tables) + pypdfium2 (Urdu text, rendering); PyMuPDF (AGPL) removed. Nastaliq PDFs → flagged → vision OCR | **decided by user 2026-11-02** ("switch to a free library if it meets Urdu/table/PDF needs" — verified on fixtures) | HANDOFF 2.2 notes |
| D-18 | 2026-11-03 | Model never sees DB ids: deterministic content-hash source ids (`S-`/`F-`), slots addressed by local `slot_time`; ToolContext from graph state only | decided (impl.) | HANDOFF 3.4 notes |
| D-19 | 2026-11-03 | Numeric grounding is deterministic and runs alongside the Haiku checker (either failing → one repair → fallback + flag) | decided (impl.) | PLAN §10 G2; `guards/grounding.py` |
| D-20 | 2026-11-03 | Eval CI smoke replays only router/tone (request hashes independent of DB state); agent suites are live-only (tool results depend on seeded slots/ids); evals run against the disposable test DB (they write contacts/leads/bookings) | decided (impl.) | §6 I-14 |
| D-21 | 2026-11-03 | Widget: stateless session JWT (no sessions table) bound to institution/contact/visitor/origin; contact created at session start so status hooks can be keyed before the turn; slots/lead form derived deterministically from tool outputs/route (no prompt changes → cassettes unaffected); transcript only in sessionStorage | decided (impl.) | HANDOFF 4.1/4.2 |
| D-22 | 2026-11-03 | Testing style from Phase 4 on (user): only invariant tests in pytest; behaviour verified by runnable scripts (API smoke, browser e2e) inside the verify scripts | decided by user | HANDOFF 4.x |
| D-23 | 2026-11-04 | Admin is a client-rendered app behind Next rewrites (same origin as the API proxy): access token in memory, refresh token httpOnly cookie, `raabta_auth` hint cookie only for the `proxy.ts` optimistic redirect; fits Netlify (D-04) | decided (impl.) | HANDOFF 5.1 |
| D-24 | 2026-11-04 | Inbox live updates = fetch-SSE of changed conversation ids, DB-polled (2 s) instead of Redis pub/sub — no write-path plumbing, works across processes; 20 s query polling fallback | decided (impl.) — revisit at scale | HANDOFF 5.4 |
| D-25 | 2026-11-04 | Superadmin impersonation = audited 1-hour Redis grant per institution (no token minting, no fake membership); UI banner while active | decided (impl.) | HANDOFF 5.9 |
| D-26 | 2026-11-04 | Phase 5 verification consolidated into `p5_s1` (static), `p5_s4` (API), `p5_s11` (browser e2e + axe) instead of 11 scripts (user: minimal tests) | decided by user preference | HANDOFF Phase 5 |
| D-27 | 2026-11-04 | WhatsApp outbound = one path: every message is a `queued` row, `deliver_message` sends or fails it (`messages.error`); free-form only inside 24 h (staff send outside → 409); proactive sends via `send_template` (free-form text inside the window, approved template outside) | decided (impl.) | HANDOFF 6.3 |
| D-28 | 2026-11-04 | Templates: named `{{vars}}` per language row (order may differ by language), positional on submit/send; Roman Urdu submitted as `<name>_ru` under Meta language `en`; webhook path `/api/v1/webhooks/whatsapp` | decided (impl.) | HANDOFF 6.5 |
| D-29 | 2026-11-04 | Admissions follow-ups at +24 h/+72 h after each AI reply (re-armed by any inbound); weekly cap 3 proactive/contact; default Jumma window Fri 12:30–14:30 on top of institution quiet hours; Phase 6 verification consolidated into `p6_s1` (live) + `p6_s2` | decided (impl.) — tune with pilots | HANDOFF 6.7/6.8 |
| D-12 | 2026-11-01 | **Hybrid agent routing**: router `complexity=simple` (FAQ: fees, timings, transport, greetings) → `claude-haiku-5-5` agent with the same tools + answer_check; `complex` (booking, fee module, multi-step, unhappy/escalation, low router confidence) → `claude-opus-5-5`. Eval gate in 3.9 compares simple-route quality Haiku vs Opus; if Haiku fails thresholds, try `claude-sonnet-5-5` for simple route. Implemented via `models_registry` keys `agent_simple` / `agent_complex` | **decided by user 2026-11-01** | PLAN §7, §19; unblocks D-05 |

---

## §6 Known issues / open questions

| ID | Raised | Issue / question | Status |
|---|---|---|---|
| I-01 | 2026-11-01 | Urdu PDF text extraction quality unknown until real prospectuses are tested; vision-OCR fallback implemented (2.2.4, `KB_VISION_OCR=1`) but untested on real data | open (needs sample, see I-12) |
| I-02 | 2026-11-01 | Meta per-message template rates for Pakistan must be checked on the current rate card before pricing plans | open |
| I-03 | 2026-11-01 | Haiku 5.5 has no server-side refusal fallback — classifier nodes use safe-default verdicts on `refusal` | noted |
| I-04 | 2026-11-01 | Minimum cacheable prefix is 512 tokens on Opus/Haiku 5.5 per current docs; design keeps global prompt > 1k anyway | noted |
| I-06 | 2026-11-01 | `ANTHROPIC_API_KEY` exported in user's `~/.zshrc` overrides `.env` for every process started from that shell; `check_keys` flags it | open (user) |
| I-07 | 2026-11-02 | Meta test-number send (`hello_world` → user's phone) accepted, then failed via webhook `131031 Business Account locked`; `account_update` event `BUSINESS_VERIFICATION_NEEDED` for WABA `2218657989053365`. So the test number **cannot send until business verification**. User has no SECP/business-name NTN yet. Workaround: develop/test 6.x with recorded webhook payloads + mocked Graph API; real-phone E2E after U-01 | open (user) |
| I-08 | 2026-11-02 | CI runs no DB-backed tests (minimal CI by user choice) → integration + isolation suites run only via `scripts/verify/*.sh` locally. Add a CI job with postgres(pgvector)+redis services + `infra/db/init.sql` in Phase 8 (was 1.7.3) | open (Phase 8) |
| I-09 | 2026-11-02 | Migration 0002 creates a BYPASSRLS role → migration role must be superuser (or have BYPASSRLS). Check the free backend host's Postgres allows it at 9.1; fallback = policy-based admin bypass GUC | open (9.1) |
| I-10 | 2026-11-02 | Superadmin has no tenant access via `X-Institution` → **resolved 2026-11-04** by the audited impersonation grant (D-25) | resolved |
| I-11 | 2026-11-02 | ~~PyMuPDF is AGPL-3.0~~ → **resolved 2026-11-02**: replaced by pdfplumber + pypdfium2 (D-17). Original note: Using it in a hosted SaaS may oblige releasing source of the service unless a commercial Artifex licence is bought. Options before pilots: buy licence, or swap to `pypdf`/`pdfplumber` (MIT/BSD; loses page rendering for vision-OCR → render via `pdf2image`/poppler). Isolated to `app/kb/parsers/pdf.py` + `render_page_png` | resolved |
| I-12 | 2026-11-02 | Demo corpus is tiny (~2 chunks per document, ~4 per institution) → recall@5 saturates at 1.00; recall@1/MRR are the useful signals. Need one real (anonymized) prospectus PDF, ideally with Urdu pages, to make the bake-off and the 90% gate meaningful (also tests the PDF parser + Urdu flags on real data, I-01) | open (user: provide a sample prospectus) |
| I-13 | 2026-11-02 | Voyage account has no payment method → 3 requests/min, 10K tokens/min. Dev/evals cope (waits + batching); live widget/WhatsApp traffic would stall. Add billing before pilots (U-14) | open (user, before pilots) |
| I-14 | 2026-11-03 | Agent-node cassettes are only replayable on the same DB state (seeded slots are relative to seed time; booking codes random) → CI smoke replays router/tone only; agent suites need `--mode live` | noted (D-20) |
| I-15 | 2026-11-03 | API: `role: system` must follow a user message (or tool results) — not the assistant's final text. Fixed via `append_operator_note` (marked user turn in that case). **CLAUDE.md "Operator notes = appended role:system" needs this nuance (user to update)** | resolved 2026-11-03 |
| I-18 | 2026-11-03 | Widget in human mode shows "our team will reply here" but staff replies have no path back to the widget yet → **resolved 2026-11-04**: `GET /widget/sessions/{id}/updates?after=` + widget polling while `human` (verify in `p5_s4`/`p5_s11`) | resolved (pending verify) |
| I-19 | 2026-11-03 | `widget:wa_code:*` → WhatsApp contact linking → **resolved 2026-11-04** (6.6) | resolved |
| I-20 | 2026-11-03 | Allowed origins only editable via SQL → **resolved 2026-11-04** (Settings → Website widget, validated origins) | resolved |
| I-17 | 2026-11-03 | Haiku answer_check false negatives: 2/27 demo turns fell back although drafts were correct (pass on rerun). Measure in the live eval (`fallback_rate`); options: checker effort/prompt tweak, or let deterministic numeric check + Haiku disagreement retry once | open (3.9 live run) |
| I-16 | 2026-11-03 | Fee tools are stubs ("not enabled → hand off") until Phase 7; fee-module turns always end in handoff | noted (Phase 7) |
| I-21 | 2026-11-04 | Docker down during S6 → **resolved 2026-11-04** (S7 ran `p5_s4`/`p5_s11`; fixes logged in §4) | resolved |
| I-22 | 2026-11-04 | `settings.escalation.max_ai_turns` is stored/editable but not enforced yet (keywords are) | open (Phase 6/8) |
| I-23 | 2026-11-04 | Lighthouse ≥ 90 (5.11.4) not automated (no Lighthouse dep); run manually: `npx lighthouse http://localhost:3010/ --preset=desktop` against the `p5_s11` admin | open |
| I-24 | 2026-11-04 | Playground full-agent runs are real turns (sandbox contact): hidden from inbox/metrics but they count in `llm_runs`/usage cost and the per-conversation daily cap | noted |
| I-25 | 2026-11-04 | Urdu admin copy (`admin/src/messages/ur.json`) was machine-written — needs a native review (5.11.5) | open (user) |
| I-26 | 2026-11-04 | Next dev/prod rewrite proxy may buffer SSE; inbox falls back to 20 s polling. If live updates lag on the chosen host, point the events fetch at the API origin directly (needs CORS for the admin origin) | noted |
| I-27 | 2026-11-04 | Intermittent isolation failure "B's data changed" (twice inside `p6_s2` on a fresh DB, on `PATCH /conversations/{id}` and `PATCH /bookings/{id}`; 0 of 4 later runs, incl. `p6_s2` OK). Unified diff showed *every* snapshot line differing (whole-snapshot change, not one row). Cause not found; ruled out as fix: token TTL (test TTL raised to 240 min anyway). Now diagnosable: assertion prints paired before/after lines and `p6_s2` keeps `/tmp/raabta-isolation.log` — on recurrence read that file | open |
| I-28 | 2026-11-04 | Daily-summary sends go to principal numbers that are not contacts → no `messages` row → not counted in `usage_daily.template_sends` (plan limit) | open (Phase 8 cost/limits) |
| I-29 | 2026-11-04 | Booking-change notes on WhatsApp outside the 24 h window fail with a reason (inbox shows it); the day-before `visit_reminder` template still reaches the parent. A `visit_confirmation` template fallback could be added | noted |
| I-30 | 2026-11-04 | Jumma window is code default only (`QuietHours` API model forbids extra keys) — make it editable if an institution needs different timing | noted |
| I-31 | 2026-11-04 | `SADeprecationWarning` for `.distinct(col)` in `api/app/api/conversations.py` (use `postgresql.distinct_on`) | open (small) |
| I-05 | 2026-11-01 | Preserved-thinking prefix check is enforced for accounts created on/after 2026-08-31 — confirm account age; design is append-only regardless | open |

---

## §7 User action queue (external tasks, no repo changes)

| # | Task | Needed by | Status |
|---|---|---|---|
| U-01 | Meta business verification (portfolio + app `RaabtaAi` created 2026-11-02; postponed — needs a document in the business name, e.g. SECP certificate or business-name NTN; portfolio name must match it exactly). Also blocks test-number sends (I-07) | before live WhatsApp E2E (6.x) / pilots | ◐ |
| U-02 | Meta app with WhatsApp use case; `.env` has META_APP_ID, META_APP_SECRET, META_PHONE_NUMBER_ID, META_WABA_ID, META_VERIFY_TOKEN (2026-11-02); META_ACCESS_TOKEN empty until 6.1.2 | 6.1 | ☑ |
| U-03 | Phone numbers for pilots + dev test number | 6.1 | ☐ |
| U-04 | Anthropic API key in `.env` + spend cap (user has key) | 0.6 | ◐ |
| U-05 | Voyage key in `.env` as `VOYAGE_API_KEY` (user has key) | 0.6 | ◐ |
| U-06 | STT provider key (`STT_API_KEY`) + ~20 voice notes (`<name>.ogg` + `<name>.txt`, UR/RU/EN) → `uv run python -m scripts.bakeoff_stt --dir …` → confirm D-02 | 6.4 | ☐ |
| U-07 | Confirm decisions D-02, D-03, D-05 (D-01 ✔ Voyage, D-04 ✔) | Phase 3 / 6 | ◐ |
| U-11 | Approve small spends: 2.4 Voyage bake-off, 2.6 live extractor ($0.16) | Phase 2 | ☑ (done 2026-11-02) |
| U-12 | Provide one real (anonymized) prospectus PDF, ideally with Urdu pages (I-12, I-01) | before pilots | ⏭ later (user) |
| U-13 | Decide PyMuPDF licensing (I-11) | — | ☑ switched to free libs (D-17) |
| U-14 | Add a payment method to the Voyage account (lifts 3 RPM limit; free 200M tokens still apply) (I-13) | before pilots | ☐ |
| U-15 | Approve Phase 3 live spends: 3.1 smoke ✔, 3.10 transcripts ✔ (2026-11-03); 3.9 first live eval (~$15–25) still pending | Phase 3 close | ◐ |
| U-08 | Hosting: Netlify (admin/widget) + free backend host — at the end; personal email for now; domain optional | 9.1 | ⏭ later |
| U-09 | Sentry projects | 8.2 | ☐ |
| U-16 | Review default WhatsApp template wording (Admin → Templates → Add default set; EN/UR/RU), then submit to Meta once 6.1 is done | 6.5 | ☐ |
| U-17 | After U-01: system-user token → `.env` `META_ACCESS_TOKEN`; public tunnel; set `institutions.wa_phone_number_id/waba_id`; run `p6_s1` | 6.1 | ☐ |
| U-10 | Sample redacted fee receipts (HBL/JazzCash/Easypaisa) | 7.5 | ☐ |
