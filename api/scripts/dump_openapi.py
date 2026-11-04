"""Write the API's OpenAPI schema to a file (no server, no DB) — input for the admin's typed
client (`pnpm -C admin gen:api`, PLAN §14 "OpenAPI → TS client codegen")."""

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    settings = Settings(
        _env_file=None,
        env="test",
        database_url="postgresql+asyncpg://x@h/d",
        redis_url="redis://h",
        jwt_secret="x" * 40,
    )
    out.write_text(json.dumps(create_app(settings).openapi(), indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
