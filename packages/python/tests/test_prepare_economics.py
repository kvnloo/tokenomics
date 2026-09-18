from __future__ import annotations

import time

from tokenomics.adapters import from_flow_prepare, from_flow_prediction
from tokenomics.report import build_savings_report, format_savings_text


def test_prepare_created_earns_zero_token_credit():
    ev = from_flow_prepare(
        {
            "schema": "flow.prepare.v1",
            "prepare_outcome": "prepare_created",
            "prepare_cost_ms": 12.5,
            "prepare_bytes": 4096,
            "prepare_provider": "inspect_result",
            "prediction_id": "a" * 32,
            "ts": time.time(),
        }
    )
    assert ev.kind == "prepare"
    assert ev.economics.prepare_outcome == "prepare_created"
    assert ev.economics.measured_tokens_avoided is None
    assert ev.economics.latency_hidden_ms is None
    assert ev.economics.prepare_cost_ms == 12.5


def test_prepare_consumed_hides_latency_not_tokens_by_default():
    ev = from_flow_prepare(
        {
            "prepare_outcome": "prepare_consumed",
            "prepare_cost_ms": 8.0,
            "prepare_provider": "inspect_result",
            "time_to_commit_ms": 4000,
            "prediction_id": "b" * 32,
            "ts": time.time(),
        }
    )
    assert ev.economics.latency_hidden_ms == 8.0
    assert ev.economics.measured_tokens_avoided is None


def test_prepare_consumed_with_frontier_replace_is_measured():
    ev = from_flow_prepare(
        {
            "prepare_outcome": "prepare_consumed",
            "prepare_cost_ms": 5.0,
            "frontier_tokens_replaced": 1500,
            "prediction_id": "c" * 32,
            "ts": time.time(),
        }
    )
    assert ev.economics.measured_tokens_avoided == 1500
    assert ev.economics.frontier_tokens_replaced == 1500


def test_funnel_hit_rate_and_no_self_congratulation():
    now = time.time()
    rows = [
        from_flow_prepare(
            {
                "prepare_outcome": "prepare_created",
                "prepare_cost_ms": 10.0,
                "prepare_bytes": 100,
                "prepare_provider": "inspect_result",
                "prediction_id": f"{i:032x}",
                "ts": now,
            }
        )
        for i in range(4)
    ]
    rows.append(
        from_flow_prepare(
            {
                "prepare_outcome": "prepare_consumed",
                "prepare_cost_ms": 10.0,
                "latency_hidden_ms": 10.0,
                "prediction_id": f"{0:032x}",
                "ts": now,
            }
        )
    )
    rows.append(
        from_flow_prepare(
            {
                "prepare_outcome": "prepare_expired",
                "prepare_cost_ms": 10.0,
                "prediction_id": f"{1:032x}",
                "ts": now,
            }
        )
    )
    rows.append(
        from_flow_prepare(
            {
                "prepare_outcome": "prepare_invalidated",
                "prepare_cost_ms": 10.0,
                "prediction_id": f"{2:032x}",
                "ts": now,
            }
        )
    )
    report = build_savings_report(rows, range_spec="all", now=now + 1)
    pf = report["prepare_funnel"]
    assert pf["prepared"] == 4
    assert pf["consumed"] == 1
    assert pf["expired"] == 1
    assert pf["invalidated"] == 1
    assert pf["prepare_hit_rate"] == 0.25
    assert pf["latency_hidden_ms"] == 10.0
    assert pf["speculation_overhead_ms"] == 40.0
    assert pf["frontier_tokens_replaced_on_consume"] == 0
    assert report["totals"]["measured_tokens_avoided"] == 0
    assert report["totals"]["estimated_tokens_avoided"] == 0
    text = format_savings_text(report)
    assert "Prepare hit rate" in text
    assert "Speculation overhead" in text


def test_flow_prediction_lift_commit_marks_consumed():
    now = time.time()
    ev = from_flow_prediction(
        {
            "schema": "flow_prediction.v1",
            "prediction_id": "d" * 32,
            "timestamp": now,
            "context_id": "ctx",
            "prepare": {
                "eligible": True,
                "cost_ms": 3.2,
                "bytes": 512,
                "provider": "inspect_result",
                "operator_family": "inspect_result",
                "started_at": now - 4,
                "ready_at": now - 3.9,
            },
            "commit": {"committed": True, "committed_at": now, "source": "flow"},
        }
    )
    assert ev is not None
    assert ev.economics.prepare_outcome == "prepare_consumed"
    assert ev.economics.time_to_commit_ms is not None
    assert ev.economics.time_to_commit_ms >= 3900
