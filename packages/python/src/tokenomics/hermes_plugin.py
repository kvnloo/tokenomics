"""Hermes Agent plugin bridge for Agent Tokenomics.

The plugin is discovered through the hermes_agent.plugins Python entry-point
group and remains opt-in under Hermes' normal plugins.enabled gate.

It exports only usage metadata. Prompt, completion, tool arguments/results,
credentials, account labels, and profile paths are never recorded here.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .emit import append_raw

_SEEN_LIMIT = 4096
_LOCK = threading.Lock()
_SEEN: "OrderedDict[str, None]" = OrderedDict()


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _count(value: Any, *names: str) -> int | None:
    for name in names:
        candidate = _get(value, name)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            return max(0, int(candidate))
    return None


def _usage_from_hook(response: Any, usage: Any) -> dict[str, int] | None:
    """Normalize current Hermes hook usage without importing Hermes internals."""
    source = usage if isinstance(usage, dict) and usage else _get(response, "usage")
    if source is None:
        return None

    input_tokens = _count(source, "input_tokens", "prompt_tokens", "input")
    output_tokens = _count(source, "output_tokens", "completion_tokens", "output")
    total_tokens = _count(source, "total_tokens", "total")

    prompt_details = _get(source, "prompt_tokens_details")
    completion_details = _get(source, "completion_tokens_details")
    cache_read = _count(source, "cache_read_tokens", "cached_input_tokens")
    if cache_read is None:
        cache_read = _count(prompt_details, "cached_tokens", "cache_read_tokens")
    cache_write = _count(source, "cache_write_tokens", "cache_write_input_tokens")
    if cache_write is None:
        cache_write = _count(prompt_details, "cache_write_tokens")
    reasoning = _count(source, "reasoning_tokens", "reasoning_output_tokens")
    if reasoning is None:
        reasoning = _count(completion_details, "reasoning_tokens")

    if not any(
        value is not None
        for value in (
            input_tokens,
            output_tokens,
            total_tokens,
            cache_read,
            cache_write,
            reasoning,
        )
    ):
        return None

    inp = input_tokens or 0
    out = output_tokens or 0
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_tokens": cache_read or 0,
        "cache_write_tokens": cache_write or 0,
        "reasoning_tokens": reasoning or 0,
        "total_tokens": total_tokens if total_tokens is not None else inp + out,
    }


def _trace_id(*, turn_id: str, task_id: str, session_id: str, api_request_id: str) -> str:
    """Stable 128-bit correlation id for one Hermes turn, with no raw local id."""
    scope = turn_id or task_id or session_id or api_request_id
    if not scope:
        scope = f"anonymous:{time.time_ns()}:{threading.get_ident()}"
    return hashlib.sha256(f"hermes:{scope}".encode("utf-8", "replace")).hexdigest()[:32]


def _dedupe_key(
    *,
    turn_id: str,
    api_call_count: int,
    api_request_id: str,
    response_id: str,
) -> str | None:
    # Prefer turn + ordinal because current post_api_request and legacy
    # post_llm_call may carry different request-id detail for the same call.
    if turn_id and api_call_count > 0:
        return f"turn:{turn_id}:call:{api_call_count}"
    if api_request_id:
        return f"request:{api_request_id}"
    if response_id:
        return f"response:{response_id}"
    return None


def _claim_once(key: str | None) -> bool:
    """Bounded compatibility dedupe for post_api_request + post_llm_call."""
    if key is None:
        return True
    with _LOCK:
        if key in _SEEN:
            _SEEN.move_to_end(key)
            return False
        _SEEN[key] = None
        while len(_SEEN) > _SEEN_LIMIT:
            _SEEN.popitem(last=False)
        return True


def _events_path() -> Path:
    configured = os.environ.get("TOKENOMICS_JSONL", "").strip()
    if configured:
        return Path(configured).expanduser()

    # Imported only inside Hermes. Keep profile isolation when Hermes exposes
    # its canonical path helper, without making Hermes a package dependency.
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return get_hermes_home() / "tokenomics" / "events.jsonl"
    except Exception:
        home = os.environ.get("HERMES_HOME", "").strip()
        base = Path(home).expanduser() if home else Path.home() / ".hermes"
        return base / "tokenomics" / "events.jsonl"


def on_post_llm_call(
    *,
    task_id: str = "",
    session_id: str = "",
    provider: str = "",
    model: str = "",
    api_call_count: int = 0,
    response: Any = None,
    usage: Any = None,
    api_duration: float = 0.0,
    turn_id: str = "",
    api_request_id: str = "",
    response_model: Any = None,
    **_: Any,
) -> None:
    """Export one complete incremental row when Hermes reports real provider usage."""
    counters = _usage_from_hook(response, usage)
    if counters is None:
        # Absence does not tell us whether usage is failed or unsupported.
        return

    if isinstance(response_model, str) and response_model:
        model = response_model

    response_id_value = _get(response, "id")
    response_id = response_id_value if isinstance(response_id_value, str) else ""
    key = _dedupe_key(
        turn_id=turn_id,
        api_call_count=int(api_call_count or 0),
        api_request_id=api_request_id,
        response_id=response_id,
    )
    if not _claim_once(key):
        return

    upstream_value = _get(response, "provider")
    upstream = upstream_value if isinstance(upstream_value, str) and upstream_value else None
    row = {
        "schema": "hermes.provider_usage.v0",
        "kind": "llm",
        "name": "hermes.provider_call",
        "trace_id": _trace_id(
            turn_id=turn_id,
            task_id=task_id,
            session_id=session_id,
            api_request_id=api_request_id,
        ),
        "session_id": session_id or None,
        "task_id": task_id or None,
        "provider": provider or None,
        "model": model or None,
        "upstream_provider": upstream,
        "request_id": response_id or api_request_id or None,
        "usage": counters,
        "latency_ms": max(0.0, float(api_duration or 0.0) * 1000.0),
        "measurement_state": "complete",
        "state_reason": "provider_response_usage",
        "status": "ok",
        "timestamp": time.time(),
    }

    try:
        with _LOCK:
            append_raw({k: v for k, v in row.items() if v is not None}, path=_events_path())
    except Exception:
        # Observability is fail-open: never change the agent turn result.
        return


def register(ctx: Any) -> None:
    """Hermes entry-point registration; both names preserve hook compatibility."""
    ctx.register_hook("post_api_request", on_post_llm_call)
    ctx.register_hook("post_llm_call", on_post_llm_call)


def _reset_for_tests() -> None:
    with _LOCK:
        _SEEN.clear()


__all__ = ["on_post_llm_call", "register"]
