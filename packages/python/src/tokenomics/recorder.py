from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import TokenomicsEvent


class Sink(Protocol):
    def emit(self, event: TokenomicsEvent) -> None: ...


@dataclass
class MemorySink:
    events: list[TokenomicsEvent] = field(default_factory=list)

    def emit(self, event: TokenomicsEvent) -> None:
        self.events.append(event)


class MultiSink:
    def __init__(self, *sinks: Sink):
        self.sinks = tuple(sinks)

    def emit(self, event: TokenomicsEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)


class Recorder:
    """Minimal fan-out recorder. Applications own instrumentation timing."""

    def __init__(self, sink: Sink):
        self.sink = sink

    def record(self, event: TokenomicsEvent) -> TokenomicsEvent:
        self.sink.emit(event)
        return event
