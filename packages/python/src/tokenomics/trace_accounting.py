"""Trace-level frontier accounting invariants.

One task trace owns physical usage, baseline, and savings delta.
Mechanisms are attribution labels — never independently summed savings.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Literal

from .models import TokenomicsEvent

MeasurementLevel = Literal["M0", "M1", "M2", "M3"]
ActualUsageClass = Literal["incremental", "aggregate_only", "unmetered", "zero_local"]
BaselineClass = Literal["paired_measured", "estimated", "missing"]
OutcomeClass = Literal["verified", "negative", "execution_only", "unknown"]


def is_prepare_event(ev: TokenomicsEvent) -> bool:
    return ev.kind == "prepare" or bool(ev.economics and ev.economics.prepare_outcome)


def is_frontier_event(ev: TokenomicsEvent) -> bool:
    return not is_prepare_event(ev)


def incremental_provider_tokens(ev: TokenomicsEvent) -> int:
    if not ev.usage or ev.usage.attribution != "incremental":
        return 0
    if ev.usage.source not in {"provider", "derived"}:
        return 0
    reuse = str((ev.extra or {}).get("reuse_kind") or "")
    if reuse in {"cache", "offline_replay", "offline"}:
        return 0
    return int(ev.usage.total() or 0)


def aggregate_reported_tokens(ev: TokenomicsEvent) -> int | None:
    if not ev.usage or ev.usage.attribution != "aggregate":
        return None
    return int(ev.usage.total() or 0)


def _baseline_from_event(ev: TokenomicsEvent) -> int | None:
    extra = ev.extra or {}
    if extra.get("baseline_total_tokens") is not None:
        try:
            return int(extra["baseline_total_tokens"])
        except (TypeError, ValueError):
            return None
    return None


def _measured_frontier_from_event(ev: TokenomicsEvent) -> int | None:
    extra = ev.extra or {}
    if extra.get("measured_frontier_tokens") is not None:
        try:
            return int(extra["measured_frontier_tokens"])
        except (TypeError, ValueError):
            pass
    if ev.usage and ev.usage.reported_total_tokens is not None:
        try:
            return int(ev.usage.reported_total_tokens)
        except (TypeError, ValueError):
            return None
    return None


def _estimated_avoided(ev: TokenomicsEvent) -> int | None:
    extra = ev.extra or {}
    if extra.get("placement_only") or ev.kind == "placement":
        return None
    if not ev.economics or ev.economics.estimated_tokens_avoided is None:
        return None
    try:
        v = int(ev.economics.estimated_tokens_avoided)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _route(ev: TokenomicsEvent) -> str:
    return str((ev.extra or {}).get("route") or "").lower()


def mechanism_labels(ev: TokenomicsEvent) -> list[str]:
    extra = ev.extra or {}
    labels: list[str] = []
    harness = str(ev.harness or "").lower()
    cap = str(ev.capability_id or ev.name or "").lower()
    route = _route(ev)
    provider = str(ev.model.provider if ev.model and ev.model.provider else "").lower()

    if harness == "flow" or (ev.economics and ev.economics.prepare_outcome):
        labels.append("flow_prepare")
    if harness == "omp" or provider == "omp" or "omp" in cap:
        labels.append("omp")
    if harness == "hermes" or provider in {"hermes", "nous"} or "hermes" in cap:
        labels.append("hermes")
    if ev.role == "rlm_worker" or "rlm" in cap or str(extra.get("context_policy") or "").startswith("rlm"):
        labels.append("rlm")
    if route in {"local", "local_model"} or "jev" in cap or "openjev" in cap or "nanojev" in cap:
        if "nanojev" in cap or provider == "nanojev":
            labels.append("nanojev")
        elif "openjev" in cap:
            labels.append("openjev")
        else:
            labels.append("jev")
    if provider == "local_mb" or "local_mb" in cap:
        labels.append("local_mb")
    if harness == "kerdoios" or provider == "kerdoios_plan" or ev.kind == "placement":
        labels.append("kerdoios")
    if route == "routine" or "routine" in cap:
        labels.append("routine")
    if "compress" in cap or (ev.context and ev.context.policy):
        labels.append("context")
    if "cache" in cap or (ev.usage and (ev.usage.cached_input_tokens or 0) > 0):
        labels.append("cache")
    if route in {"model", "frontier", "cloud"} or (ev.model and ev.model.provider):
        labels.append("routing")
    if not labels:
        labels.append("other")
    seen: set[str] = set()
    out: list[str] = []
    for x in labels:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def trace_outcome_class(events: list[TokenomicsEvent]) -> OutcomeClass:
    tiers = [e.outcome.tier() for e in events if e.outcome is not None]
    if "negative" in tiers:
        return "negative"
    if "gold" in tiers:
        return "verified"
    if "execution" in tiers or "soft" in tiers:
        return "execution_only"
    return "unknown"


@dataclass(frozen=True)
class TraceFrontierRollup:
    trace_id: str
    harness: str
    measurement_level: MeasurementLevel
    actual_usage: ActualUsageClass
    baseline: BaselineClass
    outcome: OutcomeClass
    attribution: tuple[str, ...]
    actual_frontier_tokens: int
    baseline_frontier_tokens: int | None
    tokens_avoided: int
    savings_tier: Literal["measured", "estimated", "unknown"]
    incremental_events: int
    aggregate_reported: int | None
    reconciliation_delta: int | None
    event_count: int
    verified: bool


def rollup_trace(events: list[TokenomicsEvent]) -> TraceFrontierRollup:
    rows = [e for e in events if is_frontier_event(e)] or list(events)
    trace_id = rows[0].trace_id if rows else "unknown"
    harness = rows[0].harness or "unknown"

    inc = [e for e in rows if e.usage and e.usage.attribution == "incremental"]
    agg = [e for e in rows if e.usage and e.usage.attribution == "aggregate"]

    actual = sum(incremental_provider_tokens(e) for e in inc)
    aggregate_total = None
    if agg:
        aggregate_total = aggregate_reported_tokens(sorted(agg, key=lambda e: e.ts or 0)[-1])
    reconciliation = None if aggregate_total is None else aggregate_total - actual

    if actual == 0:
        measured_vals = [v for v in (_measured_frontier_from_event(e) for e in rows) if v is not None]
        if measured_vals:
            actual = int(max(measured_vals))
        elif any(_route(e) in {"local", "local_model", "routine", "specialist"} for e in rows):
            actual = 0

    if inc and any(incremental_provider_tokens(e) > 0 for e in inc):
        actual_class: ActualUsageClass = "incremental"
    elif inc and actual == 0 and any(_route(e) in {"local", "local_model"} for e in rows):
        actual_class = "zero_local"
    elif agg and aggregate_total is not None:
        actual_class = "aggregate_only"
    elif actual > 0:
        actual_class = "incremental"
    else:
        actual_class = "unmetered"

    baseline_vals = [v for v in (_baseline_from_event(e) for e in rows) if v is not None]
    baseline_total = max(baseline_vals) if baseline_vals else None

    paired = any(
        _measured_frontier_from_event(e) is not None and _baseline_from_event(e) is not None
        for e in rows
    )

    est_avoided_vals = [v for v in (_estimated_avoided(e) for e in rows) if v is not None]

    if paired and baseline_total is not None:
        baseline_class: BaselineClass = "paired_measured"
        avoided = max(0, int(baseline_total) - int(actual))
        tier: Literal["measured", "estimated", "unknown"] = "measured"
        level: MeasurementLevel = "M3"
    elif est_avoided_vals:
        baseline_class = "estimated" if baseline_total is not None else "missing"
        avoided = int(max(est_avoided_vals))
        tier = "estimated"
        level = "M1"
    elif baseline_total is not None and actual_class in {"incremental", "zero_local", "aggregate_only"}:
        baseline_class = "missing"
        avoided = 0
        tier = "unknown"
        level = "M2"
    else:
        baseline_class = "missing"
        avoided = 0
        tier = "unknown"
        level = "M0" if actual_class == "unmetered" else "M2"

    labels: list[str] = []
    for e in rows:
        labels.extend(mechanism_labels(e))
    attr = tuple(sorted(set(labels)))
    outcome = trace_outcome_class(rows)

    return TraceFrontierRollup(
        trace_id=trace_id,
        harness=str(harness),
        measurement_level=level,
        actual_usage=actual_class,
        baseline=baseline_class,
        outcome=outcome,
        attribution=attr,
        actual_frontier_tokens=int(actual),
        baseline_frontier_tokens=int(baseline_total) if baseline_total is not None else None,
        tokens_avoided=int(avoided),
        savings_tier=tier,
        incremental_events=len(inc),
        aggregate_reported=aggregate_total,
        reconciliation_delta=reconciliation,
        event_count=len(rows),
        verified=outcome == "verified",
    )


def rollup_traces(events: Iterable[TokenomicsEvent]) -> list[TraceFrontierRollup]:
    buckets: dict[str, list[TokenomicsEvent]] = defaultdict(list)
    for ev in events:
        if is_prepare_event(ev):
            continue
        buckets[ev.trace_id].append(ev)
    return [rollup_trace(rows) for _, rows in sorted(buckets.items())]


def assert_no_double_count(events: list[TokenomicsEvent]) -> None:
    r = rollup_trace(events)
    if r.reconciliation_delta is not None and r.reconciliation_delta < 0:
        raise ValueError(
            f"aggregate reported ({r.aggregate_reported}) < incremental sum ({r.actual_frontier_tokens})"
        )
