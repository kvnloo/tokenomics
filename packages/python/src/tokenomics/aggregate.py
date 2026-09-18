from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import TokenomicsEvent


@dataclass(frozen=True)
class TraceSummary:
    trace_id: str
    event_count: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    total_tokens: int
    cost_usd: float
    duration_ms: float | None
    verified: bool
    outcome_tier: str
    root_tokens: int
    worker_tokens: int
    subagent_tokens: int
    verifier_tokens: int
    aggregate_reported_tokens: int | None
    reconciliation_delta: int | None


def _event_tokens(event: TokenomicsEvent) -> int:
    if event.usage is None:
        return 0
    return int(event.usage.total() or 0)


def summarize_trace(events: Iterable[TokenomicsEvent]) -> TraceSummary:
    rows = list(events)
    if not rows:
        raise ValueError("cannot summarize an empty trace")
    trace_ids = {r.trace_id for r in rows}
    if len(trace_ids) != 1:
        raise ValueError("summarize_trace requires exactly one trace_id")

    incremental = [r for r in rows if r.usage is not None and r.usage.attribution == "incremental"]
    aggregate = [r for r in rows if r.usage is not None and r.usage.attribution == "aggregate"]
    input_tokens = sum(int(r.usage.input_tokens or 0) for r in incremental if r.usage)
    output_tokens = sum(int(r.usage.output_tokens or 0) for r in incremental if r.usage)
    cached = sum(int(r.usage.cached_input_tokens or 0) for r in incremental if r.usage)
    reasoning = sum(int(r.usage.reasoning_tokens or 0) for r in incremental if r.usage)
    total = sum(_event_tokens(r) for r in incremental)
    cost = sum(float(r.economics.cost_usd or 0) for r in incremental if r.economics)

    role_totals: dict[str, int] = {"root": 0, "rlm_worker": 0, "subagent": 0, "verifier": 0}
    for row in incremental:
        if row.role in role_totals:
            role_totals[row.role] += _event_tokens(row)

    aggregate_total = None
    if aggregate:
        # The newest aggregate event is the authoritative reported total for reconciliation.
        aggregate_total = _event_tokens(sorted(aggregate, key=lambda e: e.ts)[-1])
    reconciliation_delta = None if aggregate_total is None else aggregate_total - total

    tiers = [r.outcome.tier() for r in rows if r.outcome is not None]
    if "negative" in tiers:
        tier = "negative"
    elif "gold" in tiers:
        tier = "gold"
    elif "execution" in tiers:
        tier = "execution"
    elif "soft" in tiers:
        tier = "soft"
    else:
        tier = "unknown"

    starts = [r.started_at for r in rows if r.started_at is not None]
    ends = [r.ended_at for r in rows if r.ended_at is not None]
    duration = None
    if starts and ends:
        duration = max(0.0, (max(ends) - min(starts)) * 1000.0)

    return TraceSummary(
        trace_id=rows[0].trace_id,
        event_count=len(rows),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached,
        reasoning_tokens=reasoning,
        total_tokens=total,
        cost_usd=cost,
        duration_ms=duration,
        verified=tier == "gold",
        outcome_tier=tier,
        root_tokens=role_totals["root"],
        worker_tokens=role_totals["rlm_worker"],
        subagent_tokens=role_totals["subagent"],
        verifier_tokens=role_totals["verifier"],
        aggregate_reported_tokens=aggregate_total,
        reconciliation_delta=reconciliation_delta,
    )


def summarize_traces(events: Iterable[TokenomicsEvent]) -> list[TraceSummary]:
    buckets: dict[str, list[TokenomicsEvent]] = {}
    for event in events:
        buckets.setdefault(event.trace_id, []).append(event)
    return [summarize_trace(rows) for _, rows in sorted(buckets.items())]


def tokens_per_verified_task(events: Iterable[TokenomicsEvent]) -> dict[str, float | int | None]:
    summaries = summarize_traces(events)
    verified = [s for s in summaries if s.verified]
    total_tokens = sum(s.total_tokens for s in verified)
    total_cost = sum(s.cost_usd for s in verified)
    return {
        "schema": "tokenomics.verified_economics.v0",
        "n_traces": len(summaries),
        "n_verified": len(verified),
        "total_tokens_on_verified": total_tokens,
        "tokens_per_verified_task": total_tokens / len(verified) if verified else None,
        "total_cost_usd_on_verified": total_cost,
        "cost_per_verified_task_usd": total_cost / len(verified) if verified else None,
        "verification_rate": len(verified) / len(summaries) if summaries else None,
    }
