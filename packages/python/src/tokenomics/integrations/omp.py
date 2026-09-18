"""Emit Tokenomics events from OMP provider/session accounting seams."""

from __future__ import annotations

from typing import Any

from ..adapters import from_omp_provider_usage, from_omp_session_aggregate
from ..emit import append_event


def emit_provider_call(raw: dict[str, Any]) -> None:
    raw = dict(raw)
    raw.setdefault("schema", "omp.provider_usage.v0")
    raw.setdefault("harness", "omp")
    append_event(from_omp_provider_usage(raw))


def emit_session_aggregate(raw: dict[str, Any]) -> None:
    raw = dict(raw)
    raw.setdefault("schema", "omp.session_usage.v0")
    raw.setdefault("harness", "omp")
    append_event(from_omp_session_aggregate(raw))
