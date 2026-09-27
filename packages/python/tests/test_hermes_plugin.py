from __future__ import annotations

import importlib.metadata
import json
from types import SimpleNamespace

from tokenomics import iter_jsonl
from tokenomics.hermes_plugin import _reset_for_tests, on_post_llm_call, register


class FakeContext:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn


def test_registers_current_and_legacy_hermes_usage_hooks():
    ctx = FakeContext()
    register(ctx)
    assert ctx.hooks["post_api_request"] is on_post_llm_call
    assert ctx.hooks["post_llm_call"] is on_post_llm_call


def test_provider_response_usage_is_complete_and_content_free(tmp_path, monkeypatch):
    _reset_for_tests()
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("TOKENOMICS_JSONL", str(path))
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            prompt_tokens_details=SimpleNamespace(cached_tokens=3, cache_write_tokens=1),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=1),
        ),
        id="resp-1",
        provider="Anthropic",
    )

    on_post_llm_call(
        task_id="task-a",
        session_id="session-a",
        turn_id="turn-a",
        api_request_id="turn-a:api:1",
        provider="nous",
        model="claude",
        response=response,
        api_duration=0.25,
        api_call_count=1,
    )

    [event] = list(iter_jsonl(path))
    assert event.harness == "hermes"
    assert event.measurement_source
    assert event.measurement_source.measurement_state == "complete"
    assert event.measurement_source.state_reason == "provider_response_usage"
    assert event.usage and event.usage.input_tokens == 10
    assert event.usage.output_tokens == 2
    assert event.usage.cached_input_tokens == 3
    assert event.usage.cache_write_input_tokens == 1
    assert event.usage.reasoning_tokens == 1
    assert event.latency and event.latency.duration_ms == 250.0
    assert event.model and event.model.origin_provider == "Anthropic"

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "content" not in raw
    assert "messages" not in raw


def test_current_and_legacy_hooks_do_not_double_emit_same_call(tmp_path, monkeypatch):
    _reset_for_tests()
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("TOKENOMICS_JSONL", str(path))
    common = dict(
        task_id="task-a",
        session_id="session-a",
        turn_id="turn-a",
        provider="openai",
        model="gpt",
        api_call_count=2,
        usage={"input_tokens": 6, "output_tokens": 2},
    )
    on_post_llm_call(**common, api_request_id="turn-a:api:2")
    on_post_llm_call(**common, api_request_id="")
    assert len(list(iter_jsonl(path))) == 1


def test_calls_in_same_turn_share_trace_but_remain_incremental(tmp_path, monkeypatch):
    _reset_for_tests()
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("TOKENOMICS_JSONL", str(path))
    common = dict(
        task_id="task-a",
        session_id="session-a",
        turn_id="turn-a",
        provider="openai",
        model="gpt",
    )
    on_post_llm_call(
        **common,
        api_call_count=1,
        api_request_id="turn-a:api:1",
        usage={"input_tokens": 4, "output_tokens": 1},
    )
    on_post_llm_call(
        **common,
        api_call_count=2,
        api_request_id="turn-a:api:2",
        usage={"input_tokens": 6, "output_tokens": 2},
    )

    events = list(iter_jsonl(path))
    assert len(events) == 2
    assert events[0].trace_id == events[1].trace_id
    assert all(e.usage and e.usage.attribution == "incremental" for e in events)


def test_missing_usage_does_not_guess_failed_or_unsupported(tmp_path, monkeypatch):
    _reset_for_tests()
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("TOKENOMICS_JSONL", str(path))
    on_post_llm_call(
        task_id="task-a",
        session_id="session-a",
        turn_id="turn-a",
        provider="unknown",
        model="m",
        response=SimpleNamespace(usage=None),
    )
    assert not path.exists()


def test_distribution_declares_hermes_entry_point():
    eps = importlib.metadata.entry_points()
    group = (
        list(eps.select(group="hermes_agent.plugins"))
        if hasattr(eps, "select")
        else list(eps.get("hermes_agent.plugins", []))
    )
    assert any(
        ep.name == "tokenomics" and ep.value == "tokenomics.hermes_plugin:register"
        for ep in group
    )
