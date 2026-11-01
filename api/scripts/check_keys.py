"""Check provider keys for RaabtaAI (HANDOFF step 0.6). Never prints key values.

    uv run python -m scripts.check_keys          # offline: which keys are set, and from where
    uv run python -m scripts.check_keys --live   # also verifies the Anthropic key + pinned models
                                                 # via the free Models API (no tokens billed)
Exit code 0 = required keys set (and, with --live, valid); 1 otherwise.
"""

import os
import sys

import anthropic

from app.core.config import REPO_ROOT, get_settings
from app.core.models_registry import NODES, spec_for

REQUIRED_NOW = ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY")
LATER = ("STT_API_KEY", "META_APP_ID", "META_APP_SECRET", "META_VERIFY_TOKEN", "META_ACCESS_TOKEN")


def dotenv_has(name: str) -> bool:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return False
    for line in env_file.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name:
            return bool(value.strip())
    return False


def source_of(name: str) -> str:
    in_shell = bool(os.environ.get(name))
    in_dotenv = dotenv_has(name)
    if in_shell and in_dotenv:
        return "SET (shell env overrides .env — the .env value is ignored!)"
    if in_shell:
        return "set (from shell env, not .env)"
    if in_dotenv:
        return "set (.env)"
    return "MISSING"


def check_anthropic_live(api_key: str) -> bool:
    client = anthropic.Anthropic(api_key=api_key)
    ok = True
    for model in sorted({spec_for(n).model for n in NODES}):
        try:
            info = client.models.retrieve(model)
            print(f"  ✔ {model}: available ({info.display_name})")
        except anthropic.AuthenticationError:
            print("  ✘ ANTHROPIC_API_KEY rejected (401) — check the key")
            return False
        except anthropic.NotFoundError:
            print(f"  ✘ {model}: not available on this account")
            ok = False
        except anthropic.APIConnectionError:
            print("  ✘ cannot reach the Anthropic API (network)")
            return False
    return ok


def main() -> int:
    live = "--live" in sys.argv
    print("Required now:")
    missing = False
    for name in REQUIRED_NOW:
        state = source_of(name)
        missing |= state == "MISSING"
        print(f"  {name}: {state}")
    print("Needed later (OK to be missing now):")
    for name in LATER:
        print(f"  {name}: {source_of(name)}")
    if missing:
        print("RESULT: add the missing keys to .env (see .env.example)")
        return 1
    if live:
        print("Live check (Anthropic Models API, free):")
        if not check_anthropic_live(get_settings().require("anthropic_api_key")):
            return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
