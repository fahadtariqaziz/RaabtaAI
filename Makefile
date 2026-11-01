.PHONY: install lint test build verify

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
