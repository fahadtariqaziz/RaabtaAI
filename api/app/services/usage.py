"""Per-institution daily usage (PLAN §19): real-time increments + nightly authoritative rollup.

- `record_usage(...)` — atomic upsert-increment for counters needed live (plan limits, budgets).
- `rollup_usage(day)` — recomputes a whole day for every institution from source tables
  (conversations, messages, llm_runs, leads, bookings), using each institution's timezone for the
  day boundary. Overwrites → idempotent; it is the source of truth for closed days.
Runs cross-tenant → caller provides an admin-scoped session.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import UsageDaily

COUNTERS = (
    "conversations",
    "messages_in",
    "messages_out",
    "template_sends",
    "tokens_in",
    "tokens_out",
    "llm_cost_usd",
    "leads",
    "bookings",
    "fee_recovered_pkr",
)


async def record_usage(
    session: AsyncSession, institution_id: uuid.UUID, day: date, **increments: int | Decimal
) -> None:
    unknown = set(increments) - set(COUNTERS)
    if unknown:
        raise ValueError(f"unknown usage counters: {sorted(unknown)}")
    if not increments:
        return
    stmt = insert(UsageDaily).values(institution_id=institution_id, date=day, **increments)
    stmt = stmt.on_conflict_do_update(
        index_elements=[UsageDaily.institution_id, UsageDaily.date],
        set_={k: getattr(UsageDaily, k) + stmt.excluded[k] for k in increments},
    )
    await session.execute(stmt)


# One statement: per-institution local-day window, aggregates from each source table.
_ROLLUP_SQL = text(
    """
WITH win AS (
  SELECT id AS institution_id,
         (CAST(:day AS date)::timestamp AT TIME ZONE timezone) AS t0,
         ((CAST(:day AS date) + 1)::timestamp AT TIME ZONE timezone) AS t1
  FROM institutions
),
conv AS (SELECT c.institution_id, count(*) n FROM conversations c JOIN win w
         ON w.institution_id = c.institution_id AND c.created_at >= w.t0 AND c.created_at < w.t1
         GROUP BY 1),
msg AS (SELECT m.institution_id,
               count(*) FILTER (WHERE direction = 'in') AS n_in,
               count(*) FILTER (WHERE direction = 'out' AND sender <> 'system') AS n_out,
               count(*) FILTER (WHERE direction = 'out' AND type = 'template') AS n_tpl
        FROM messages m JOIN win w
        ON w.institution_id = m.institution_id AND m.created_at >= w.t0 AND m.created_at < w.t1
        GROUP BY 1),
llm AS (SELECT r.institution_id,
               sum(input_tokens + cache_read_tokens + cache_write_tokens) AS t_in,
               sum(output_tokens) AS t_out, sum(cost_usd) AS cost
        FROM llm_runs r JOIN win w
        ON w.institution_id = r.institution_id AND r.created_at >= w.t0 AND r.created_at < w.t1
        GROUP BY 1),
lead AS (SELECT l.institution_id, count(*) n FROM leads l JOIN win w
         ON w.institution_id = l.institution_id AND l.created_at >= w.t0 AND l.created_at < w.t1
         GROUP BY 1),
book AS (SELECT b.institution_id, count(*) n FROM bookings b JOIN win w
         ON w.institution_id = b.institution_id AND b.created_at >= w.t0 AND b.created_at < w.t1
         GROUP BY 1)
INSERT INTO usage_daily AS u (institution_id, date, conversations, messages_in, messages_out,
                              template_sends, tokens_in, tokens_out, llm_cost_usd, leads, bookings)
SELECT w.institution_id, CAST(:day AS date),
       coalesce(conv.n, 0), coalesce(msg.n_in, 0), coalesce(msg.n_out, 0), coalesce(msg.n_tpl, 0),
       coalesce(llm.t_in, 0), coalesce(llm.t_out, 0), coalesce(llm.cost, 0),
       coalesce(lead.n, 0), coalesce(book.n, 0)
FROM win w
LEFT JOIN conv USING (institution_id) LEFT JOIN msg USING (institution_id)
LEFT JOIN llm USING (institution_id) LEFT JOIN lead USING (institution_id)
LEFT JOIN book USING (institution_id)
ON CONFLICT (institution_id, date) DO UPDATE SET
  conversations = excluded.conversations, messages_in = excluded.messages_in,
  messages_out = excluded.messages_out, template_sends = excluded.template_sends,
  tokens_in = excluded.tokens_in, tokens_out = excluded.tokens_out,
  llm_cost_usd = excluded.llm_cost_usd, leads = excluded.leads, bookings = excluded.bookings
"""
)


async def rollup_usage(session: AsyncSession, day: date) -> int:
    """Recompute `day` for all institutions. Returns rows written. fee_recovered_pkr is kept
    (Phase 7 fills it from confirmed payments)."""
    result = await session.execute(_ROLLUP_SQL, {"day": day})
    return int(getattr(result, "rowcount", 0) or 0)
