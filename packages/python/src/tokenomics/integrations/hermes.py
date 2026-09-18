"""Emit Tokenomics events from Hermes accounting seams.

Call from ``agent.turn_usage.record_response_usage`` after ``normalize_usage``.
Does not replace Hermes counters — append-only projection to ~/.z0int/tokenomics/events.jsonl.
"""

from __future__ import annotations

from typing import Any

from ..adapters import from_hermes_provider_usage
from ..emit import append_event


def emit_provider_call(
    *,
    agent: Any,
    canonical_usage: Any,
    api_duration: float,
    response: Any | None = None,
    role: str = "root",
) -> None:
    usage_dict = {
        "input_tokens": getattr(canonical_usage, "input_tokens", None),
        "output_tokens": getattr(canonical_usage, "output_tokens", None),
        "prompt_tokens": getattr(canonical_usage, "prompt_tokens", None),
        "completion_tokens": getattr(canonical_usage, "output_tokens", None),
        "cache_read_tokens": getattr(canonical_usage, "cache_read_tokens", None),
        "cache_write_tokens": getattr(canonical_usage, "cache_write_tokens", None),
        "reasoning_tokens": getattr(canonical_usage, "reasoning_tokens", None),
        "total_tokens": getattr(canonical_usage, "total_tokens", None),
    }
    raw = {
        "schema": "hermes.provider_usage.v0",
        "harness": "hermes",
        "session_id": getattr(agent, "session_id", None),
        "trace_id": getattr(agent, "trace_id", None) or getattr(agent, "session_id", None),
        "provider": getattr(agent, "provider", None),
        "model": getattr(agent, "model", None),
        "role": role,
        "usage": usage_dict,
        "latency_ms": float(api_duration) * 1000.0,
        "response_id": getattr(response, "id", None) if response is not None else None,
    }
    append_event(from_hermes_provider_usage(raw))
