"""Test env: set before `app` is imported so tests never depend on a developer's .env.

Real env vars take precedence over the `.env` file in pydantic-settings, so these win.
Unit tests use an unreachable DB/Redis on purpose; integration tests (marker `integration`)
point at the docker-compose services instead (see scripts/verify/p0_s3.sh).
"""

import os

os.environ["ENV"] = "test"
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/none")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")
os.environ.setdefault("JWT_SECRET", "test-secret")
for key in ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY"):
    os.environ.setdefault(key, "")
