from __future__ import annotations

import secrets
import uuid


def new_trace_id() -> str:
    """Return a 128-bit lowercase hex id compatible with OTel trace-id width."""
    return uuid.uuid4().hex


def new_span_id() -> str:
    """Return a non-zero 64-bit lowercase hex id compatible with OTel span-id width."""
    while True:
        value = secrets.token_hex(8)
        if value != "0000000000000000":
            return value


def new_event_id() -> str:
    return uuid.uuid4().hex
