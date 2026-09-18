"""Agent Tokenomics: neutral measurement contracts for LLM harnesses."""

from .aggregate import TraceSummary, summarize_trace, summarize_traces, tokens_per_verified_task
from .report import REPORT_SCHEMA, build_savings_report, classify_savings, format_savings_text, savings_report_from_sources
from .adapters import from_kerdoios_observation, from_z0int_receipt, from_bespoke_curation
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
    "REPORT_SCHEMA",
    "TraceSummary",
    "build_savings_report",
    "classify_savings",
    "format_savings_text",
    "savings_report_from_sources",
    "from_kerdoios_observation",
    "from_z0int_receipt",
    "from_bespoke_curation",
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
