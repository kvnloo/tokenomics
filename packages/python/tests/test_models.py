from tokenomics import MeasurementSourceRef, MeasurementState, Outcome, TokenUsage, TokenomicsEvent


def test_gold_requires_verification_signal():
    assert Outcome(execution_completed=True, success=True).tier() == "execution"
    assert Outcome(execution_completed=True, verified_success=True, verification_source="tests").tier() == "gold"


def test_ambient_close_is_not_gold_without_verification_source():
    out = Outcome(execution_completed=True, test_pass=True, source="omp_turn_end")
    assert out.tier() == "execution"
    assert "ambient_close_sanitized" in (out.normalized().note or "")


def test_negative_beats_gold():
    assert Outcome(verified_success=True, user_correction=True, verification_source="manual").tier() == "negative"


def test_usage_total_prefers_reported_total():
    assert TokenUsage(input_tokens=10, output_tokens=5).total() == 15
    assert TokenUsage(input_tokens=10, output_tokens=5, reported_total_tokens=20).total() == 20


def test_event_roundtrip():
    event = TokenomicsEvent(
        kind="llm",
        name="call",
        usage=TokenUsage(input_tokens=10, output_tokens=2),
        measurement_source=MeasurementSourceRef(
            observer_id="runtime-a",
            logical_source_id="account-a",
            physical_source_id="host-a:store-1",
            identity_basis="storage",
        ),
    )
    got = TokenomicsEvent.from_dict(event.to_dict())
    assert got.trace_id == event.trace_id
    assert got.usage and got.usage.total() == 12
    assert got.measurement_source == event.measurement_source


def test_physical_identity_is_explicit_not_inferred_from_other_ids():
    a = MeasurementSourceRef(observer_id="runtime-a", logical_source_id="account-a", physical_source_id="host-a:store-1", identity_basis="storage")
    b = MeasurementSourceRef(observer_id="runtime-b", logical_source_id="account-a", physical_source_id="host-a:store-1", identity_basis="storage")
    c = MeasurementSourceRef(observer_id="runtime-a", logical_source_id="account-a", physical_source_id="host-b:store-1", identity_basis="storage")
    assert a.observer_id != b.observer_id
    assert a.physical_source_id == b.physical_source_id
    assert a.logical_source_id == c.logical_source_id
    assert a.physical_source_id != c.physical_source_id


def test_measurement_completeness_is_independent_of_execution_status():
    event = TokenomicsEvent(
        kind="quota",
        name="partial-read",
        status="ok",
        measurement=MeasurementState(completeness="partial", reason="one transcript unreadable"),
    )
    assert event.status == "ok"
    assert event.measurement and event.measurement.completeness == "partial"


def test_unsupported_and_failed_measurements_are_distinct():
    assert MeasurementState(completeness="unsupported").completeness != MeasurementState(completeness="failed").completeness
