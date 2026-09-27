from tokenomics import (
    ContextEconomics,
    MeasurementSourceRef,
    ModelRef,
    Outcome,
    TokenUsage,
    TokenomicsEvent,
    to_otel_attributes,
)


def test_otel_mapping_uses_genai_for_standard_usage_and_custom_context():
    event = TokenomicsEvent(
        kind="llm",
        name="rlm.query",
        role="rlm_worker",
        model=ModelRef(provider="openai", name="gpt-x"),
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_input_tokens=30, source="provider"),
        measurement_source=MeasurementSourceRef(
            observer_id="runtime-b",
            logical_source_id="account-a",
            physical_source_id="host-a:store-1",
            identity_basis="storage",
            measurement_state="partial",
            state_reason="sparse_runtime_update",
        ),
        context=ContextEconomics(policy="rlm-search", granted_bytes=4096, missed_evidence_count=0),
        outcome=Outcome(execution_completed=True),
    )
    attrs = to_otel_attributes(event)
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.cache_read.input_tokens"] == 30
    assert attrs["tokenomics.measurement.observer_id"] == "runtime-b"
    assert attrs["tokenomics.measurement.logical_source_id"] == "account-a"
    assert attrs["tokenomics.measurement.physical_source_id"] == "host-a:store-1"
    assert attrs["tokenomics.measurement.identity_basis"] == "storage"
    assert attrs["tokenomics.measurement.state"] == "partial"
    assert attrs["tokenomics.measurement.state_reason"] == "sparse_runtime_update"
    assert attrs["tokenomics.context.granted_bytes"] == 4096
    assert attrs["tokenomics.outcome.tier"] == "execution"
    assert not any("prompt" in k or "completion" in k for k in attrs)
