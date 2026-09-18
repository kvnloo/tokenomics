from __future__ import annotations

import time

from tokenomics.adapters import from_z0int_receipt
from tokenomics.coverage import build_coverage_report
from tokenomics.models import Outcome


def _tid(n: int) -> str:
    return f"{n:032x}"


def test_coverage_classification_independent_from_verified_outcome():
    now = time.time()
    verified_unmetered = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(1),
            "capability_id": "coding.open",
            "route": "local",
            "outcome": {"verified_success": True, "verification_source": "tests"},
            "ts": now,
        }
    )
    unverified_metered = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(2),
            "capability_id": "coding.run",
            "route": "model",
            "input_tokens": 500,
            "output_tokens": 100,
            "ts": now,
        }
    )
    report = build_coverage_report([verified_unmetered, unverified_metered], range_spec="all", now=now + 1)
    by_id = {row["trace_id"]: row for row in report["traces"]}
    assert by_id[_tid(1)]["measurement_level"] in {"M0", "M1", "M2"}
    assert by_id[_tid(1)]["outcome"] == "verified"
    assert by_id[_tid(2)]["outcome"] == "unknown"
    assert by_id[_tid(2)]["actual_usage"] in {"incremental", "unmetered"}


def test_coverage_does_not_alter_savings_totals():
    now = time.time()
    rows = [
        from_z0int_receipt(
            {
                "schema": "z0int.decision_receipt.v1",
                "trace_id": _tid(10),
                "capability_id": "a",
                "route": "model",
                "baseline_input_tokens": 1000,
                "measured_frontier_tokens": 400,
                "ts": now,
            }
        ),
        from_z0int_receipt(
            {
                "schema": "z0int.decision_receipt.v1",
                "trace_id": _tid(11),
                "capability_id": "b",
                "route": "local",
                "estimated_frontier_tokens_avoided": 2500,
                "ts": now,
            }
        ),
    ]
    report = build_coverage_report(rows, range_spec="all", now=now + 1)
    assert report["frontier_lane"]["measured_avoided"] == 600
    assert report["frontier_lane"]["estimated_avoided"] == 2500
    assert report["savings_report_schema"] == "tokenomics.report.v1"
