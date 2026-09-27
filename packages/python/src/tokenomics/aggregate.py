from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import TokenomicsEvent

EXPLICIT_INCOMPLETE_MEASUREMENT_STATES = frozenset({"partial", "failed", "unsupported"})


def event_measurement_state(event: TokenomicsEvent) -> str:
    source = event.measurement_source
    return str(source.measurement_state) if source and source.measurement_state else "unknown"


def has_explicit_incomplete_measurement(events: Iterable[TokenomicsEvent]) -> bool:
    return any(
        event_measurement_state(event) in EXPLICIT_INCOMPLETE_MEASUREMENT_STATES
        for event in events
    )


def aggregate_measurement_state(events: Iterable[TokenomicsEvent]) -> str:
    states = [event_measurement_state(event) for event in events]
    if not states:
        return "unknown"
    if "failed" in states:
        return "failed"
    if "partial" in states:
        return "partial"
    if "unsupported" in states:
        return "unsupported" if all(state == "unsupported" for state in states) else "partial"
    if "unknown" in states:
        return "unknown"
    return "complete" if all(state == "complete" for state in states) else "unknown"


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
    measurement_state: str
    authoritative: bool


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
    measurement_rows = incremental if incremental else aggregate
    measurement_state = aggregate_measurement_state(measurement_rows)

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
        measurement_state=measurement_state,
        authoritative=measurement_state == "complete",
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
    verified_complete = [s for s in verified if s.authoritative]
    verified_explicit_incomplete = [
        s for s in verified
        if s.measurement_state in EXPLICIT_INCOMPLETE_MEASUREMENT_STATES
    ]
    verified_unknown = [s for s in verified if s.measurement_state == "unknown"]
    authoritative = bool(verified) and len(verified_complete) == len(verified)
    verified_states = [s.measurement_state for s in verified]
    if authoritative:
        verified_measurement_state = "complete"
    elif "failed" in verified_states:
        verified_measurement_state = "failed"
    elif "partial" in verified_states:
        verified_measurement_state = "partial"
    elif "unsupported" in verified_states:
        verified_measurement_state = (
            "unsupported"
            if verified_states and all(state == "unsupported" for state in verified_states)
            else "partial"
        )
    else:
        verified_measurement_state = "unknown"
    observed_tokens_per_verified = total_tokens / len(verified) if verified else None
    observed_cost_per_verified = total_cost / len(verified) if verified else None
    return {
        "schema": "tokenomics.verified_economics.v0",
        "n_traces": len(summaries),
        "n_verified": len(verified),
        "n_verified_complete": len(verified_complete),
        "n_verified_explicit_incomplete": len(verified_explicit_incomplete),
        "n_verified_unknown": len(verified_unknown),
        "measurement_state": verified_measurement_state,
        "authoritative": authoritative,
        "total_tokens_on_verified": total_tokens,
        "tokens_per_verified_task": observed_tokens_per_verified,
        "total_cost_usd_on_verified": total_cost,
        "cost_per_verified_task_usd": observed_cost_per_verified,
        "authoritative_tokens_per_verified_task": (
            observed_tokens_per_verified if authoritative else None
        ),
        "authoritative_cost_per_verified_task_usd": (
            observed_cost_per_verified if authoritative else None
        ),
        "verification_rate": len(verified) / len(summaries) if summaries else None,
    }
