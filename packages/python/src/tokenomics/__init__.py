"""Agent Tokenomics: neutral measurement contracts for LLM harnesses."""

from .aggregate import TraceSummary, summarize_trace, summarize_traces, tokens_per_verified_task
from .coverage import COVERAGE_SCHEMA, build_coverage_report, coverage_report_from_sources, format_coverage_text
from .gap_priority import gaps_for_autoresearch, rank_measurement_gaps
from .report import REPORT_SCHEMA, build_savings_report, classify_savings, format_savings_text, savings_report_from_sources
from .trace_accounting import TraceFrontierRollup, rollup_trace, rollup_traces
from .adapters import (
    from_flow_prepare,
    from_flow_prediction,
    from_hermes_provider_usage,
    from_kerdoios_observation,
    from_omp_provider_usage,
    from_z0int_receipt,
)
from .emit import append_event, append_raw
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
from .orchestration import (
    SCHEMA,
    SCHEMA as ORCHESTRATION_SCHEMA,
    LatencySummary,
    OrchestrationObservation,
    observation_to_event,
    percentile,
    summarize_latency,
    summarize_observations,
)
from .otel import OtelSink, to_otel_attributes
from .recorder import MemorySink, MultiSink, Recorder

__all__ = [
    "ContextEconomics",
    "Economics",
    "Experiment",
    "JsonlSink",
    "Latency",
    "LatencySummary",
    "MemorySink",
    "ModelRef",
    "MultiSink",
    "OrchestrationObservation",
    "OtelSink",
    "Outcome",
    "QuotaSnapshot",
    "Recorder",
    "TokenUsage",
    "TokenomicsEvent",

    "COVERAGE_SCHEMA",
    "ORCHESTRATION_SCHEMA",
    "SCHEMA",
    "TraceFrontierRollup",
    "build_coverage_report",
    "coverage_report_from_sources",
    "format_coverage_text",
    "gaps_for_autoresearch",
    "rank_measurement_gaps",
    "rollup_trace",
    "rollup_traces",
    "from_hermes_provider_usage",
    "from_omp_provider_usage",
    "append_event",
    "append_raw",
    "REPORT_SCHEMA",
    "TraceSummary",
    "build_savings_report",
    "classify_savings",
    "format_savings_text",
    "savings_report_from_sources",
    "from_flow_prepare",
    "from_flow_prediction",
    "from_kerdoios_observation",
    "from_z0int_receipt",
    "iter_jsonl",
    "new_event_id",
    "new_span_id",
    "new_trace_id",
    "observation_to_event",
    "percentile",
    "summarize_latency",
    "summarize_observations",
    "summarize_trace",
    "summarize_traces",
    "to_otel_attributes",
    "tokens_per_verified_task",
    "treatment_hash",
]

__version__ = "0.1.0"
