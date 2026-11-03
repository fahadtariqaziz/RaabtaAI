"""Live smoke for the Claude wrapper (step 3.1): two calls with an identical cached prefix on
the cheap `agent_simple` node, then one `router` parse. Asserts the second call reads the cache
(`cache_read_input_tokens > 0`). Spends < $0.01. Usage: `uv run python -m scripts.llm_smoke`."""

import asyncio
import sys

from app.agent.context import CACHE
from app.agent.graph import cached_system, router_user_content
from app.agent.schemas import RouteDecision
from app.core.config import get_settings
from app.llm.claude import ClaudeClient
from app.prompts import load_prompt


async def main() -> int:
    settings = get_settings()
    key = settings.require("anthropic_api_key")
    client = ClaudeClient(key, mode="live")
    rules = f"{load_prompt('system_global').text}\n\n{load_prompt('agent_admissions').text}"
    system = [{"type": "text", "text": rules, "cache_control": CACHE}]
    messages = [{"role": "user", "content": "Reply with one word: ready"}]
    first = await client.complete("agent_simple", system=system, messages=messages)
    second = await client.complete("agent_simple", system=system, messages=messages)
    route = await client.parse(
        "router",
        system=cached_system("router"),
        messages=[
            {
                "role": "user",
                "content": router_user_content("school", [], "", "", "Class 3 ki fee kitni hai?"),
            }
        ],
        output_format=RouteDecision,
    )
    for label, r in (("call 1", first), ("call 2", second), ("router", route)):
        print(
            f"{label}: model={r.model} stop={r.stop_reason} in={r.input_tokens} "
            f"cache_write={r.cache_write_tokens} cache_read={r.cache_read_tokens} "
            f"out={r.output_tokens} cost=${r.cost_usd} fallback={r.fallback_used}"
        )
    print("router decision:", route.output.model_dump())
    if second.cache_read_tokens <= 0:
        print("FAIL: second identical-prefix call did not read the cache")
        return 1
    print("OK: cache hit on second call")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
