from tokenomics import Outcome, TokenUsage, TokenomicsEvent


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
    event = TokenomicsEvent(kind="llm", name="call", usage=TokenUsage(input_tokens=10, output_tokens=2))
    got = TokenomicsEvent.from_dict(event.to_dict())
    assert got.trace_id == event.trace_id
    assert got.usage and got.usage.total() == 12
