from __future__ import annotations

from typing import Any

from .ids import new_span_id, new_trace_id
from .models import (
    Economics,
    Experiment,
    Latency,
    ModelRef,
    Outcome,
    QuotaSnapshot,
    TokenUsage,
    TokenomicsEvent,
)


def _trace_id(value: Any) -> str:
    text = str(value or "").replace("-", "").lower()
    if len(text) == 32:
        try:
            int(text, 16)
            return text
        except ValueError:
            pass
    return new_trace_id()


def _outcome(raw: Any) -> Outcome | None:
    if not isinstance(raw, dict):
        return None
    known = Outcome.__dataclass_fields__
    return Outcome(**{k: v for k, v in raw.items() if k in known})


def from_z0int_receipt(raw: dict[str, Any], *, harness: str = "z0int") -> TokenomicsEvent:
    """Map a z0int.decision_receipt.v1-compatible row into the neutral schema."""
    extra = raw.get("extra") if isinstance(raw.get("extra"), dict) else {}
    experiment_keys = {
        "experiment_id",
        "pair_id",
        "task_snapshot_id",
        "arm_id",
        "treatment_hash",
        "selection_policy",
        "assignment_probability",
        "reference_requested",
        "reason_for_reference",
        "replay_grade",
        "verifier_class",
    }
    exp_data = {k: raw.get(k, extra.get(k)) for k in experiment_keys}
    exp_data = {k: v for k, v in exp_data.items() if v is not None}
    baseline = None
    if raw.get("baseline_input_tokens") is not None or raw.get("baseline_output_tokens") is not None:
        baseline = int(raw.get("baseline_input_tokens") or 0) + int(raw.get("baseline_output_tokens") or 0)
    measured = raw.get("measured_frontier_tokens")
    measured_i = int(measured) if measured is not None else None
    # Never collapse tiers: measured requires paired baseline+actual.
    measured_avoided = None
    if baseline is not None and measured_i is not None:
        measured_avoided = max(0, int(baseline) - measured_i)
    elif raw.get("actual_tokens_saved") is not None and measured_i is not None:
        try:
            measured_avoided = max(0, int(raw["actual_tokens_saved"]))
        except (TypeError, ValueError):
            measured_avoided = None
    est_avoided = raw.get("estimated_frontier_tokens_avoided")
    try:
        est_avoided_i = int(est_avoided) if est_avoided is not None else None
    except (TypeError, ValueError):
        est_avoided_i = None
    route = raw.get("route")
    return TokenomicsEvent(
        kind="decision",
        name=str(raw.get("capability_id") or raw.get("action_taken") or "z0int.decision"),
        trace_id=_trace_id(raw.get("trace_id")),
        span_id=new_span_id(),
        session_id=raw.get("session_id"),
        capability_id=raw.get("capability_id"),
        harness=harness,
        role="router",
        status="ok" if raw.get("outcome_tier") != "negative" else "error",
        model=ModelRef(provider=raw.get("provider"), name=raw.get("model")),
        usage=TokenUsage(
            input_tokens=raw.get("input_tokens"),
            output_tokens=raw.get("output_tokens"),
            cached_input_tokens=raw.get("cached_input_tokens"),
            reported_total_tokens=measured,
            attribution="incremental",
            source="provider" if measured is not None else "unknown",
        ),
        economics=Economics(
            estimated_tokens_avoided=est_avoided_i,
            measured_tokens_avoided=measured_avoided,
        ),
        latency=Latency(duration_ms=raw.get("latency_ms")),
        experiment=Experiment(**exp_data) if exp_data else None,
        outcome=_outcome(raw.get("outcome")),
        ts=float(raw.get("ts") or raw.get("close_ts") or 0) or __import__("time").time(),
        extra={
            "legacy_schema": raw.get("schema"),
            "baseline_total_tokens": baseline,
            "measured_frontier_tokens": measured_i,
            "route": route,
            "action_taken": raw.get("action_taken"),
            "execution": raw.get("execution"),
        },
    )


def from_kerdoios_observation(raw: dict[str, Any], *, harness: str = "kerdoios") -> TokenomicsEvent:
    """Map a Kerdoios observed-execution row into the neutral schema."""
    quota_before = None
    quota_after = None
    if raw.get("quota_before") is not None:
        quota_before = QuotaSnapshot(remaining=float(raw["quota_before"]), source=raw.get("remaining_source"))
    if raw.get("quota_after") is not None or raw.get("remaining_quota") is not None:
        value = raw.get("quota_after", raw.get("remaining_quota"))
        quota_after = QuotaSnapshot(remaining=float(value), source=raw.get("remaining_source"))
    outcome = Outcome(
        execution_completed=bool(raw.get("completed")),
        verified_success=True if raw.get("verified") is True else None,
        success=bool(raw.get("completed")),
        source="kerdoios_observed",
        retries=int(raw.get("fallback_count") or (1 if raw.get("retried") else 0)),
    )
    return TokenomicsEvent(
        kind="placement",
        name=str(raw.get("capability_id") or raw.get("task_type") or "kerdoios.placement"),
        trace_id=_trace_id(raw.get("trace_id")),
        span_id=new_span_id(),
        session_id=raw.get("session_id"),
        capability_id=raw.get("capability_id"),
        harness=harness,
        role="router",
        status="ok" if raw.get("completed") else "error",
        model=ModelRef(
            provider=raw.get("provider"),
            origin_provider=raw.get("origin_provider"),
            name=raw.get("model"),
        ),
        usage=TokenUsage(
            input_tokens=raw.get("input_tokens"),
            output_tokens=raw.get("output_tokens"),
            cached_input_tokens=raw.get("cached_input_tokens"),
            context_tokens=raw.get("context_tokens"),
            attribution="incremental",
            source="provider",
        ),
        economics=Economics(cost_usd=float(raw.get("actual_cost") or 0.0)),
        latency=Latency(duration_ms=raw.get("latency_ms")),
        quota_before=quota_before,
        quota_after=quota_after,
        outcome=outcome,
        attributes={
            k: v
            for k, v in {
                "tokenomics.retry": bool(raw.get("retried")),
                "tokenomics.fallback.count": int(raw.get("fallback_count") or 0),
                "http.response.status_code": raw.get("http_status"),
                "error.type": raw.get("error_class"),
            }.items()
            if v is not None
        },
    )
