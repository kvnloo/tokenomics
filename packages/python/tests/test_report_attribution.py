"""Regression: tokenomics.report.v1 must not double-count aggregate OMP session rows."""

from __future__ import annotations

import json
import time

from tokenomics.adapters import from_omp_provider_usage, from_omp_session_aggregate, from_z0int_receipt
from tokenomics.report import build_savings_report, default_sources, load_events_from_paths


def _tid(n: int) -> str:
    return f"{n:032x}"


def test_report_does_not_double_count_session_aggregate():
    now = time.time()
    trace = _tid(1)
    rows = [
        from_omp_provider_usage(
            {
                "trace_id": trace,
                "role": "root",
                "usage": {"input_tokens": 100, "output_tokens": 10},
                "ts": now,
            }
        ),
        from_omp_provider_usage(
            {
                "trace_id": trace,
                "role": "rlm_worker",
                "usage": {"input_tokens": 20, "output_tokens": 5},
                "ts": now,
            }
        ),
        from_omp_session_aggregate(
            {
                "trace_id": trace,
                "name": "omp.session.aggregate",
                "usage": {"input_tokens": 120, "output_tokens": 15},
                "ts": now,
            }
        ),
    ]
    report = build_savings_report(rows, range_spec="all", now=now + 1)
    assert report["totals"]["actual_frontier_tokens"] == 135
    rec = report["reconciliation"]
    assert rec["incremental_tokens"] == 135
    assert rec["aggregate_reported_tokens"] == 135
    assert rec["reconciliation_delta_tokens"] == 0
    assert rec["status"] == "reconciled"
    assert rec["role_breakdown"]["root_tokens"] == 110
    assert rec["role_breakdown"]["rlm_worker_tokens"] == 25


def test_classify_savings_skips_aggregate_rows():
    now = time.time()
    trace = _tid(2)
    agg = from_omp_session_aggregate(
        {
            "trace_id": trace,
            "usage": {"input_tokens": 500, "output_tokens": 50},
            "ts": now,
        }
    )
    report = build_savings_report([agg], range_spec="all", now=now + 1)
    assert report["totals"]["actual_frontier_tokens"] == 0
    assert report["data_quality"]["aggregate_usage_events"] == 1


def test_reconciliation_block_on_mixed_savings_and_usage():
    now = time.time()
    trace = _tid(3)
    rows = [
        from_z0int_receipt(
            {
                "schema": "z0int.decision_receipt.v1",
                "trace_id": trace,
                "capability_id": "coding.next_action",
                "route": "model",
                "baseline_input_tokens": 2000,
                "baseline_output_tokens": 500,
                "measured_frontier_tokens": 900,
                "ts": now,
            }
        ),
        from_omp_provider_usage(
            {
                "trace_id": trace,
                "role": "root",
                "usage": {"input_tokens": 800, "output_tokens": 100},
                "ts": now,
            }
        ),
    ]
    report = build_savings_report(rows, range_spec="all", now=now + 1)
    rec = report["reconciliation"]
    assert rec["measured_avoided_tokens"] == 1600
    assert rec["gross_delta_tokens"] == rec["baseline_tokens"] - rec["actual_tokens"]
    assert report["token_coverage"]["measured"]["tokens"] == 1600


def test_default_sources_includes_omp_glob(tmp_path, monkeypatch):
    omp_tokenomics = tmp_path / "tokenomics"
    omp_tokenomics.mkdir(parents=True)
    (omp_tokenomics / "events-2026-09-18.jsonl").write_text("")
    (omp_tokenomics / "events-2026-09-17.jsonl").write_text("")
    monkeypatch.setenv("OMP_HOME", str(tmp_path))
    sources = default_sources(root=tmp_path / "z0int")
    names = [p.name for p in sources]
    assert "events-2026-09-17.jsonl" in names
    assert "events-2026-09-18.jsonl" in names


def test_load_omp_jsonl_fixture(tmp_path):
    trace = _tid(4)
    now = time.time()
    lines = [
        {
            "schema": "tokenomics.event.v0",
            "kind": "llm",
            "name": "omp.root",
            "trace_id": trace,
            "harness": "omp",
            "role": "root",
            "usage": {
                "input_tokens": 50,
                "output_tokens": 5,
                "attribution": "incremental",
                "source": "provider",
            },
            "ts": now,
        },
        {
            "schema": "tokenomics.event.v0",
            "kind": "llm",
            "name": "omp.session.aggregate",
            "trace_id": trace,
            "harness": "omp",
            "role": "other",
            "usage": {
                "input_tokens": 50,
                "output_tokens": 5,
                "attribution": "aggregate",
                "source": "provider",
            },
            "ts": now,
        },
    ]
    p = tmp_path / "events-2026-09-18.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    events = load_events_from_paths([p])
    assert len(events) == 2
    report = build_savings_report(events, range_spec="all", now=now + 1, sources=[str(p)])
    assert report["totals"]["actual_frontier_tokens"] == 55
    assert str(p) in report["sources"]
