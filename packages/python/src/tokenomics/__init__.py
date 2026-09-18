"""Agent Tokenomics: neutral measurement contracts for LLM harnesses."""

from .aggregate import TraceSummary, summarize_trace, summarize_traces, tokens_per_verified_task
from .adapters import from_kerdoios_observation, from_z0int_receipt
from .experiment import treatment_hash
from .ids import new_event_id, new_span_id, new_trace_id
from .jsonl import JsonlSink, iter_jsonl
from .models import (
    ContextEconomics,
    Economics,
    Experiment,
    Latency,
    ModelRef,
    Outcome,
    QuotaSnapshot,
    TokenUsage,
    TokenomicsEvent,
)
from .otel import OtelSink, to_otel_attributes
from .recorder import MemorySink, MultiSink, Recorder

__all__ = [
    "ContextEconomics",
    "Economics",
    "Experiment",
    "JsonlSink",
    "Latency",
    "MemorySink",
    "ModelRef",
    "MultiSink",
    "OtelSink",
    "Outcome",
    "QuotaSnapshot",
    "Recorder",
    "TokenUsage",
    "TokenomicsEvent",
    "TraceSummary",
    "from_kerdoios_observation",
    "from_z0int_receipt",
    "iter_jsonl",
    "new_event_id",
    "new_span_id",
    "new_trace_id",
    "summarize_trace",
    "summarize_traces",
    "to_otel_attributes",
    "tokens_per_verified_task",
    "treatment_hash",
]

__version__ = "0.1.0"
