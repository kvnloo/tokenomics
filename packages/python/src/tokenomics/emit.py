"""Append canonical tokenomics events to ~/.z0int/tokenomics/events.jsonl."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .jsonl import JsonlSink
from .models import TokenomicsEvent


def default_events_path(root: Path | None = None) -> Path:
    base = root or Path(os.environ.get("Z0INT_HOME", Path.home() / ".z0int")).expanduser()
    return base / "tokenomics" / "events.jsonl"


def append_event(event: TokenomicsEvent | dict[str, Any], *, path: Path | None = None) -> Path:
    p = path or default_events_path()
    ev = event if isinstance(event, TokenomicsEvent) else TokenomicsEvent.from_dict(event)
    JsonlSink(p).emit(ev)
    return p


def append_raw(raw: dict[str, Any], *, path: Path | None = None) -> Path:
    from .report import _coerce_event

    ev = _coerce_event(raw)
    if ev is None:
        raise ValueError("row is not a recognized tokenomics event shape")
    return append_event(ev, path=path)
