"""Neutral orchestration / tool-calling control telemetry.

This module models one *decision -> execution -> outcome* triple in a
model-agnostic way and lifts it into the canonical ``tokenomics.event.v0``
event (``kind="decision"``).

Design rules enforced here:

* ``selected_action`` (what the learned/deterministic layer chose) and
  ``executed_action`` (what the runtime actually ran) are never merged.
* ``execution_completed`` (transport/execution reached its end) and
  ``verified_success`` (an *independent* source confirmed task quality) stay
  separate.  ``verified_success`` is carried through verbatim and is never
  inferred; a learned observer cannot mint its own gold outcome.
* Orchestration fields with no home in ``tokenomics.event.v0`` are carried in
  the free-form ``attributes`` bag because the v0 schema forbids extra
  top-level properties.

The module is stdlib-only and reuses the existing models in
``tokenomics.models`` rather than duplicating them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .ids import new_span_id, new_trace_id
from .models import Economics, Latency, ModelRef, Outcome, TokenUsage, TokenomicsEvent

SCHEMA = "tokenomics.orchestration.v1"

_ATTRIBUTE_PREFIX = "orchestration."


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Return the ``pct``-th percentile (0-100) of ``values``.

    Uses linear interpolation between the two closest ranks (the same
    convention as ``numpy.percentile``'s default ``linear`` method).
    Empty input returns ``None``; a single value returns that value.
    """
    if not 0.0 <= pct <= 100.0:
        raise ValueError("pct must be between 0 and 100")
    data = sorted(float(v) for v in values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    rank = (len(data) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return data[lower]
    fraction = rank - lower
    return data[lower] + (data[upper] - data[lower]) * fraction


@dataclass(frozen=True)
class LatencySummary:
    """Percentile summary of a latency series.

    A ``mean`` is always reported alongside the percentiles; callers must
    never publish a mean on its own.
    """

    count: int
    p50: float | None
    p95: float | None
    p99: float | None
    mean: float | None
    maximum: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "mean": self.mean,
            "maximum": self.maximum,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> "LatencySummary":
        if raw is None:
            raw = {}
        count = raw.get("count", 0)
        return cls(
            count=int(count) if count is not None else 0,
            p50=raw.get("p50"),
            p95=raw.get("p95"),
            p99=raw.get("p99"),
            mean=raw.get("mean"),
            maximum=raw.get("maximum"),
        )


def summarize_latency(values: Sequence[float]) -> LatencySummary:
    """Summarize a latency series; ``None`` entries are ignored."""
    data = [float(v) for v in values if v is not None]
    if not data:
        return LatencySummary(count=0, p50=None, p95=None, p99=None, mean=None, maximum=None)
    return LatencySummary(
        count=len(data),
        p50=percentile(data, 50),
        p95=percentile(data, 95),
        p99=percentile(data, 99),
        mean=sum(data) / len(data),
        maximum=max(data),
    )


@dataclass(frozen=True)
class OrchestrationObservation:
    """One decision -> execution -> outcome triple, model-agnostic."""

    trace_id: str
    decision_backend: str | None = None  # deterministic|jev|nemotron|qwen|hammer|functiongemma|...
    model_id: str | None = None
    revision: str | None = None
    candidate_action_count: int | None = None
    selected_action: str | None = None  # what the learned/deterministic layer chose
    executed_action: str | None = None  # what the RUNTIME actually executed (may differ / be None)
    invalid_call: bool | None = None
    irrelevant_call: bool | None = None
    unnecessary_call: bool | None = None
    dependency_violation: bool | None = None
    parallelizable_but_serialized: bool | None = None
    retry_count: int | None = None
    recovery_success: bool | None = None
    escalated: bool | None = None
    abstained: bool | None = None
    execution_completed: bool | None = None
    verified_success: bool | None = None
    decision_latency_ms: float | None = None
    ttft_ms: float | None = None
    tool_latency_ms: float | None = None
    end_to_end_latency_ms: float | None = None
    gpu_ms: float | None = None
    vram_peak_mib: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_tokens: int | None = None
    local_cost_usd: float | None = None
    provider_cost_usd: float | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-ready dict; always tagged with ``SCHEMA``, ``None`` dropped."""
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data = {key: value for key, value in data.items() if value is not None}
        data["schema"] = SCHEMA
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> "OrchestrationObservation":
        if not isinstance(raw, dict):
            raise TypeError("OrchestrationObservation.from_dict expects a dict")
        data = dict(raw)
        schema = data.pop("schema", None)
        if schema not in (None, SCHEMA):
            raise ValueError(f"unsupported schema: {schema}")
        known = cls.__dataclass_fields__
        extra = data.pop("extra", None)
        extra = dict(extra) if isinstance(extra, dict) else {}
        unknown = {key: value for key, value in data.items() if key not in known}
        for key in unknown:
            data.pop(key, None)
        extra.update(unknown)
        kwargs = {key: value for key, value in data.items() if key in known}
        kwargs["extra"] = extra
        return cls(**kwargs)


def _normalize_trace_id(value: Any) -> str:
    """Keep a valid 32-hex trace id, otherwise mint a fresh one."""
    text = str(value or "").replace("-", "").lower()
    if len(text) == 32:
        try:
            int(text, 16)
            return text
        except ValueError:
            pass
    return new_trace_id()


def _orchestration_attributes(obs: OrchestrationObservation) -> dict[str, str | int | float | bool]:
    """Fields with no home in the v0 event, placed in the attributes bag."""
    candidates: dict[str, Any] = {
        "orchestration.schema": SCHEMA,
        "orchestration.decision_backend": obs.decision_backend,
        "orchestration.candidate_action_count": obs.candidate_action_count,
        "orchestration.selected_action": obs.selected_action,
        "orchestration.executed_action": obs.executed_action,
        "orchestration.invalid_call": obs.invalid_call,
        "orchestration.irrelevant_call": obs.irrelevant_call,
        "orchestration.unnecessary_call": obs.unnecessary_call,
        "orchestration.dependency_violation": obs.dependency_violation,
        "orchestration.parallelizable_but_serialized": obs.parallelizable_but_serialized,
        "orchestration.recovery_success": obs.recovery_success,
        "orchestration.escalated": obs.escalated,
        "orchestration.abstained": obs.abstained,
        "orchestration.decision_latency_ms": obs.decision_latency_ms,
        "orchestration.tool_latency_ms": obs.tool_latency_ms,
        "orchestration.gpu_ms": obs.gpu_ms,
        "orchestration.vram_peak_mib": obs.vram_peak_mib,
        "orchestration.local_cost_usd": obs.local_cost_usd,
        "orchestration.provider_cost_usd": obs.provider_cost_usd,
    }
    return {key: value for key, value in candidates.items() if value is not None}


def observation_to_event(
    obs: OrchestrationObservation,
    *,
    harness: str | None = None,
    ts: float | None = None,
) -> TokenomicsEvent:
    """Convert to a canonical ``tokenomics.event.v0`` event with ``kind='decision'``.

    ``Outcome.execution_completed`` / ``Outcome.verified_success`` are copied
    verbatim from the observation: the runtime execution signal and the
    independently verified gold signal are distinct, and ``verified_success``
    is never inferred or defaulted.
    """
    outcome = None
    if any(
        value is not None
        for value in (obs.execution_completed, obs.verified_success, obs.retry_count)
    ):
        outcome = Outcome(
            execution_completed=obs.execution_completed,
            verified_success=obs.verified_success,
            retries=obs.retry_count,
            source="orchestration",
            # verification_source is deliberately left unset: the caller owns it.
        )

    has_usage = any(
        value is not None
        for value in (obs.prompt_tokens, obs.completion_tokens, obs.cache_tokens)
    )
    usage = (
        TokenUsage(
            input_tokens=obs.prompt_tokens,
            output_tokens=obs.completion_tokens,
            cached_input_tokens=obs.cache_tokens,
            attribution="incremental",
            source="provider",
        )
        if has_usage
        else None
    )

    has_latency = obs.ttft_ms is not None or obs.end_to_end_latency_ms is not None
    latency = (
        Latency(duration_ms=obs.end_to_end_latency_ms, ttft_ms=obs.ttft_ms)
        if has_latency
        else None
    )

    cost_usd = None
    if obs.local_cost_usd is not None or obs.provider_cost_usd is not None:
        cost_usd = float(obs.local_cost_usd or 0.0) + float(obs.provider_cost_usd or 0.0)
    economics = Economics(cost_usd=cost_usd) if cost_usd is not None else None

    model = (
        ModelRef(name=obs.model_id, revision=obs.revision)
        if (obs.model_id or obs.revision)
        else None
    )

    if obs.invalid_call or obs.dependency_violation:
        status = "error"
    elif obs.execution_completed is True:
        status = "ok"
    elif obs.execution_completed is False:
        status = "error"
    else:
        status = "unknown"

    event = TokenomicsEvent(
        kind="decision",
        name="orchestration.decision",
        trace_id=_normalize_trace_id(obs.trace_id),
        span_id=new_span_id(),
        harness=harness,
        service="orchestration",
        role="router",
        status=status,
        model=model,
        usage=usage,
        economics=economics,
        latency=latency,
        outcome=outcome,
        attributes=_orchestration_attributes(obs),
        extra=dict(obs.extra),
    )
    if ts is not None:
        event.ts = float(ts)
    return event


_COUNTER_FIELDS = (
    "invalid_call",
    "irrelevant_call",
    "unnecessary_call",
    "dependency_violation",
    "parallelizable_but_serialized",
    "recovery_success",
    "escalated",
    "abstained",
)


def summarize_observations(observations: Sequence[OrchestrationObservation]) -> dict:
    """Aggregate observations into a report.

    Counter fields are reported as integer totals (``True`` counts; summed
    retries) plus the number of rows that actually carried the field, so a
    zero is never confused with "not observed".  Rates are computed only over
    rows where the underlying fields are present.  Every latency mean is
    reported next to p50/p95/p99.
    """
    rows = list(observations)
    counters: dict[str, int] = {}
    observed: dict[str, int] = {}
    for key in _COUNTER_FIELDS:
        counters[key] = sum(1 for row in rows if getattr(row, key) is True)
        observed[key] = sum(1 for row in rows if getattr(row, key) is not None)
    counters["retry_count"] = sum(
        int(row.retry_count) for row in rows if row.retry_count is not None
    )
    observed["retry_count"] = sum(1 for row in rows if row.retry_count is not None)

    comparable = [
        row
        for row in rows
        if row.selected_action is not None and row.executed_action is not None
    ]
    selected_equals_executed = (
        sum(1 for row in comparable if row.selected_action == row.executed_action) / len(comparable)
        if comparable
        else None
    )

    verified = [row for row in rows if row.verified_success is not None]
    verified_success_rate = (
        sum(1 for row in verified if row.verified_success is True) / len(verified)
        if verified
        else None
    )

    return {
        "schema": SCHEMA,
        "count": len(rows),
        "decision_latency": summarize_latency([row.decision_latency_ms for row in rows]).to_dict(),
        "ttft": summarize_latency([row.ttft_ms for row in rows]).to_dict(),
        "tool_latency": summarize_latency([row.tool_latency_ms for row in rows]).to_dict(),
        "end_to_end_latency": summarize_latency(
            [row.end_to_end_latency_ms for row in rows]
        ).to_dict(),
        "counters": counters,
        "counter_observed": observed,
        "selected_equals_executed": selected_equals_executed,
        "selected_equals_executed_count": len(comparable),
        "verified_success_rate": verified_success_rate,
        "verified_success_count": len(verified),
    }
