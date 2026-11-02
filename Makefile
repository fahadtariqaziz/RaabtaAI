.PHONY: install lint test build verify migrate seed ingest-seeds evals-retrieval

install:
	cd api && uv sync
	pnpm install

lint:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy
	pnpm -C admin lint && pnpm -C admin typecheck
	pnpm -C widget typecheck

test:
	cd api && uv run pytest

build:
	pnpm -C admin build
	pnpm -C widget build && pnpm -C widget size

# Run all verification scripts of completed steps (see HANDOFF.md).
verify:
	bash scripts/verify/all.sh

# Apply DB migrations to the dev database (uses MIGRATIONS_DATABASE_URL from .env — owner role).
migrate:
	cd api && uv run alembic upgrade head

# Load the three demo institutions + demo users into the dev DB (idempotent; --reset via ARGS).
seed:
	bash scripts/seed.sh $(ARGS)

# Run the demo documents through the KB pipeline (parse → chunk → embed → facts → ready).
# Embeddings use EMBEDDING_PROVIDER from .env (fake = no spend).
ingest-seeds:
	cd api && uv run python -m app.cli ingest-seeds $(ARGS)

# Retrieval eval (recall@5 per language) against the ingested demo institutions.
evals-retrieval:
	cd api && uv run python -m evals.run_evals --suite retrieval $(ARGS)
