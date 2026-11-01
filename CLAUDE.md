# CLAUDE.md — RaabtaAI project rules

RaabtaAI: multi-tenant AI assistant for Pakistani schools/colleges/universities — admissions Q&A (EN/Urdu/Roman Urdu, voice) and fee recovery over a web widget + WhatsApp. Not an ERP. Design: `docs/PLAN.md`. Status: `HANDOFF.md`.

## Session protocol
1. Read `HANDOFF.md` §0 and the current step block first. Read only the `PLAN §N` the step cites (`grep -n "^## §N" docs/PLAN.md`).
2. Run the verify script of the last completed step (`scripts/verify/pN_sM.sh`) before starting work.
3. Do the step; create and run its verify script. If it needs the user (Meta account, API spend, browser check), give exact commands + expected output and mark `◐ (awaiting user)`.
4. End of step/session: update `HANDOFF.md` (§0, statuses, §4 session log, §5/§6) and give a one-line commit message `type(scope): msg`.
5. **Never `git commit` or `git push`.** The user commits.
6. Context efficiency: no `cat` of big files; `grep`/`sed -n`; don't re-read files you just wrote; summarize, don't dump.

## Pinned models (`api/app/core/models_registry.py`)
| Node | Model | Effort |
|---|---|---|
| agent_complex (bookings, fee module, multi-step, escalations), facts_extractor, receipt_reader, eval judge | `claude-opus-5-5` | agent medium; extractor high; vision medium; judge high |
| agent_simple (router `complexity=simple` FAQ turns — D-12 hybrid), guard_in, router, answer_check, tone_check, summarizer | `claude-haiku-5-5` | low |
Changing a model ID, prompt, skill, or effort = a release: `evals-live` must pass (PLAN §12).

## Claude API rules (official `anthropic` SDK only; no langchain-anthropic)
- Opus 5.5: never send `thinking` disabled/`budget_tokens` (400). Always set `output_config={"effort": ...}` explicitly (default is `medium`).
- No `temperature/top_p/top_k`, no assistant prefill, no `tool_choice` `any`/`tool` → use `auto` + `strict: True` tools + prompt instruction, or structured outputs (`client.messages.parse(output_format=Model)` / `output_config.format`).
- Opus calls: `client.beta.messages.*` with `betas=["server-side-fallback-2026-07-01"], fallbacks="default"`. Haiku has no fallback → safe-default verdict on `refusal`.
- Always check `stop_reason` (`refusal`, `max_tokens`, `tool_use`) before reading content.
- Caching order: tools (name-sorted) → system[global] → system[tenant] → system[skills] → messages. No timestamps/tenant-volatile data in cached blocks; verify `usage.cache_read_input_tokens > 0`.
- Preserved thinking: within a turn the message list is append-only and thinking blocks are passed back unchanged; across turns build a fresh deterministic context (summary + last K turns as text, no thinking replay). Operator notes = appended `{"role":"system"}` messages, never edits.
- Parallel tool calls → all `tool_result`s in one user message; errors as `is_error: True`; parse tool inputs with Pydantic/json, never string-match.
- Typed exceptions (`RateLimitError`, `APIStatusError`, `APIConnectionError`) with backoff; per-node timeouts; log tokens + cost per institution (`llm_runs`).

## Code conventions
- Python 3.13, FastAPI async, Pydantic v2, SQLAlchemy 2 typed async, Alembic (one head), ruff + mypy clean, pytest (`unit/`, `integration/`, `isolation/`, `evals`). `uv run ...` for everything.
- Every tenant row has `institution_id`; queries run under RLS (`SET LOCAL app.institution_id`); tools get `ToolContext`, never a tenant id from the model.
- Prompts in `api/app/prompts/*.md` with front-matter `version`; skills in `api/app/skills/<name>/SKILL.md` + `skill.yaml`; tools strict JSON schema (`additionalProperties: false`).
- Money/dates/scheduling/sending are deterministic code, never LLM arithmetic. Fee data only after `verify_parent`.
- Admin is Next.js 16 (newer than training data): read `admin/AGENTS.md` and the relevant guide in `admin/node_modules/next/dist/docs/` before writing admin code.
- TS: strict, ESLint + Prettier; admin = Next.js App Router + shadcn/ui + TanStack Query; widget = vanilla TS, Shadow DOM, ≤ 30KB gz.
- Secrets only via env (`.env` is git-ignored). No PII in logs. Conventional commits.
- Don't create docs/README files unless a step asks for them. Don't over-engineer: MVP scope is PLAN §1; deferred items are PLAN §24.
