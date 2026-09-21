import json
from pathlib import Path

from tokenomics import from_kerdoios_observation, from_z0int_receipt

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    return json.loads((ROOT / "fixtures" / name).read_text())


def test_z0int_adapter_preserves_verification_and_usage():
    e = from_z0int_receipt(load("z0int_receipt.json"))
    assert e.trace_id == "0123456789abcdef0123456789abcdef"
    assert e.outcome and e.outcome.tier() == "gold"
    assert e.usage and e.usage.total() == 1200
    assert e.experiment and e.experiment.arm_id == "search-grants"


def test_kerdoios_adapter_preserves_quota_and_cost():
    e = from_kerdoios_observation(load("kerdoios_observation.json"))
    assert e.model and e.model.provider == "cerebras"
    assert e.quota_before and e.quota_before.remaining == 60000
    assert e.quota_after and e.quota_after.remaining == 59050
    assert e.economics and e.economics.cost_usd == 0.002


def test_kerdoios_adapter_carries_request_id_time_and_unknown_cost():
    e = from_kerdoios_observation(
        {
            "trace_id": "a" * 32,
            "provider": "groq",
            "model": "llama-x",
            "task_id": "w-9",
            "request_id": "req_abc",
            "started_at": 100.0,
            "ended_at": 100.5,
            "completed": True,
            "input_tokens": 10,
            "output_tokens": 2,
        }
    )
    assert e.request_id == "req_abc"
    assert e.task_id == "w-9"
    assert e.started_at == 100.0 and e.ended_at == 100.5
    assert e.ts == 100.5
    # Missing cost is unknown, not a fabricated zero.
    assert e.economics is not None and e.economics.cost_usd is None
    assert e.outcome and e.outcome.execution_completed is True
    assert e.outcome.verified_success is None
    assert e.outcome.success is True
    # Missing retry signal is unknown, not zero retries.
    assert e.outcome.retries is None


def test_kerdoios_adapter_zero_cost_is_preserved():
    e = from_kerdoios_observation(
        {"trace_id": "b" * 32, "provider": "cerebras", "model": "m", "completed": True, "actual_cost": 0}
    )
    assert e.economics is not None and e.economics.cost_usd == 0.0


def test_kerdoios_adapter_missing_execution_signal_is_unknown():
    e = from_kerdoios_observation({"trace_id": "c" * 32, "provider": "groq", "model": "m"})
    assert e.status == "unknown"
    assert e.outcome and e.outcome.execution_completed is None
    assert e.outcome.success is None
    assert e.outcome.verified_success is None


def test_kerdoios_adapter_retry_state_is_explicit_when_present():
    e = from_kerdoios_observation(
        {"trace_id": "d" * 32, "provider": "cerebras", "model": "m", "completed": True, "fallback_count": 2}
    )
    assert e.outcome and e.outcome.retries == 2
    e2 = from_kerdoios_observation(
        {"trace_id": "d" * 32, "provider": "cerebras", "model": "m", "completed": True, "retried": True}
    )
    assert e2.outcome and e2.outcome.retries == 1


from tokenomics.adapters import from_hermes_provider_usage, from_omp_provider_usage


def test_omp_adapter_preserves_provider_usage():
    e = from_omp_provider_usage(
        {
            "trace_id": "0123456789abcdef0123456789abcdef",
            "session_id": "omp-s1",
            "provider": "anthropic",
            "model": "claude-sonnet",
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 300,
                "cached_input_tokens": 400,
                "cache_write_tokens": 50,
                "reasoning_output_tokens": 100,
            },
            "cost_usd": 0.012,
        }
    )
    assert e.harness == "omp"
    assert e.usage and e.usage.attribution == "incremental"
    assert e.usage.source == "provider"
    assert e.usage.input_tokens == 1200
    assert e.usage.output_tokens == 300
    assert e.usage.cached_input_tokens == 400
    assert e.usage.cache_write_input_tokens == 50
    assert e.usage.reasoning_tokens == 100
    assert e.economics and e.economics.cost_usd == 0.012


def test_hermes_adapter_preserves_provider_usage():
    e = from_hermes_provider_usage(
        {
            "trace_id": "fedcba9876543210fedcba9876543210",
            "session_id": "hermes-s1",
            "provider": "openai",
            "model": "gpt-4.1",
            "usage": {
                "input_tokens": 800,
                "output_tokens": 120,
                "cache_read_tokens": 200,
                "cache_write_tokens": 10,
                "reasoning_tokens": 64,
            },
            "latency_ms": 950.0,
        }
    )
    assert e.harness == "hermes"
    assert e.usage and e.usage.attribution == "incremental"
    assert e.usage.input_tokens == 800
    assert e.usage.cache_write_input_tokens == 10
    assert e.latency and e.latency.duration_ms == 950.0
