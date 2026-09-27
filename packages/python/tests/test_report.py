from __future__ import annotations

import time

from tokenomics.adapters import from_z0int_receipt
from tokenomics.models import Economics, MeasurementSourceRef, Outcome, TokenUsage, TokenomicsEvent
from tokenomics.report import (
    REPORT_SCHEMA,
    build_savings_report,
    classify_savings,
    format_savings_text,
    parse_range,
)


def _tid(n: int) -> str:
    return f"{n:032x}"


def test_parse_range_7d():
    now = 1_700_000_000.0
    start, end = parse_range("7d", now=now)
    assert end == now
    assert abs((end - start) - 7 * 86400) < 1


def test_classify_measured_vs_estimated_vs_unknown():
    now = time.time()
    measured = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(1),
            "capability_id": "coding.next_action",
            "route": "model",
            "baseline_input_tokens": 2000,
            "baseline_output_tokens": 500,
            "measured_frontier_tokens": 900,
            "estimated_frontier_tokens_avoided": 9999,  # must not override measured
            "ts": now,
        }
    )
    tier, base, actual, avoided = classify_savings(measured)
    assert tier == "measured"
    assert base == 2500
    assert actual == 900
    assert avoided == 1600

    estimated = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(2),
            "capability_id": "routine.preflight",
            "route": "local",
            "baseline_input_tokens": 4000,
            "baseline_output_tokens": 800,
            "estimated_frontier_tokens_avoided": 4800,
            "ts": now,
        }
    )
    tier, base, actual, avoided = classify_savings(estimated)
    assert tier == "estimated"
    assert avoided == 4800
    assert actual == 0

    unknown = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(3),
            "capability_id": "coding.open",
            "route": "model",
            "input_tokens": 1200,
            "output_tokens": 300,
            "ts": now,
        }
    )
    # provider source only when measured; here usage source unknown → actual from usage
    tier, base, actual, avoided = classify_savings(unknown)
    assert tier == "unknown"
    assert avoided == 0


def test_partial_actual_cannot_mint_measured_savings():
    now = time.time()
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(30),
            "capability_id": "coding.next_action",
            "route": "model",
            "baseline_input_tokens": 2000,
            "baseline_output_tokens": 500,
            "measured_frontier_tokens": 900,
            "ts": now,
        }
    )
    ev.measurement_source = MeasurementSourceRef(measurement_state="partial")
    tier, base, actual, avoided = classify_savings(ev)
    assert tier == "unknown"
    assert base == 2500
    assert actual == 900
    assert avoided == 0


def test_complete_actual_keeps_measured_savings_authoritative():
    now = time.time()
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(31),
            "capability_id": "coding.next_action",
            "route": "model",
            "baseline_input_tokens": 2000,
            "baseline_output_tokens": 500,
            "measured_frontier_tokens": 900,
            "outcome": {"verified_success": True, "verification_source": "tests"},
            "ts": now,
        }
    )
    ev.measurement_source = MeasurementSourceRef(measurement_state="complete")
    report = build_savings_report([ev], range_spec="all", now=now + 1)
    assert report["totals"]["authoritative"] is True
    assert report["totals"]["measurement_state"] == "complete"
    assert report["totals"]["measured_tokens_avoided_authoritative"] == 1600
    assert report["totals"]["measured_tokens_avoided_provisional"] == 0
    assert report["verified_outcomes"]["authoritative"] is True
    assert report["verified_outcomes"]["authoritative_tokens_per_verified_task"] is not None


def test_legacy_measured_savings_stay_numeric_but_provisional():
    now = time.time()
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(32),
            "capability_id": "coding.next_action",
            "route": "model",
            "baseline_input_tokens": 2000,
            "baseline_output_tokens": 500,
            "measured_frontier_tokens": 900,
            "ts": now,
        }
    )
    report = build_savings_report([ev], range_spec="all", now=now + 1)
    assert report["totals"]["measured_tokens_avoided"] == 1600
    assert report["totals"]["measured_tokens_avoided_authoritative"] == 0
    assert report["totals"]["measured_tokens_avoided_provisional"] == 1600
    assert report["totals"]["measurement_state"] == "unknown"
    assert report["totals"]["authoritative"] is False


def test_report_never_collapses_tiers():
    now = time.time()
    rows = [
        from_z0int_receipt(
            {
                "schema": "z0int.decision_receipt.v1",
                "trace_id": _tid(10),
                "capability_id": "a",
                "route": "model",
                "baseline_input_tokens": 1000,
                "baseline_output_tokens": 0,
                "measured_frontier_tokens": 400,
                "outcome": {"verified_success": True, "verification_source": "tests"},
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
        from_z0int_receipt(
            {
                "schema": "z0int.decision_receipt.v1",
                "trace_id": _tid(12),
                "capability_id": "c",
                "route": "model",
                "input_tokens": 100,
                "output_tokens": 20,
                "ts": now,
            }
        ),
    ]
    report = build_savings_report(rows, range_spec="all", now=now + 1)
    assert report["schema"] == REPORT_SCHEMA
    assert report["totals"]["measured_tokens_avoided"] == 600
    assert report["totals"]["estimated_tokens_avoided"] == 2500
    # no collapsed single savings key that hides the split
    assert "tokens_saved" not in report["totals"]
    assert report["savings"]["tiers"]["measured"]["tokens_avoided"] == 600
    assert report["savings"]["tiers"]["estimated"]["tokens_avoided"] == 2500
    text = format_savings_text(report)
    assert "Measured tokens avoided" in text
    assert "Estimated tokens avoided" in text
    assert "600" in text or "0.6k" in text
    assert "2.5k" in text or "2500" in text


def test_adapter_does_not_put_estimate_into_measured_field():
    ev = from_z0int_receipt(
        {
            "schema": "z0int.decision_receipt.v1",
            "trace_id": _tid(20),
            "estimated_frontier_tokens_avoided": 1234,
            "ts": time.time(),
        }
    )
    assert ev.economics is not None
    assert ev.economics.estimated_tokens_avoided == 1234
    assert ev.economics.measured_tokens_avoided is None



def test_incomplete_prepare_measurement_mints_no_baseline_or_savings():
    ev = TokenomicsEvent(
        kind="prepare",
        name="prepare.consume",
        economics=Economics(
            prepare_outcome="prepare_consumed",
            measured_tokens_avoided=500,
        ),
        measurement_source=MeasurementSourceRef(measurement_state="failed"),
    )
    assert classify_savings(ev) == ("unknown", 0, 0, 0)
