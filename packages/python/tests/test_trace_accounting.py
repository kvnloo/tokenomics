from __future__ import annotations

import time

import pytest

from tokenomics.adapters import (
    from_flow_prepare,
    from_kerdoios_observation,
    from_omp_provider_usage,
    from_omp_session_aggregate,
    from_z0int_receipt,
)
from tokenomics.models import Economics, Outcome, TokenUsage, TokenomicsEvent
from tokenomics.trace_accounting import assert_no_double_count, rollup_trace, rollup_traces


def _tid(n: int) -> str:
    return f"{n:032x}"


def _omp(trace: str, inp: int, out: int, *, role: str = "root", reuse_kind: str | None = None):
    raw = {
        "trace_id": trace,
        "session_id": "sess",
        "role": role,
        "provider": "anthropic",
        "model": "claude",
        "usage": {
            "input_tokens": inp,
            "output_tokens": out,
            "cached_input_tokens": 0,
        },
    }
    if reuse_kind:
        raw["reuse_kind"] = reuse_kind
    ev = from_omp_provider_usage(raw)
    if reuse_kind:
        extra = dict(ev.extra or {})
        extra["reuse_kind"] = reuse_kind
        ev.extra = extra
    return ev


def test_incremental_children_and_aggregate_parent_do_not_double_count():
    trace = _tid(1)
    rows = [
        _omp(trace, 100, 10),
        _omp(trace, 20, 5, role="rlm_worker"),
        from_omp_session_aggregate(
            {
                "trace_id": trace,
                "usage": {"input_tokens": 120, "output_tokens": 15},
            }
        ),
    ]
    r = rollup_trace(rows)
    assert r.actual_frontier_tokens == 135
    assert r.aggregate_reported == 135
    assert r.reconciliation_delta == 0
    assert_no_double_count(rows)


def test_rlm_aggregate_summary_and_workers_do_not_double_count():
    trace = _tid(2)
    rows = [
        _omp(trace, 50, 5, role="rlm_worker"),
        _omp(trace, 30, 3, role="rlm_worker"),
        from_omp_session_aggregate(
            {
                "trace_id": trace,
                "role": "root",
                "context_policy": "rlm",
                "usage": {"input_tokens": 80, "output_tokens": 8},
            }
        ),
    ]
    r = rollup_trace(rows)
    assert r.actual_frontier_tokens == 88
    assert r.reconciliation_delta == 0
    assert "rlm" in r.attribution


def test_local_jev_without_baseline_earns_zero_saved_tokens():
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(3),
            "capability_id": "coding.delegate",
            "route": "local",
            "provider": "local_mb",
            "ts": time.time(),
        }
    )
    r = rollup_trace([ev])
    assert r.actual_frontier_tokens == 0
    assert r.tokens_avoided == 0
    assert r.savings_tier == "unknown"
    assert r.baseline == "missing"


def test_jev_with_estimated_baseline_stays_estimated():
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(4),
            "capability_id": "routine.preflight",
            "route": "local",
            "baseline_input_tokens": 4000,
            "baseline_output_tokens": 800,
            "estimated_frontier_tokens_avoided": 4800,
            "ts": time.time(),
        }
    )
    r = rollup_trace([ev])
    assert r.savings_tier == "estimated"
    assert r.baseline == "estimated"
    assert r.tokens_avoided == 4800
    assert r.measurement_level == "M1"


def test_paired_baseline_upgrades_to_measured():
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(5),
            "capability_id": "coding.next_action",
            "route": "model",
            "baseline_input_tokens": 2000,
            "baseline_output_tokens": 500,
            "measured_frontier_tokens": 900,
            "ts": time.time(),
        }
    )
    r = rollup_trace([ev])
    assert r.savings_tier == "measured"
    assert r.baseline == "paired_measured"
    assert r.measurement_level == "M3"
    assert r.tokens_avoided == 1600


def test_kerdoios_placement_cannot_mint_savings():
    ev = from_kerdoios_observation(
        {
            "trace_id": _tid(6),
            "capability_id": "coding.delegate",
            "provider": "cerebras",
            "model": "llama",
            "input_tokens": 500,
            "output_tokens": 50,
            "completed": True,
            "allocation_id": "alloc-1",
        }
    )
    ev.economics = Economics(estimated_tokens_avoided=9000, cost_usd=0.01)
    r = rollup_trace([ev])
    assert r.tokens_avoided == 0
    assert r.savings_tier == "unknown"
    assert (ev.extra or {}).get("placement_only") is True


def test_flow_prepare_create_cannot_mint_token_savings():
    prep = from_flow_prepare(
        {
            "prepare_outcome": "prepare_created",
            "prepare_cost_ms": 120,
            "frontier_tokens_replaced": 5000,
            "trace_id": _tid(7),
            "ts": time.time(),
        }
    )
    assert rollup_traces([prep]) == []


def test_cached_offline_replay_never_creates_second_provider_charge():
    trace = _tid(8)
    replay = _omp(trace, 999, 999, reuse_kind="offline_replay")
    live = _omp(trace, 40, 4)
    r = rollup_trace([replay, live])
    assert r.actual_frontier_tokens == 44
