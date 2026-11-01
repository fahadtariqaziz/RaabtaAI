#!/usr/bin/env bash
# Local dev: infra in Docker, app processes on the host with hot reload.
# Ctrl+C stops api/worker/admin (Postgres/Redis keep running; `docker compose stop` to stop them).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f .env ]] || { echo "No .env — copy .env.example to .env first"; exit 1; }
set -a; source .env; set +a

docker compose up -d --wait postgres redis

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

(cd api && uv run uvicorn app.main:app --reload --port 8000) & pids+=($!)
(cd api && uv run arq app.jobs.worker.WorkerSettings --watch app) & pids+=($!)
pnpm -C admin dev & pids+=($!)

echo "api http://localhost:8000/healthz · admin http://localhost:3000"
wait
