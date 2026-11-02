"""USD price table per model (per 1M tokens) for `llm_runs.cost_usd` (PLAN §19).
Source: Anthropic pricing, 2026-10. Cache writes billed at 1.25× input (5-minute TTL)."""

from decimal import Decimal

PRICES: dict[str, tuple[Decimal, Decimal, Decimal]] = {
    # model: (input, output, cache read)
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00"), Decimal("0.20")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50"), Decimal("0.01")),
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00"), Decimal("0.20")),
}
MTOK = Decimal(1_000_000)


def cost_usd(
    model: str, *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> Decimal:
    inp, out, read = PRICES.get(model, PRICES["claude-opus-5-5"])
    total = (
        inp * input_tokens
        + out * output_tokens
        + read * cache_read
        + inp * Decimal("1.25") * cache_write
    ) / MTOK
    return total.quantize(Decimal("0.000001"))
