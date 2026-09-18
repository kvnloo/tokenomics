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
        extra={
            "allocation_id": raw.get("allocation_id"),
            "placement_only": True,
        },
    )


def from_flow_prepare(raw: dict[str, Any], *, harness: str = "flow") -> TokenomicsEvent:
    """Map a Flow prepare lifecycle row into tokenomics.event.v0 kind=prepare.

    Accounting rule: prepare_created never receives token-avoidance credit.
    Token avoidance only when outcome=prepare_consumed AND frontier_tokens_replaced > 0.
    """
    outcome = str(raw.get("prepare_outcome") or raw.get("outcome") or "prepare_created")
    cost_ms = raw.get("prepare_cost_ms", raw.get("cost_ms"))
    try:
        cost_ms_f = float(cost_ms) if cost_ms is not None else None
    except (TypeError, ValueError):
        cost_ms_f = None
    bytes_v = raw.get("prepare_bytes", raw.get("bytes"))
    try:
        bytes_i = int(bytes_v) if bytes_v is not None else None
    except (TypeError, ValueError):
        bytes_i = None
    ttc = raw.get("time_to_commit_ms")
    try:
        ttc_f = float(ttc) if ttc is not None else None
    except (TypeError, ValueError):
        ttc_f = None
    hidden = raw.get("latency_hidden_ms")
    try:
        hidden_f = float(hidden) if hidden is not None else None
    except (TypeError, ValueError):
        hidden_f = None
    # Only consumed prepares may hide latency / replace frontier tokens.
    if outcome != "prepare_consumed":
        hidden_f = None
        frontier_replaced = None
    else:
        fr = raw.get("frontier_tokens_replaced")
        try:
            frontier_replaced = int(fr) if fr is not None else None
        except (TypeError, ValueError):
            frontier_replaced = None
        # Default latency_hidden to prepare_cost when consume and ready before commit.
        if hidden_f is None and cost_ms_f is not None:
            hidden_f = cost_ms_f

    measured_avoided = None
    estimated_avoided = None
    if outcome == "prepare_consumed" and frontier_replaced and frontier_replaced > 0:
        measured_avoided = frontier_replaced

    provider = raw.get("prepare_provider") or raw.get("provider") or raw.get("operator_family")
    tid = raw.get("trace_id") or raw.get("prediction_id") or raw.get("pred_id")
    return TokenomicsEvent(
        kind="prepare",
        name=str(raw.get("name") or f"flow.prepare.{outcome}"),
        trace_id=_trace_id(tid),
        span_id=new_span_id(),
        session_id=raw.get("session_id"),
        capability_id=raw.get("capability_id") or raw.get("operator_family") or "flow.prepare",
        harness=harness,
        role="router",
        status="ok" if outcome in {"prepare_created", "prepare_consumed", "would_prepare"} else "cancelled",
        economics=Economics(
            estimated_tokens_avoided=estimated_avoided,
            measured_tokens_avoided=measured_avoided,
            prepare_outcome=outcome,
            prepare_cost_ms=cost_ms_f,
            prepare_bytes=bytes_i,
            prepare_provider=str(provider) if provider is not None else None,
            time_to_commit_ms=ttc_f,
            latency_hidden_ms=hidden_f,
            manual_equivalent=bool(raw["manual_equivalent"]) if raw.get("manual_equivalent") is not None else None,
            frontier_tokens_replaced=frontier_replaced if outcome == "prepare_consumed" else None,
        ),
        latency=Latency(duration_ms=cost_ms_f),
        started_at=raw.get("started_at"),
        ended_at=raw.get("ready_at") or raw.get("ended_at"),
        ts=float(raw.get("ts") or raw.get("ready_at") or raw.get("started_at") or __import__("time").time()),
        extra={
            "cache_key": raw.get("cache_key"),
            "context_id": raw.get("context_id"),
            "prediction_id": raw.get("prediction_id") or raw.get("pred_id"),
            "operator_family": raw.get("operator_family"),
            "kind": raw.get("kind"),
            "legacy_schema": raw.get("schema"),
            "horizon_ms": raw.get("horizon_ms"),
            "prepare_arm": raw.get("prepare_arm"),
            "commit_setup_ms": raw.get("commit_setup_ms"),
            "counterfactual_blocking_ms": raw.get("counterfactual_blocking_ms"),
            "test_execution_ms": raw.get("test_execution_ms"),
        },
    )


