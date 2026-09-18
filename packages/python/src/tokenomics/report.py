"""Canonical tokenomics.report.v1 — savings without collapsing tiers."""

from __future__ import annotations

import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from .adapters import (
    from_bespoke_curation,
    from_flow_prediction,
    from_flow_prepare,
    from_hermes_provider_usage,
    from_hermes_session_aggregate,
    from_kerdoios_observation,
    from_omp_provider_usage,
    from_omp_session_aggregate,
    from_z0int_receipt,
)
from .aggregate import summarize_traces, tokens_per_verified_task
from .models import TokenomicsEvent

REPORT_SCHEMA = "tokenomics.report.v1"
SavingsTier = Literal["measured", "estimated", "unknown"]


def parse_range(spec: str, *, now: float | None = None) -> tuple[float, float]:
    """Parse range like today|7d|30d|all|24h into (start_ts, end_ts) local-aware UTC."""
    end = now if now is not None else time.time()
    s = (spec or "7d").strip().lower()
    if s in {"all", "*"}:
        return 0.0, end
    if s == "today":
        # local midnight
        local = datetime.now().astimezone()
        start_dt = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_dt.timestamp(), end
    if s.endswith("d") and s[:-1].isdigit():
        days = int(s[:-1])
        return end - days * 86400.0, end
    if s.endswith("h") and s[:-1].isdigit():
        hours = int(s[:-1])
        return end - hours * 3600.0, end
    if s.endswith("m") and s[:-1].isdigit():
        mins = int(s[:-1])
        return end - mins * 60.0, end
    raise ValueError(f"unsupported range {spec!r}; use today|7d|30d|24h|all")


def _usage_attribution(ev: TokenomicsEvent) -> str:
    if ev.usage is None:
        return "none"
    return str(ev.usage.attribution or "unknown")


def _is_aggregate_usage(ev: TokenomicsEvent) -> bool:
    return ev.usage is not None and ev.usage.attribution == "aggregate"


def _is_incremental_usage(ev: TokenomicsEvent) -> bool:
    return ev.usage is not None and ev.usage.attribution == "incremental"


def _event_usage_tokens(ev: TokenomicsEvent) -> int:
    if ev.usage is None:
        return 0
    return int(ev.usage.total() or 0)


def _baseline_tokens(ev: TokenomicsEvent) -> int | None:
    extra = ev.extra or {}
    if extra.get("baseline_total_tokens") is not None:
        try:
            return int(extra["baseline_total_tokens"])
        except (TypeError, ValueError):
            return None
    return None


def _measured_frontier(ev: TokenomicsEvent) -> int | None:
    if _is_aggregate_usage(ev):
        return None
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
    if ev.usage and ev.usage.source == "provider":
        tot = ev.usage.total()
        if tot:
            return int(tot)
    return None




def _actual_tokens(ev: TokenomicsEvent) -> int:
    """Tokens actually spent on frontier (0 if fully offloaded/local).

    Aggregate attribution rows are reconciliation evidence only — never additive.
    """
    if _is_aggregate_usage(ev):
        return 0
    m = _measured_frontier(ev)
    if m is not None:
        return max(0, m)
    if ev.usage and ev.usage.source == "provider":
        return int(ev.usage.total() or 0)
    route = str((ev.extra or {}).get("route") or "")
    if route in {"local", "local_model", "routine", "specialist", "log_only"}:
        return 0
    if ev.usage:
        attr = _usage_attribution(ev)
        if attr in {"incremental", "unknown"}:
            return int(ev.usage.total() or 0)
        return 0
    return 0



def classify_savings(ev: TokenomicsEvent) -> tuple[SavingsTier, int, int, int]:
    """Return (tier, baseline, actual, avoided) for one event.

    MEASURED: paired baseline + measured frontier, OR consume that replaced frontier tokens.
    ESTIMATED: estimate field present (and not already counted as measured).
    UNKNOWN: no trustworthy baseline/estimate.

    Prepare create/expire/invalidate never contribute token avoidance.
    Aggregate attribution usage is reconciliation-only (summarize_trace semantics).
    """
    if _is_aggregate_usage(ev):
        return "unknown", 0, 0, 0
    econ = ev.economics
    if econ and econ.prepare_outcome:
        outcome = econ.prepare_outcome
        if outcome != "prepare_consumed":
            return "unknown", 0, 0, 0
        if econ.measured_tokens_avoided and econ.measured_tokens_avoided > 0:
            return "measured", int(econ.measured_tokens_avoided), 0, int(econ.measured_tokens_avoided)
        return "unknown", 0, 0, 0

    base = _baseline_tokens(ev)
    measured = _measured_frontier(ev)
    est = int(econ.estimated_tokens_avoided) if econ and econ.estimated_tokens_avoided is not None else None
    meas_av = int(econ.measured_tokens_avoided) if econ and econ.measured_tokens_avoided is not None else None

    if base is not None and measured is not None:
        avoided = max(0, base - measured)
        if meas_av is not None:
            avoided = max(0, meas_av)
        return "measured", base, measured, avoided

    if est is not None and est > 0:
        actual = _actual_tokens(ev)
        return "estimated", base if base is not None else 0, actual, est

    if base is not None:
        actual = _actual_tokens(ev)
        return "unknown", base, actual, 0

    actual = _actual_tokens(ev)
    return "unknown", 0, actual, 0


