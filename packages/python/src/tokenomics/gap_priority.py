"""Measurement-gap prioritization for autoresearch replay planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .trace_accounting import TraceFrontierRollup


@dataclass(frozen=True)
class MeasurementGap:
    mechanism: str
    capability_id: str
    n_traces: int
    verified_traces: int
    actual_metered: bool
    baseline_coverage: float
    avg_actual_tokens: float
    avg_baseline_tokens: float | None
    expected_information_value: str
    priority_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "capability_id": self.capability_id,
            "n_traces": self.n_traces,
            "verified_traces": self.verified_traces,
            "actual_metered": self.actual_metered,
            "baseline_coverage": round(self.baseline_coverage, 4),
            "avg_actual_tokens": round(self.avg_actual_tokens, 1),
            "avg_baseline_tokens": round(self.avg_baseline_tokens, 1)
            if self.avg_baseline_tokens is not None
            else None,
            "expected_information_value": self.expected_information_value,
            "priority_score": round(self.priority_score, 4),
        }


def _eiv_label(score: float) -> str:
    if score >= 0.65:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def rank_measurement_gaps(
    rollups: Iterable[TraceFrontierRollup],
    *,
    capability_by_trace: dict[str, str] | None = None,
    replay_cost: float = 1.0,
    limit: int = 32,
) -> list[MeasurementGap]:
    cap_map = capability_by_trace or {}
    buckets: dict[tuple[str, str], list[TraceFrontierRollup]] = {}
    for r in rollups:
        cap = cap_map.get(r.trace_id, "unknown")
        for mech in r.attribution or ("other",):
            if mech == "flow_prepare":
                continue
            buckets.setdefault((mech, cap), []).append(r)

    gaps: list[MeasurementGap] = []
    for (mech, cap), rows in buckets.items():
        n = len(rows)
        if n == 0:
            continue
        verified = sum(1 for r in rows if r.verified)
        paired = sum(1 for r in rows if r.baseline == "paired_measured")
        estimated = sum(1 for r in rows if r.baseline == "estimated")
        baseline_cov = (paired + 0.5 * estimated) / n if n else 0.0
        metered = sum(1 for r in rows if r.actual_usage in {"incremental", "zero_local"})
        avg_actual = sum(r.actual_frontier_tokens for r in rows) / n
        base_vals = [r.baseline_frontier_tokens for r in rows if r.baseline_frontier_tokens]
        avg_base = (sum(base_vals) / len(base_vals)) if base_vals else None
        magnitude = avg_base or avg_actual or 1.0
        resolve_prob = max(0.05, 1.0 - baseline_cov)
        score = (n * (1 + verified) * magnitude * resolve_prob) / max(replay_cost, 0.1)
        gaps.append(
            MeasurementGap(
                mechanism=mech,
                capability_id=cap,
                n_traces=n,
                verified_traces=verified,
                actual_metered=metered > 0,
                baseline_coverage=baseline_cov,
                avg_actual_tokens=avg_actual,
                avg_baseline_tokens=avg_base,
                expected_information_value=_eiv_label(score / max(n, 1)),
                priority_score=score,
            )
        )
    gaps.sort(key=lambda g: (-g.priority_score, -g.n_traces, g.mechanism))
    return gaps[:limit]


def gaps_for_autoresearch(
    rollups: Iterable[TraceFrontierRollup],
    *,
    capability_by_trace: dict[str, str] | None = None,
    limit: int = 16,
) -> list[dict[str, Any]]:
    return [
        g.to_dict()
        for g in rank_measurement_gaps(rollups, capability_by_trace=capability_by_trace, limit=limit)
    ]


def capability_by_trace_from_events(events) -> dict[str, str]:
    out: dict[str, str] = {}
    for ev in events:
        cap = str(ev.capability_id or "unknown")
        if ev.trace_id not in out or cap != "unknown":
            out[ev.trace_id] = cap
    return out