def from_flow_prediction(raw: dict[str, Any], *, harness: str = "flow") -> TokenomicsEvent | None:
    """Lift prepare block from a flow_prediction.v1 receipt when present."""
    prepare = raw.get("prepare") if isinstance(raw.get("prepare"), dict) else None
    if not prepare or not prepare.get("eligible"):
        return None
    outcome = prepare.get("outcome") or (
        "prepare_consumed"
        if (isinstance(raw.get("commit"), dict) and raw["commit"].get("committed"))
        else "prepare_created"
    )
    started = prepare.get("started_at")
    committed_at = (raw.get("commit") or {}).get("committed_at") if isinstance(raw.get("commit"), dict) else None
    ttc = None
    if started is not None and committed_at is not None and outcome == "prepare_consumed":
        try:
            ttc = max(0.0, (float(committed_at) - float(started)) * 1000.0)
        except (TypeError, ValueError):
            ttc = None
    return from_flow_prepare(
        {
            "schema": raw.get("schema"),
            "prepare_outcome": outcome,
            "prepare_cost_ms": prepare.get("cost_ms"),
            "prepare_bytes": prepare.get("bytes"),
            "prepare_provider": prepare.get("provider") or prepare.get("operator_family") or prepare.get("kind"),
            "time_to_commit_ms": ttc,
            "latency_hidden_ms": prepare.get("latency_hidden_ms"),
            "frontier_tokens_replaced": prepare.get("frontier_tokens_replaced"),
            "manual_equivalent": (raw.get("actual") or {}).get("manual_equivalent")
            if isinstance(raw.get("actual"), dict)
            else None,
            "prediction_id": raw.get("prediction_id"),
            "context_id": raw.get("context_id"),
            "operator_family": prepare.get("operator_family"),
            "capability_id": prepare.get("operator_family") or "flow.prepare",
            "cache_key": prepare.get("cache_key"),
            "started_at": prepare.get("started_at"),
            "ready_at": prepare.get("ready_at"),
            "ts": raw.get("timestamp") or prepare.get("ready_at") or prepare.get("started_at"),
            "kind": prepare.get("kind"),
        },
        harness=harness,
    )