def _mechanism(ev: TokenomicsEvent) -> str:
    extra = ev.extra or {}
    route = str(extra.get("route") or "").lower()
    cap = str(ev.capability_id or ev.name or "").lower()
    if route in {"routine"} or "routine" in cap:
        return "routine"
    if route in {"specialist", "local_model"} or "specialist" in cap:
        return "specialist"
    if route in {"local"} or "jev" in cap or "nanojev" in cap:
        return "jev"
    if "context" in cap or "compress" in cap:
        return "context_compression"
    if "cache" in cap:
        return "cache"
    if route in {"model", "frontier", "cloud"} or (ev.model and ev.model.provider):
        # offload residual still on frontier
        if classify_savings(ev)[0] == "measured" and classify_savings(ev)[3] > 0:
            return "model_routing"
        return "frontier"
    if route in {"log_only"}:
        return "log_only"
    return "other"


def z0int_home() -> Path:
    override = os.environ.get("Z0INT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".z0int"


def load_events_from_paths(paths: Iterable[Path]) -> list[TokenomicsEvent]:
    events: list[TokenomicsEvent] = []
    for path in paths:
        if not path or not Path(path).is_file():
            continue
        path = Path(path)
        for raw in _iter_raw_jsonl(path):
            ev = _coerce_event(raw)
            if ev is not None:
                events.append(ev)
    return events


def _iter_raw_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _coerce_event(raw: dict[str, Any]) -> TokenomicsEvent | None:
    schema = str(raw.get("schema") or "")
    # Nested bridge envelope
    if isinstance(raw.get("receipt"), dict):
        rec = dict(raw["receipt"])
        if raw.get("outcome") and "outcome" not in rec:
            rec["outcome"] = raw["outcome"]
        if raw.get("outcome_tier") and "outcome_tier" not in rec:
            rec["outcome_tier"] = raw["outcome_tier"]
        raw = rec
        schema = str(raw.get("schema") or schema)


    if schema.startswith("tokenomics.event"):
        try:
            return TokenomicsEvent.from_dict(raw)
        except Exception:
            return None
    if schema in {"omp.provider_usage.v0", "omp.session_usage.v0"} or (
        str(raw.get("harness") or "").lower() == "omp" and raw.get("usage")
    ):
        try:
            if schema.endswith("session_usage.v0") or raw.get("attribution") == "aggregate":
                return from_omp_session_aggregate(raw)
            return from_omp_provider_usage(raw)
        except Exception:
            return None
    if schema in {"hermes.provider_usage.v0", "hermes.session_usage.v0"} or (
        str(raw.get("harness") or "").lower() == "hermes" and (raw.get("usage") or raw.get("input_tokens") is not None)
    ):
        try:
            if schema.endswith("session_usage.v0") or raw.get("attribution") == "aggregate":
                return from_hermes_session_aggregate(raw)
            return from_hermes_provider_usage(raw)
        except Exception:
            return None
    if schema.startswith("bespoke.") or raw.get("intervention_kind"):
        try:
            return from_bespoke_curation(raw)
        except Exception:
            return None
    # Flow prepare lifecycle BEFORE z0int catch-all (rows also carry capability_id).
    if schema.startswith("flow.prepare") or raw.get("prepare_outcome"):
        try:
            return from_flow_prepare(raw)
        except Exception:
            return None
    # flow_prediction.v1 with prepare block
    if schema == "flow_prediction.v1":
        try:
            return from_flow_prediction(raw)
        except Exception:
            return None
    if schema.startswith("z0int.decision_receipt") or (
        ("capability_id" in raw or "baseline_input_tokens" in raw)
        and schema.startswith("z0int")
    ) or (
        schema == ""
        and ("baseline_input_tokens" in raw or "estimated_frontier_tokens_avoided" in raw)
    ):
        try:
            return from_z0int_receipt(raw)
        except Exception:
            return None
    # Legacy bare decision rows without schema
    if "capability_id" in raw and (
        "baseline_input_tokens" in raw
        or "estimated_frontier_tokens_avoided" in raw
        or "measured_frontier_tokens" in raw
        or raw.get("schema", "").startswith("z0int")
    ):
        try:
            return from_z0int_receipt(raw)
        except Exception:
            return None
    if schema.startswith("kerdoios") or "observed_execution" in schema or (
        "provider" in raw and "model" in raw and "input_tokens" in raw
    ):
        try:
            return from_kerdoios_observation(raw)
        except Exception:
            return None
    # Generic tokenomics-ish
    if "trace_id" in raw and ("usage" in raw or "economics" in raw or raw.get("kind") == "prepare"):
        try:
            return TokenomicsEvent.from_dict(raw)
        except Exception:
            return None
    return None


def default_sources(*, root: Path | None = None) -> list[Path]:
    """Discover local measurement streams without requiring a UI."""
    home = root or z0int_home()
    paths: list[Path | None] = [
        home / "receipts" / "decisions.jsonl",
        home / "receipts" / "flow_predictions.jsonl",
        home / "stream" / "bridge.jsonl",
        home / "tokenomics" / "events.jsonl",
        home / "tokenomics" / "prepare_events.jsonl",
    ]
    omp_home = Path(os.environ.get("OMP_HOME", Path.home() / ".omp")).expanduser()
    omp_tokenomics = omp_home / "tokenomics"
    if omp_tokenomics.is_dir():
        paths.extend(sorted(omp_tokenomics.glob("events-*.jsonl")))
    env_jsonl = os.environ.get("TOKENOMICS_JSONL")
    if env_jsonl:
        paths.append(Path(env_jsonl).expanduser())
    return [p for p in paths if p is not None]


def _build_reconciliation(
    rows: list[TokenomicsEvent],
    *,
    baseline_sum: int,
    actual_sum: int,
    measured_avoided: int,
    estimated_avoided: int,
    unknown_baseline_tokens: int,
) -> dict[str, Any]:
    """Trace-level reconciliation using summarize_trace attribution semantics."""
    usage_rows = [e for e in rows if e.usage is not None]
    trace_summaries = summarize_traces(usage_rows) if usage_rows else []

    incremental_tokens = sum(s.total_tokens for s in trace_summaries)
    aggregate_reported = sum(
        int(s.aggregate_reported_tokens or 0)
        for s in trace_summaries
        if s.aggregate_reported_tokens is not None
    )
    reconciliation_deltas = [
        int(s.reconciliation_delta) for s in trace_summaries if s.reconciliation_delta is not None
    ]
    reconciliation_delta_tokens = sum(reconciliation_deltas) if reconciliation_deltas else None

    gross_delta = int(baseline_sum - actual_sum)
    explained = int(measured_avoided + estimated_avoided)
    unattributed_delta = gross_delta - explained

    has_aggregate = any(_is_aggregate_usage(e) for e in rows)
    unknown_attr_tokens = sum(
        _event_usage_tokens(e)
        for e in rows
        if e.usage is not None and _usage_attribution(e) == "unknown" and not _is_aggregate_usage(e)
    )

    if not has_aggregate:
        status = "no_aggregate_receipts"
    elif reconciliation_delta_tokens is None:
        status = "unknown"
    elif abs(reconciliation_delta_tokens) <= max(1, int(incremental_tokens * 0.001)):
        status = "reconciled"
    else:
        status = "delta_observed"

    return {
        "baseline_tokens": int(baseline_sum),
        "actual_tokens": int(actual_sum),
        "gross_delta_tokens": gross_delta,
        "measured_avoided_tokens": int(measured_avoided),
        "estimated_avoided_tokens": int(estimated_avoided),
        "unattributed_delta_tokens": unattributed_delta,
        "aggregate_reported_tokens": int(aggregate_reported) if has_aggregate else None,
        "incremental_tokens": int(incremental_tokens),
        "reconciliation_delta_tokens": reconciliation_delta_tokens,
        "unknown_attribution_tokens": int(unknown_attr_tokens),
        "unknown_or_no_baseline_tokens": int(unknown_baseline_tokens),
        "status": status,
        "role_breakdown": {
            "root_tokens": sum(s.root_tokens for s in trace_summaries),
            "rlm_worker_tokens": sum(s.worker_tokens for s in trace_summaries),
            "subagent_tokens": sum(s.subagent_tokens for s in trace_summaries),
            "verifier_tokens": sum(s.verifier_tokens for s in trace_summaries),
        },
        "n_traces_with_usage": len(trace_summaries),
    }


def _token_coverage(
    *,
    measured_avoided: int,
    estimated_avoided: int,
    unknown_tokens: int,
    actual_sum: int,
) -> dict[str, Any]:
    """Token-level tier coverage — measured and estimated remain separate."""
    frontier_mass = actual_sum + measured_avoided + estimated_avoided + unknown_tokens

    def _share(n: int) -> float | None:
        return round(n / frontier_mass, 4) if frontier_mass > 0 else None

    return {
        "measured": {"tokens": int(measured_avoided), "share": _share(measured_avoided)},
        "estimated": {"tokens": int(estimated_avoided), "share": _share(estimated_avoided)},
        "unknown_or_unattributed": {"tokens": int(unknown_tokens), "share": _share(unknown_tokens)},
        "actual_frontier": {"tokens": int(actual_sum), "share": _share(actual_sum)},
    }


def build_savings_report(
    events: Iterable[TokenomicsEvent],
    *,
    range_spec: str = "7d",
    now: float | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate tokenomics.report.v1 savings. Never collapses measured∪estimated."""
    start, end = parse_range(range_spec, now=now)
    rows = [e for e in events if start <= float(e.ts or 0) <= end]
    n = len(rows)

    baseline_sum = 0
    actual_sum = 0
    measured_avoided = 0
    estimated_avoided = 0
    unknown_baseline_tokens = 0
    n_measured = 0
    n_estimated = 0
    n_unknown = 0

    by_mech_avoided: Counter[str] = Counter()
    by_mech_actual: Counter[str] = Counter()
    by_harness_avoided: Counter[str] = Counter()
    by_harness_actual: Counter[str] = Counter()
    by_harness_verified: Counter[str] = Counter()
    by_cap_actual: Counter[str] = Counter()
    by_provider_actual: Counter[str] = Counter()
    by_model_actual: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()

    # daily buckets for timeseries (UTC date)
    ts_base: dict[str, int] = defaultdict(int)
    ts_actual: dict[str, int] = defaultdict(int)
    ts_meas: dict[str, int] = defaultdict(int)
    ts_est: dict[str, int] = defaultdict(int)

    for ev in rows:
        tier, base, actual, avoided = classify_savings(ev)
        by_tier[tier] += 1
        baseline_sum += base
        actual_sum += actual
        day = datetime.fromtimestamp(float(ev.ts or end), tz=timezone.utc).strftime("%Y-%m-%d")
        ts_base[day] += base
        ts_actual[day] += actual

        if tier == "measured":
            n_measured += 1
            measured_avoided += avoided
            ts_meas[day] += avoided
        elif tier == "estimated":
            n_estimated += 1
            estimated_avoided += avoided
            ts_est[day] += avoided
        else:
            n_unknown += 1
            if base <= 0 and actual > 0:
                unknown_baseline_tokens += actual

        mech = _mechanism(ev)
        by_mech_avoided[mech] += avoided
        by_mech_actual[mech] += actual
        harness = str(ev.harness or "unknown")
        by_harness_avoided[harness] += avoided
        by_harness_actual[harness] += actual
        cap = str(ev.capability_id or ev.name or "unknown")
        by_cap_actual[cap] += actual
        if ev.model:
            if ev.model.provider:
                by_provider_actual[str(ev.model.provider)] += actual
            if ev.model.name:
                by_model_actual[str(ev.model.name)] += actual
        if ev.outcome is not None and ev.outcome.tier() == "gold":
            by_harness_verified[harness] += 1

    verified_stats = tokens_per_verified_task(rows)
    # Baseline tokens / verified uses sum of baselines on gold traces when available
    gold_events = [e for e in rows if e.outcome is not None and e.outcome.tier() == "gold"]
    gold_base = sum(_baseline_tokens(e) or 0 for e in gold_events)
    gold_n = int(verified_stats.get("n_verified") or 0)
    baseline_per_verified = (gold_base / gold_n) if gold_n and gold_base else None
    actual_per_verified = verified_stats.get("tokens_per_verified_task")

    reduction = None
    if baseline_sum > 0:
        reduction = round(1.0 - (actual_sum / baseline_sum), 4)

    total_avoided_display = measured_avoided + estimated_avoided  # for UI split only — never single headline without tiers

    def _pct_map(counter: Counter[str], total: int) -> list[dict[str, Any]]:
        t = total if total > 0 else sum(counter.values()) or 1
        out = []
        for k, v in counter.most_common():
            out.append(
                {
                    "key": k,
                    "tokens": int(v),
                    "share": round(v / t, 4) if t else 0.0,
                }
            )
        return out

    mech_total = sum(by_mech_avoided.values()) or sum(by_mech_actual.values()) or 1
    # mechanism shares prefer avoided mass; include frontier residual actual
    mech_rows = []
    keys = set(by_mech_avoided) | set(by_mech_actual)
    for k in sorted(keys, key=lambda x: -(by_mech_avoided[x] + by_mech_actual[x])):
        av = by_mech_avoided[k]
        ac = by_mech_actual[k]
        mech_rows.append(
            {
                "mechanism": k,
                "tokens_avoided": int(av),
                "tokens_actual": int(ac),
                "share_of_avoided": round(av / mech_total, 4) if mech_total else 0.0,
            }
        )

    harness_rows = []
    for h in sorted(set(by_harness_actual) | set(by_harness_avoided), key=lambda x: -by_harness_avoided[x]):
        harness_rows.append(
            {
                "harness": h,
                "tokens_avoided": int(by_harness_avoided[h]),
                "tokens_actual": int(by_harness_actual[h]),
                "verified_tasks": int(by_harness_verified[h]),
            }
        )

    days = sorted(set(ts_base) | set(ts_actual) | set(ts_meas) | set(ts_est))
    timeseries = [
        {
            "day": d,
            "baseline_tokens": int(ts_base[d]),
            "actual_frontier_tokens": int(ts_actual[d]),
            "measured_tokens_avoided": int(ts_meas[d]),
            "estimated_tokens_avoided": int(ts_est[d]),
        }
        for d in days
    ]


    # --- Prepare/speculation funnel (non-LLM economics) ---
    # Prefer dedicated flow.prepare.v1 lifecycle rows; fall back to lifted
    # flow_prediction prepare blocks. Dedupe by prediction_id with terminal
    # outcome winning over create so receipts + events never double-count.
    prep_events = [
        e for e in rows if e.kind == "prepare" or (e.economics and e.economics.prepare_outcome)
    ]
    _OUTCOME_RANK = {
        "would_prepare": 0,
        "prepare_created": 1,
        "prepare_expired": 2,
        "prepare_invalidated": 2,
        "prepare_consumed": 3,
    }
    by_pred: dict[str, object] = {}
    unkeyed: list = []
    for ev in prep_events:
        eco = ev.economics
        if not eco or not eco.prepare_outcome:
            continue
        pid = str((ev.extra or {}).get("prediction_id") or "")
        legacy = str((ev.extra or {}).get("legacy_schema") or "")
        # Prefer dedicated prepare_events over flow_prediction lifts when both exist.
        weight = 2 if legacy.startswith("flow.prepare") else 1
        if not pid:
            unkeyed.append(ev)
            continue
        prev = by_pred.get(pid)
        if prev is None:
            by_pred[pid] = (weight, _OUTCOME_RANK.get(eco.prepare_outcome, 0), ev)
        else:
            pw, pr, _ = prev
            rank = _OUTCOME_RANK.get(eco.prepare_outcome, 0)
            if weight > pw or (weight == pw and rank >= pr):
                by_pred[pid] = (weight, rank, ev)
    chosen = [trip[2] for trip in by_pred.values()] + unkeyed

    created = consumed = expired = invalidated = would_prepare = 0
    latency_hidden_ms = 0.0
    counterfactual_blocking_ms = 0.0
    commit_setup_ms_sum = 0.0
    by_provider_prep: Counter[str] = Counter()
    by_operator_horizon: dict[tuple[str, int], dict[str, Any]] = {}
    frontier_replaced_sum = 0
    # Speculation cost: sum create costs once per prediction (from create event if present).
    create_cost_by_pred: dict[str, float] = {}
    create_bytes_by_pred: dict[str, int] = {}
    for ev in prep_events:
        eco = ev.economics
        if not eco or eco.prepare_outcome != "prepare_created":
            continue
        pid = str((ev.extra or {}).get("prediction_id") or ev.event_id or id(ev))
        if eco.prepare_cost_ms is not None:
            create_cost_by_pred[pid] = float(eco.prepare_cost_ms)
        if eco.prepare_bytes is not None:
            create_bytes_by_pred[pid] = int(eco.prepare_bytes)

    for ev in chosen:
        eco = ev.economics
        if not eco or not eco.prepare_outcome:
            continue
        oc = eco.prepare_outcome
        extra = ev.extra or {}
        horizon_ms = int(extra.get("horizon_ms") or 0)
        provider = str(eco.prepare_provider or extra.get("operator_family") or "unknown")
        oh_key = (provider, horizon_ms)
        bucket = by_operator_horizon.setdefault(
            oh_key,
            {
                "operator": provider,
                "horizon_ms": horizon_ms,
                "prepared": 0,
                "would_prepare": 0,
                "consumed": 0,
                "expired": 0,
                "invalidated": 0,
                "latency_hidden_ms": 0.0,
                "speculation_cost_ms": 0.0,
                "counterfactual_blocking_ms": 0.0,
                "net_ms": 0.0,
            },
        )
        if oc == "would_prepare":
            would_prepare += 1
            bucket["would_prepare"] += 1
        elif oc == "prepare_created":
            created += 1
            bucket["prepared"] += 1
            if eco.prepare_cost_ms:
                bucket["speculation_cost_ms"] += float(eco.prepare_cost_ms)
        elif oc == "prepare_consumed":
            consumed += 1
            created += 1
            bucket["prepared"] += 1
            bucket["consumed"] += 1
            if eco.latency_hidden_ms:
                latency_hidden_ms += float(eco.latency_hidden_ms)
                bucket["latency_hidden_ms"] += float(eco.latency_hidden_ms)
            cf = extra.get("counterfactual_blocking_ms")
            if cf is not None:
                counterfactual_blocking_ms += float(cf)
                bucket["counterfactual_blocking_ms"] += float(cf)
            cs = extra.get("commit_setup_ms")
            if cs is not None:
                commit_setup_ms_sum += float(cs)
            if eco.prepare_cost_ms:
                bucket["speculation_cost_ms"] += float(eco.prepare_cost_ms)
            if eco.frontier_tokens_replaced:
                frontier_replaced_sum += int(eco.frontier_tokens_replaced)
        elif oc == "prepare_expired":
            expired += 1
            created += 1
            bucket["prepared"] += 1
            bucket["expired"] += 1
            if eco.prepare_cost_ms:
                bucket["speculation_cost_ms"] += float(eco.prepare_cost_ms)
        elif oc == "prepare_invalidated":
            invalidated += 1
            created += 1
            bucket["prepared"] += 1
            bucket["invalidated"] += 1
            if eco.prepare_cost_ms:
                bucket["speculation_cost_ms"] += float(eco.prepare_cost_ms)
        if eco.prepare_provider:
            by_provider_prep[str(eco.prepare_provider)] += 1

    speculation_cost_ms = sum(create_cost_by_pred.values())
    prepare_bytes_sum = sum(create_bytes_by_pred.values())
    # If we only saw terminals without creates, still count chosen creates above.
    # Hit rate uses created as denominator after terminal backfill.

    hit_rate = (consumed / created) if created > 0 else None
    net_prepare_value_ms = round(latency_hidden_ms - speculation_cost_ms, 3)
    prepare_efficiency = (
        round(latency_hidden_ms / speculation_cost_ms, 2)
        if speculation_cost_ms > 0
        else None
    )
    for bucket in by_operator_horizon.values():
        bucket["net_ms"] = round(
            float(bucket["latency_hidden_ms"]) - float(bucket["speculation_cost_ms"]), 3
        )
        for k in (
            "latency_hidden_ms",
            "speculation_cost_ms",
            "counterfactual_blocking_ms",
        ):
            bucket[k] = round(float(bucket[k]), 3)
    pred_ids = set(by_pred.keys())
    prepare_funnel = {
        "predictions": len(pred_ids) if pred_ids else None,
        "prepared": created,
        "would_prepare": would_prepare,
        "consumed": consumed,
        "expired": expired,
        "invalidated": invalidated,
        "changed_behavior": None,
        "verified_useful": None,
        "prepare_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        "latency_hidden_ms": round(latency_hidden_ms, 3),
        "speculation_overhead_ms": round(speculation_cost_ms, 3),
        "net_prepare_value_ms": net_prepare_value_ms,
        "prepare_efficiency": prepare_efficiency,
        "counterfactual_blocking_ms": round(counterfactual_blocking_ms, 3),
        "commit_setup_ms": round(commit_setup_ms_sum, 3),
        "prepare_bytes_sum": int(prepare_bytes_sum),
        "frontier_tokens_replaced_on_consume": int(frontier_replaced_sum),
        "by_provider": [
            {"provider": k, "events": int(v)} for k, v in by_provider_prep.most_common()
        ],
        "by_operator_horizon": sorted(
            by_operator_horizon.values(), key=lambda r: (-r["consumed"], r["operator"], r["horizon_ms"])
        ),
        "rule": (
            "Do not credit prepare_created as savings. "
            "latency_hidden only on prepare_consumed. "
            "net_prepare_value_ms = latency_hidden - speculation_overhead (expired/invalidated stay in cost). "
            "Token avoidance only when frontier_tokens_replaced > 0 on consume."
        ),
    }

    reconciliation = _build_reconciliation(
        rows,
        baseline_sum=int(baseline_sum),
        actual_sum=int(actual_sum),
        measured_avoided=int(measured_avoided),
        estimated_avoided=int(estimated_avoided),
        unknown_baseline_tokens=int(unknown_baseline_tokens),
    )
    token_coverage = _token_coverage(
        measured_avoided=int(measured_avoided),
        estimated_avoided=int(estimated_avoided),
        unknown_tokens=int(unknown_baseline_tokens + reconciliation["unknown_attribution_tokens"]),
        actual_sum=int(actual_sum),
    )

    return {
        "schema": REPORT_SCHEMA,
        "range": range_spec,
        "period": {
            "start_ts": start,
            "end_ts": end,
            "start_iso": datetime.fromtimestamp(start, tz=timezone.utc).isoformat() if start > 0 else None,
            "end_iso": datetime.fromtimestamp(end, tz=timezone.utc).isoformat(),
        },
        "sources": sources or [],
        "n_events": n,
        "totals": {
            "baseline_tokens": int(baseline_sum),
            "actual_frontier_tokens": int(actual_sum),
            # Split is mandatory — never a single collapsed "saved" headline field.
            "measured_tokens_avoided": int(measured_avoided),
            "estimated_tokens_avoided": int(estimated_avoided),
            "unknown_or_no_baseline_tokens": int(unknown_baseline_tokens),
            "tokens_avoided_sum_for_display_only": int(total_avoided_display),
            "reduction_vs_baseline": reduction,
        },
        "savings": {
            "tiers": {
                "measured": {"events": n_measured, "tokens_avoided": int(measured_avoided)},
                "estimated": {"events": n_estimated, "tokens_avoided": int(estimated_avoided)},
                "unknown": {"events": n_unknown, "tokens_observed_without_baseline": int(unknown_baseline_tokens)},
            },
            "rule": "Never collapse measured and estimated into one savings number.",
        },
        "verified_outcomes": {
            "verified_tasks": gold_n,
            "tokens_per_verified_task": actual_per_verified,
            "baseline_tokens_per_verified_task": baseline_per_verified,
            "reduction_per_verified": (
                round(1.0 - (float(actual_per_verified) / float(baseline_per_verified)), 4)
                if actual_per_verified and baseline_per_verified
                else None
            ),
            "trace_stats": verified_stats,
        },
        "by_mechanism": mech_rows,
        "by_harness": harness_rows,
        "by_capability": _pct_map(by_cap_actual, actual_sum),
        "by_provider": _pct_map(by_provider_actual, actual_sum),
        "by_model": _pct_map(by_model_actual, actual_sum),
        "timeseries": timeseries,
        "data_quality": {
            "tier_event_counts": dict(by_tier),
            "events_with_baseline": sum(1 for e in rows if _baseline_tokens(e) is not None),
            "events_with_measured_frontier": sum(1 for e in rows if _measured_frontier(e) is not None),
            "events_with_estimate_only": n_estimated,
            "prepare_events": len(prep_events),
            "incremental_usage_events": sum(1 for e in rows if _is_incremental_usage(e)),
            "aggregate_usage_events": sum(1 for e in rows if _is_aggregate_usage(e)),
            "unknown_attribution_events": sum(
                1 for e in rows if e.usage is not None and _usage_attribution(e) == "unknown"
            ),
        },
        "prepare_funnel": prepare_funnel,
        "reconciliation": reconciliation,
        "token_coverage": token_coverage,
        "economics": {
            # Costs optional — only when events carry prices/cost_usd.
            "observed_cost_usd": _sum_cost(rows, baseline=False),
            "baseline_cost_usd": _sum_cost(rows, baseline=True),
            "note": "Costs only sum when events include cost_usd / baseline_cost_usd; never invent prices.",
        },
    }


def _sum_cost(rows: list[TokenomicsEvent], *, baseline: bool) -> float | None:
    total = 0.0
    any_c = False
    for ev in rows:
        if _is_aggregate_usage(ev):
            continue
        if not ev.economics:
            continue
        v = ev.economics.baseline_cost_usd if baseline else ev.economics.cost_usd
        if v is None:
            continue
        any_c = True
        total += float(v)
    return round(total, 6) if any_c else None


def format_savings_text(report: dict[str, Any]) -> str:
    """Human report — measured and estimated always on separate lines."""
    tot = report["totals"]
    sav = report["savings"]["tiers"]
    ver = report["verified_outcomes"]
    period = report["period"]
    lines = [
        f"Tokenomics · {report['range']}",
        "",
        "Frontier work",
        "────────────────────────────────────────",
        f"Baseline tokens              {_fmt_tok(tot['baseline_tokens'])}",
        f"Actual frontier tokens       {_fmt_tok(tot['actual_frontier_tokens'])}",
        f"Measured tokens avoided      {_fmt_tok(sav['measured']['tokens_avoided'])}",
        f"Estimated tokens avoided     {_fmt_tok(sav['estimated']['tokens_avoided'])}",
        f"Unknown / no baseline        {_fmt_tok(tot['unknown_or_no_baseline_tokens'])}",
        "",
        "Verified outcomes",
        "────────────────────────────────────────",
        f"Verified tasks               {ver['verified_tasks']}",
        f"Tokens / verified task       {_fmt_tok(ver['tokens_per_verified_task'])}",
        f"Baseline tokens / task       {_fmt_tok(ver['baseline_tokens_per_verified_task'])}",
        f"Reduction                    {_fmt_pct(ver.get('reduction_per_verified'))}",
        "",
        "Offload (by mechanism)",
        "────────────────────────────────────────",
    ]
    for row in report["by_mechanism"][:8]:
        lines.append(
            f"{row['mechanism']:<22} avoided {_fmt_tok(row['tokens_avoided']):>8}  "
            f"actual {_fmt_tok(row['tokens_actual']):>8}  "
            f"({row['share_of_avoided']*100:.1f}% avoided share)"
        )
    lines += [
        "",
        "By harness",
        "────────────────────────────────────────",
        f"{'harness':<16}{'avoided':>10}{'actual':>10}{'verified':>10}",
    ]
    for row in report["by_harness"][:10]:
        lines.append(
            f"{row['harness']:<16}{_fmt_tok(row['tokens_avoided']):>10}"
            f"{_fmt_tok(row['tokens_actual']):>10}{row['verified_tasks']:>10}"
        )
    pf = report.get("prepare_funnel") or {}
    if pf:
        lines += [
            "",
            "Prepare / speculation funnel",
            "────────────────────────────────────────",
            f"Predictions                  {pf.get('predictions') if pf.get('predictions') is not None else '—'}",
            f"Prepared                     {pf.get('prepared', 0)}",
            f"Consumed                     {pf.get('consumed', 0)}",
            f"Expired                      {pf.get('expired', 0)}",
            f"Invalidated                  {pf.get('invalidated', 0)}",
            f"Would prepare (withheld)     {pf.get('would_prepare', 0)}",
            f"Prepare hit rate             {_fmt_pct(pf.get('prepare_hit_rate'))}",
            f"Latency hidden               {_fmt_ms(pf.get('latency_hidden_ms'))}",
            f"Speculation overhead         {_fmt_ms(pf.get('speculation_overhead_ms'))}",
            f"Net prepare value            {_fmt_ms(pf.get('net_prepare_value_ms'))}",
            f"Prepare efficiency           {pf.get('prepare_efficiency') if pf.get('prepare_efficiency') is not None else '—'}",
            f"Counterfactual blocking      {_fmt_ms(pf.get('counterfactual_blocking_ms'))}",
            f"Frontier tokens replaced*    {_fmt_tok(pf.get('frontier_tokens_replaced_on_consume'))}",
            "  * only on consume that replaced a model call — create earns 0",
        ]
    rec = report.get("reconciliation") or {}
    if rec:
        lines += [
            "",
            "Reconciliation",
            "────────────────────────────────────────",
            f"Incremental tokens           {_fmt_tok(rec.get('incremental_tokens'))}",
            f"Aggregate reported           {_fmt_tok(rec.get('aggregate_reported_tokens'))}",
            f"Reconciliation delta         {_fmt_tok(rec.get('reconciliation_delta_tokens'))}",
            f"Gross delta (base−actual)    {_fmt_tok(rec.get('gross_delta_tokens'))}",
            f"Unattributed delta           {_fmt_tok(rec.get('unattributed_delta_tokens'))}",
            f"Status                       {rec.get('status', '—')}",
        ]
    cov = report.get("token_coverage") or {}
    if cov:
        lines += [
            "",
            "Token coverage (tier mass)",
            "────────────────────────────────────────",
        ]
        for key in ("measured", "estimated", "unknown_or_unattributed", "actual_frontier"):
            row = cov.get(key) or {}
            share = row.get("share")
            share_s = f"{float(share)*100:.1f}%" if share is not None else "—"
            lines.append(f"{key:<28} {_fmt_tok(row.get('tokens')):>8}  ({share_s})")
    red = tot.get("reduction_vs_baseline")
    lines += [
        "",
        f"Reduction vs baseline workload: {_fmt_pct(red)}",
        f"Events: {report['n_events']}  "
        f"(measured={sav['measured']['events']} estimated={sav['estimated']['events']} "
        f"unknown={sav['unknown']['events']})",
        "Rule: never collapse measured and estimated savings.",
    ]
    if report.get("economics", {}).get("observed_cost_usd") is not None:
        eco = report["economics"]
        lines += [
            "",
            "Economics (only where cost fields present)",
            "────────────────────────────────────────",
            f"Observed cost                ${_fmt_money(eco.get('observed_cost_usd'))}",
            f"Baseline cost                ${_fmt_money(eco.get('baseline_cost_usd'))}",
        ]
    lines.append(f"Period {period.get('start_iso')} → {period.get('end_iso')}")
    return "\n".join(lines) + "\n"


def _fmt_tok(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(int(n) if n == int(n) else round(n, 1))


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_ms(v: Any) -> str:
    if v is None:
        return "—"
    try:
        ms = float(v)
    except (TypeError, ValueError):
        return "—"
    if ms >= 60_000:
        return f"{ms/60000:.1f} min"
    if ms >= 1000:
        return f"{ms/1000:.2f} s"
    return f"{ms:.1f} ms"


def _fmt_money(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v):.2f}"


def savings_report_from_sources(
    *,
    range_spec: str = "7d",
    paths: list[Path] | None = None,
    root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    src = paths if paths is not None else default_sources(root=root)
    events = load_events_from_paths(src)
    return build_savings_report(
        events,
        range_spec=range_spec,
        now=now,
        sources=[str(p) for p in src if Path(p).is_file()],
    )
