import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tokenomics import (
    SCHEMA,
    LatencySummary,
    OrchestrationObservation,
    observation_to_event,
    percentile,
    summarize_latency,
    summarize_observations,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "spec/schemas"

TRACE = "0123456789abcdef0123456789abcdef"


def _event_validator() -> Draft202012Validator:
    raw_schemas = {}
    for name in ("event.schema.json", "experiment.schema.json", "outcome.schema.json"):
        raw = json.loads((SCHEMAS / name).read_text())
        raw_schemas[name] = raw
    registry = Registry().with_resources(
        [(raw["$id"], Resource.from_contents(raw)) for raw in raw_schemas.values()]
    )
    return Draft202012Validator(raw_schemas["event.schema.json"], registry=registry)


# --- percentile -------------------------------------------------------------


def test_percentile_empty_is_none():
    assert percentile([], 50) is None
    assert percentile([], 99) is None


def test_percentile_single_value_is_that_value():
    assert percentile([7.0], 50) == 7.0
    assert percentile([7.0], 0) == 7.0
    assert percentile([7.0], 100) == 7.0


def test_percentile_hand_computed_interpolation():
    # rank = (4 - 1) * 0.95 = 2.85 -> 30 + (40 - 30) * 0.85 = 38.5
    assert percentile([10.0, 20.0, 30.0, 40.0], 95) == pytest.approx(38.5)
    # rank = 3 * 0.5 = 1.5 -> 2 + (3 - 2) * 0.5 = 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)
    assert percentile([1.0, 2.0, 3.0, 4.0], 0) == pytest.approx(1.0)
    assert percentile([1.0, 2.0, 3.0, 4.0], 100) == pytest.approx(4.0)


def test_percentile_is_not_a_mean_and_sorts_input():
    values = [100.0, 1.0, 1.0, 1.0]  # deliberately skewed
    assert percentile(values, 50) == pytest.approx(1.0)
    assert percentile(values, 50) != pytest.approx(sum(values) / len(values))
    # rank = 3 * 0.95 = 2.85 -> 1 + (100 - 1) * 0.85 = 85.15
    assert percentile(values, 95) == pytest.approx(85.15)
    assert percentile([1.0, 2.0, 3.0], 100) == pytest.approx(3.0)


def test_percentile_rejects_out_of_range_pct():
    with pytest.raises(ValueError):
        percentile([1.0, 2.0], 101)
    with pytest.raises(ValueError):
        percentile([1.0, 2.0], -1)


# --- summarize_latency ------------------------------------------------------


def test_summarize_latency_produces_ordered_percentiles():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    summary = summarize_latency(values)
    assert summary.count == 5
    assert summary.p50 == pytest.approx(3.0)
    assert summary.p50 <= summary.p95 <= summary.p99
    assert summary.p95 == pytest.approx(4.8)
    assert summary.p99 == pytest.approx(4.96)
    assert summary.mean == pytest.approx(3.0)
    assert summary.maximum == pytest.approx(5.0)
    assert "mean" in summary.to_dict() and "p95" in summary.to_dict()


def test_summarize_latency_empty_and_none_handling():
    empty = summarize_latency([])
    assert empty.count == 0
    assert empty.p50 is None and empty.p95 is None and empty.p99 is None
    assert empty.mean is None and empty.maximum is None
    filtered = summarize_latency([1.0, None, 3.0])
    assert filtered.count == 2
    assert filtered.p50 == pytest.approx(2.0)


def test_latency_summary_round_trip():
    summary = summarize_latency([10.0, 20.0, 30.0])
    restored = LatencySummary.from_dict(summary.to_dict())
    assert restored == summary
    assert LatencySummary.from_dict(None).count == 0


# --- OrchestrationObservation round-trip ------------------------------------


def test_observation_to_dict_drops_nones_and_keeps_schema():
    obs = OrchestrationObservation(
        trace_id=TRACE,
        decision_backend="jev",
        selected_action="search",
        invalid_call=False,
    )
    data = obs.to_dict()
    assert data["schema"] == SCHEMA
    assert data["trace_id"] == TRACE
    assert data["invalid_call"] is False  # False is not None, must survive
    assert "revision" not in data
    assert "executed_action" not in data
    assert "extra" in data


def test_observation_round_trip_preserves_fields():
    obs = OrchestrationObservation(
        trace_id=TRACE,
        decision_backend="nemotron",
        model_id="nano-3",
        revision="r1",
        candidate_action_count=3,
        selected_action="search",
        executed_action="read_file",
        invalid_call=False,
        retry_count=1,
        verified_success=True,
        decision_latency_ms=12.5,
        end_to_end_latency_ms=99.0,
        prompt_tokens=10,
        completion_tokens=4,
        extra={"note": "x"},
    )
    restored = OrchestrationObservation.from_dict(obs.to_dict())
    assert restored == obs
    assert restored.to_dict() == obs.to_dict()


def test_observation_from_dict_moves_unknown_keys_to_extra_and_checks_schema():
    obs = OrchestrationObservation.from_dict(
        {"trace_id": TRACE, "schema": SCHEMA, "future_field": 1}
    )
    assert obs.extra["future_field"] == 1
    with pytest.raises(ValueError):
        OrchestrationObservation.from_dict({"trace_id": TRACE, "schema": "nope"})


# --- observation_to_event ---------------------------------------------------


def _sample_observation(**overrides) -> OrchestrationObservation:
    base = dict(
        trace_id=TRACE,
        decision_backend="jev",
        model_id="qwen3",
        revision="rev-7",
        candidate_action_count=4,
        selected_action="search",
        executed_action="read_file",
        invalid_call=False,
        irrelevant_call=False,
        dependency_violation=False,
        parallelizable_but_serialized=True,
        retry_count=2,
        recovery_success=True,
        escalated=False,
        abstained=False,
        execution_completed=True,
        verified_success=None,
        decision_latency_ms=11.0,
        ttft_ms=30.0,
        tool_latency_ms=5.0,
        end_to_end_latency_ms=120.0,
        gpu_ms=8.0,
        vram_peak_mib=4096.0,
        prompt_tokens=100,
        completion_tokens=20,
        cache_tokens=10,
        local_cost_usd=0.001,
        provider_cost_usd=0.002,
    )
    base.update(overrides)
    return OrchestrationObservation(**base)


def test_observation_to_event_validates_against_event_schema():
    event = observation_to_event(_sample_observation(), harness="test-harness", ts=123.0)
    payload = event.to_dict()
    _event_validator().validate(payload)
    assert payload["kind"] == "decision"
    assert payload["schema"] == "tokenomics.event.v0"
    assert payload["harness"] == "test-harness"
    assert payload["ts"] == 123.0
    assert payload["model"]["name"] == "qwen3"
    assert payload["model"]["revision"] == "rev-7"
    assert payload["latency"]["ttft_ms"] == 30.0
    assert payload["latency"]["duration_ms"] == 120.0
    assert payload["usage"]["input_tokens"] == 100
    assert payload["usage"]["cached_input_tokens"] == 10
    assert payload["outcome"]["execution_completed"] is True
    assert payload["outcome"]["retries"] == 2


def test_selected_and_executed_actions_stay_distinct():
    obs = _sample_observation(selected_action="search", executed_action="read_file")
    event = observation_to_event(obs)
    attrs = event.to_dict()["attributes"]
    assert attrs["orchestration.selected_action"] == "search"
    assert attrs["orchestration.executed_action"] == "read_file"
    assert attrs["orchestration.selected_action"] != attrs["orchestration.executed_action"]


def test_verified_success_is_never_inferred_or_minted():
    # execution completed but nothing independently verified it: execution tier, no gold.
    event = observation_to_event(_sample_observation(execution_completed=True, verified_success=None))
    payload = event.to_dict()
    assert payload["outcome"]["execution_completed"] is True
    assert "verified_success" not in payload["outcome"]
    assert payload["outcome"]["tier"] == "execution"
    _event_validator().validate(payload)

    # An explicit gold signal is carried through verbatim.
    verified_event = observation_to_event(
        _sample_observation(execution_completed=True, verified_success=True)
    )
    assert verified_event.outcome is not None
    assert verified_event.outcome.verified_success is True
    assert verified_event.outcome.tier() == "gold"

    # An explicit negative signal is also carried verbatim.
    failed_event = observation_to_event(
        _sample_observation(execution_completed=True, verified_success=False)
    )
    assert failed_event.outcome is not None
    assert failed_event.outcome.verified_success is False


def test_observation_to_event_handles_sparse_observation():
    event = observation_to_event(OrchestrationObservation(trace_id=TRACE))
    payload = event.to_dict()
    _event_validator().validate(payload)
    assert "usage" not in payload
    assert "latency" not in payload
    assert "outcome" not in payload


# --- summarize_observations -------------------------------------------------


def test_summarize_observations_reports_percentiles_and_rates():
    rows = [
        _sample_observation(
            selected_action="search",
            executed_action="search",
            verified_success=True,
            decision_latency_ms=10.0,
        ),
        _sample_observation(
            selected_action="search",
            executed_action="read_file",
            verified_success=False,
            decision_latency_ms=20.0,
        ),
        _sample_observation(
            selected_action="read_file",
            executed_action=None,
            verified_success=None,
            decision_latency_ms=30.0,
        ),
    ]
    report = summarize_observations(rows)
    assert report["schema"] == SCHEMA
    assert report["count"] == 3

    decision = report["decision_latency"]
    assert set(("p50", "p95", "p99", "mean", "count", "maximum")).issubset(decision)
    assert decision["count"] == 3
    assert decision["p50"] <= decision["p95"] <= decision["p99"]

    # verified_success_rate covers only the two rows that actually carry a value.
    assert report["verified_success_count"] == 2
    assert report["verified_success_rate"] == pytest.approx(0.5)

    # selected_equals_executed covers only rows where both actions are present.
    assert report["selected_equals_executed_count"] == 2
    assert report["selected_equals_executed"] == pytest.approx(0.5)

    assert report["counters"]["parallelizable_but_serialized"] == 3  # all True
    assert report["counters"]["retry_count"] == 6  # 2 + 2 + 2
    assert report["counter_observed"]["retry_count"] == 3


def test_verified_success_none_rows_never_contribute_to_gold_rate():
    rows = [
        _sample_observation(execution_completed=True, verified_success=None),
        _sample_observation(execution_completed=False, verified_success=None),
    ]
    report = summarize_observations(rows)
    assert report["verified_success_count"] == 0
    assert report["verified_success_rate"] is None


def test_summarize_observations_empty_is_safe():
    report = summarize_observations([])
    assert report["count"] == 0
    assert report["verified_success_rate"] is None
    assert report["selected_equals_executed"] is None
    assert report["decision_latency"]["p50"] is None
    assert report["decision_latency"]["mean"] is None