def from_bespoke_curation(raw: dict[str, Any], *, harness: str = "bespoke") -> TokenomicsEvent:
    """Optional importer for Bespoke/Nimble-style curation records.

    Maps measurement + lineage only. Does **not** set outcome.verified_success
    from curation.accepted — synthetic construction checks ≠ live task success.

    Distinguishes reuse_kind: fresh | cache | offline_replay so Tokenomics does
    not double-count provider cost on cache/replay hits.
    """
    accepted = raw.get("accepted", raw.get("curation_accepted"))
    if isinstance(accepted, str):
        acceptance_status = accepted
    elif accepted is True:
        acceptance_status = "accepted"
    elif accepted is False:
        acceptance_status = "rejected"
    else:
        acceptance_status = raw.get("acceptance_status")

    reuse = str(raw.get("reuse_kind") or raw.get("reuse") or "fresh")
    cost = raw.get("cost_usd")
    usage_in = raw.get("input_tokens")
    usage_out = raw.get("output_tokens")
    # cache/offline must not invent a second provider charge
    if reuse in ("cache", "offline_replay", "offline"):
        cost = None
        # keep tokens as derived reference only
        usage_source = "derived"
    else:
        usage_source = "provider" if (usage_in is not None or usage_out is not None) else "unknown"

    exp = Experiment(
        experiment_id=raw.get("experiment_id"),
        pair_id=raw.get("pair_id") or raw.get("contrast_group_id"),
        task_snapshot_id=raw.get("task_snapshot_id") or raw.get("parent_example_id"),
        arm_id=raw.get("arm_id") or raw.get("intervention_kind"),
        treatment_hash=raw.get("treatment_hash"),
        parent_example_id=raw.get("parent_example_id"),
        contrast_group_id=raw.get("contrast_group_id") or raw.get("pair_id"),
        source_family_id=raw.get("source_family_id"),
        intervention_kind=raw.get("intervention_kind"),
        supervision_kind=raw.get("supervision_kind") or raw.get("supervision"),
        acceptance_status=acceptance_status,
        rejection_stage=raw.get("rejection_stage"),
        gate_revision=raw.get("gate_revision"),
        reuse_kind=reuse,
        original_event_ref=raw.get("original_event_ref"),
        evaluation_cohort=raw.get("evaluation_cohort") or raw.get("split"),
        production_credit_eligible=False,  # hard rule
        verifier_class=raw.get("verifier_class") or "curation_gate",
    )

    # outcome: execution may complete; verified_success stays None
    outcome = Outcome(
        execution_completed=True if acceptance_status in ("accepted", "rejected", "partial") else None,
        verified_success=None,
        note="curation_record_not_live_verified",
        source="bespoke_curation",
        verification_source=None,
    )

    return TokenomicsEvent(
        kind="curation",
        name=str(raw.get("name") or raw.get("gate") or "bespoke.curation"),
        trace_id=_trace_id(raw.get("trace_id")),
        span_id=new_span_id(),
        task_id=raw.get("task_id") or raw.get("parent_example_id"),
        capability_id=raw.get("capability_id") or "curation.contrast_pair",
        harness=harness,
        service=str(raw.get("service") or "bespoke"),
        role="other",
        status="ok" if acceptance_status == "accepted" else ("error" if acceptance_status == "rejected" else "unknown"),
        model=ModelRef(
            provider=raw.get("provider"),
            name=raw.get("model"),
            revision=raw.get("model_revision"),
        )
        if (raw.get("provider") or raw.get("model"))
        else None,
        usage=TokenUsage(
            input_tokens=int(usage_in) if usage_in is not None else None,
            output_tokens=int(usage_out) if usage_out is not None else None,
            source=usage_source,  # type: ignore[arg-type]
        )
        if (usage_in is not None or usage_out is not None)
        else None,
        economics=Economics(cost_usd=float(cost) if cost is not None else None),
        latency=Latency(
            duration_ms=raw.get("duration_ms"),
            queue_ms=raw.get("queue_ms"),
        ),
        experiment=exp,
        outcome=outcome,
        attributes={
            k: v
            for k, v in {
                "tokenomics.curation.accepted": bool(acceptance_status == "accepted"),
                "tokenomics.curation.reuse": reuse,
            }.items()
        },
        extra={
            "curation_accepted": acceptance_status == "accepted",
            "conditions": raw.get("conditions"),
            "pair_pass": raw.get("pair_pass"),
            "original_event_ref": raw.get("original_event_ref"),
        },
    )

def _usage_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else raw
    return usage if isinstance(usage, dict) else {}


