from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Iterator

from .models import TokenomicsEvent


class JsonlSink:
    """Append-only local durability sink.

    A single encoded line is written with O_APPEND. This is intentionally tiny:
    JSONL is the offline source of truth even when OTLP/Phoenix is unavailable.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def emit(self, event: TokenomicsEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"), default=str) + "\n").encode()
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)


def iter_jsonl(path: str | Path, *, strict: bool = False) -> Iterator[TokenomicsEvent]:
    target = Path(path).expanduser()
    if not target.is_file():
        return
    with target.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                yield TokenomicsEvent.from_dict(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                if strict:
                    raise ValueError(f"invalid tokenomics JSONL at {target}:{lineno}")
                continue


def write_jsonl(path: str | Path, events: Iterable[TokenomicsEvent]) -> None:
    sink = JsonlSink(path)
    for event in events:
        sink.emit(event)