def from_provider_usage(
    raw: dict[str, Any],
    *,
    harness: str,
    role: str = "root",
    attribution: str = "incremental",
) -> TokenomicsEvent:
    """Map canonical provider usage (OMP/Hermes/RLM worker) to tokenomics.event.v0."""
    usage = _usage_from_raw(raw)
    inp = usage.get("input_tokens", usage.get("prompt_tokens"))
    out = usage.get("output_tokens", usage.get("completion_tokens"))
    cached = usage.get("cached_input_tokens", usage.get("cache_read_tokens"))
    cache_write = usage.get("cache_write_input_tokens", usage.get("cache_write_tokens"))
    reasoning = usage.get("reasoning_tokens", usage.get("reasoning_output_tokens"))
    reported = usage.get("total_tokens", usage.get("reported_total_tokens"))
    cost = raw.get("cost_usd", raw.get("estimated_cost_usd"))
    try:
        cost_f = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_f = None
    return TokenomicsEvent(
        kind=str(raw.get("kind") or "llm"),
        name=str(raw.get("name") or f"{harness}.provider_call"),
        trace_id=_trace_id(raw.get("trace_id") or raw.get("session_id")),
        span_id=str(raw.get("span_id") or new_span_id()),
        parent_span_id=raw.get("parent_span_id"),
        session_id=raw.get("session_id"),
        task_id=raw.get("task_id"),
        capability_id=raw.get("capability_id"),
        harness=harness,
        role=role,  # type: ignore[arg-type]
        status=str(raw.get("status") or "ok"),  # type: ignore[arg-type]
        model=ModelRef(
            provider=raw.get("provider"),
            name=raw.get("model"),
            origin_provider=raw.get("origin_provider") or raw.get("upstream_provider"),
        )
        if (raw.get("provider") or raw.get("model"))
        else None,
        usage=TokenUsage(
            input_tokens=int(inp) if inp is not None else None,
            output_tokens=int(out) if out is not None else None,
            cached_input_tokens=int(cached) if cached is not None else None,
            cache_write_input_tokens=int(cache_write) if cache_write is not None else None,
            reasoning_tokens=int(reasoning) if reasoning is not None else None,
            reported_total_tokens=int(reported) if reported is not None else None,
            attribution=attribution,  # type: ignore[arg-type]
            source="provider",
        ),
        economics=Economics(cost_usd=cost_f),
        latency=Latency(duration_ms=raw.get("latency_ms") or raw.get("api_duration_ms")),
        ts=float(raw.get("ts") or raw.get("timestamp") or __import__("time").time()),
        extra={
            "legacy_schema": raw.get("schema"),
            "allocation_id": raw.get("allocation_id"),
            "request_id": raw.get("request_id") or raw.get("response_id"),
            "context_policy": raw.get("context_policy"),
        },
    )


def from_omp_provider_usage(raw: dict[str, Any]) -> TokenomicsEvent:
    """Thin adapter for OMP canonical provider usage rows."""
    role = str(raw.get("role") or "root")
    if role not in {"root", "rlm_worker", "subagent", "verifier", "router", "other"}:
        role = "root"
    return from_provider_usage(raw, harness="omp", role=role, attribution="incremental")


def from_omp_session_aggregate(raw: dict[str, Any]) -> TokenomicsEvent:
    """OMP session summary — aggregate reconciliation only."""
    ev = from_omp_provider_usage(raw)
    usage = ev.usage
    if usage is None:
        return ev
    object.__setattr__(ev, "usage", TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        reported_total_tokens=usage.reported_total_tokens or usage.total(),
        attribution="aggregate",
        source="provider",
    ))
    return ev


def from_hermes_provider_usage(raw: dict[str, Any]) -> TokenomicsEvent:
    """Thin adapter for Hermes turn_usage / aux_accounting usage rows."""
    role = str(raw.get("role") or "root")
    if role not in {"root", "rlm_worker", "subagent", "verifier", "router", "other"}:
        role = "root"
    return from_provider_usage(raw, harness="hermes", role=role, attribution="incremental")


def from_hermes_session_aggregate(raw: dict[str, Any]) -> TokenomicsEvent:
    ev = from_hermes_provider_usage(raw)
    usage = ev.usage
    if usage is None:
        return ev
    object.__setattr__(ev, "usage", TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        cache_write_input_tokens=usage.cache_write_input_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        reported_total_tokens=usage.reported_total_tokens or usage.total(),
        attribution="aggregate",
        source="provider",
    ))
    return ev

