from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .ids import new_event_id, new_span_id, new_trace_id

SCHEMA = "tokenomics.event.v0"

EventKind = Literal[
    "task",
    "decision",
    "llm",
    "tool",
    "retrieval",
    "context",
    "verification",
    "quota",
    "placement",
    "other",
]
EventStatus = Literal["ok", "error", "cancelled", "unknown"]
ExecutionRole = Literal["root", "rlm_worker", "subagent", "verifier", "router", "other"]
UsageAttribution = Literal["incremental", "aggregate", "unknown"]
UsageSource = Literal["provider", "estimated", "derived", "unknown"]
OutcomeTier = Literal["gold", "negative", "execution", "soft", "unknown"]

GOLD_SIGNALS = (
    "verified_success",
    "verified",
    "test_pass",
    "verifier_ok",
    "pr_merged",
    "task_done",
)
NEGATIVE_TRUE_SIGNALS = ("user_correction", "reverted", "ci_failed")
AMBIENT_CLOSE_SOURCES = frozenset(
    {
        "bridge_turn_end",
        "bridge_agent_end",
        "bridge_agent_start",
        "omp_turn_end",
        "omp_agent_end",
        "close_turn",
    }
)


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


@dataclass(frozen=True)
class ModelRef:
    provider: str | None = None
    name: str | None = None
    role: str | None = None
    origin_provider: str | None = None
    revision: str | None = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    context_tokens: int | None = None
    reported_total_tokens: int | None = None
    attribution: UsageAttribution = "incremental"
    source: UsageSource = "unknown"

    def total(self) -> int | None:
        if self.reported_total_tokens is not None:
            return int(self.reported_total_tokens)
        values = (self.input_tokens, self.output_tokens)
        if all(v is None for v in values):
            return None
        return int(self.input_tokens or 0) + int(self.output_tokens or 0)


@dataclass(frozen=True)
class Economics:
    cost_usd: float | None = None
    baseline_cost_usd: float | None = None
    input_price_usd_per_million: float | None = None
    output_price_usd_per_million: float | None = None
    cache_read_price_usd_per_million: float | None = None
    cache_write_price_usd_per_million: float | None = None
    estimated_tokens_avoided: int | None = None
    measured_tokens_avoided: int | None = None


@dataclass(frozen=True)
class Latency:
    duration_ms: float | None = None
    ttft_ms: float | None = None
    queue_ms: float | None = None


@dataclass(frozen=True)
class ContextEconomics:
    policy: str | None = None
    spilled_bytes: int | None = None
    granted_bytes: int | None = None
    reintroduced_bytes: int | None = None
    spill_count: int | None = None
    retrieval_calls: int | None = None
    worker_calls_avoided: int | None = None
    compaction_count: int | None = None
    citation_count: int | None = None
    missed_evidence_count: int | None = None
    unsupported_claim_count: int | None = None


@dataclass(frozen=True)
class QuotaSnapshot:
    remaining: float | None = None
    reset_seconds: float | None = None
    remaining_credits: float | None = None
    source: str | None = None


@dataclass(frozen=True)
class Experiment:
    experiment_id: str | None = None
    pair_id: str | None = None
    task_snapshot_id: str | None = None
    arm_id: str | None = None
    treatment_hash: str | None = None
    selection_policy: str | None = None
    assignment_probability: float | None = None
    reference_requested: bool | None = None
    reason_for_reference: str | None = None
    replay_grade: str | None = None
    verifier_class: str | None = None


@dataclass
class Outcome:
    execution_completed: bool | None = None
    verified_success: bool | None = None
    verified: bool | None = None
    success: bool | None = None
    tool_ok: bool | None = None
    test_pass: bool | None = None
    task_done: bool | None = None
    user_correction: bool | None = None
    reverted: bool | None = None
    verifier_ok: bool | None = None
    ci_failed: bool | None = None
    pr_merged: bool | None = None
    retries: int | None = None
    note: str | None = None
    source: str | None = None
    verification_source: str | None = None

    def normalized(self) -> "Outcome":
        out = Outcome(**asdict(self))
        source = out.source or ""
        ambient = source in AMBIENT_CLOSE_SOURCES or (
            source.startswith("bridge_") and source not in {"bridge_manual", "bridge_verified"}
        )
        if ambient and not out.verification_source:
            for key in GOLD_SIGNALS:
                if getattr(out, key) is True:
                    setattr(out, key, None)
            if out.execution_completed is not False:
                out.execution_completed = True
            if out.note is None:
                out.note = "ambient_close_sanitized"
            elif "ambient_close_sanitized" not in out.note:
                out.note += "|ambient_close_sanitized"
        return out

    def tier(self) -> OutcomeTier:
        out = self.normalized()
        data = asdict(out)
        negative = any(data.get(k) is True for k in NEGATIVE_TRUE_SIGNALS) or any(
            data.get(k) is False for k in GOLD_SIGNALS
        )
        if negative:
            return "negative"
        if any(data.get(k) is True for k in GOLD_SIGNALS):
            return "gold"
        if out.execution_completed is True:
            return "execution"
        if out.success is True or out.tool_ok is True:
            return "soft"
        return "unknown"


@dataclass
class TokenomicsEvent:
    kind: EventKind
    name: str
    trace_id: str = field(default_factory=new_trace_id)
    span_id: str = field(default_factory=new_span_id)
    event_id: str = field(default_factory=new_event_id)
    parent_span_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    capability_id: str | None = None
    harness: str | None = None
    service: str | None = None
    role: ExecutionRole = "other"
    status: EventStatus = "unknown"
    model: ModelRef | None = None
    usage: TokenUsage | None = None
    economics: Economics | None = None
    latency: Latency | None = None
    context: ContextEconomics | None = None
    quota_before: QuotaSnapshot | None = None
    quota_after: QuotaSnapshot | None = None
    experiment: Experiment | None = None
    outcome: Outcome | None = None
    started_at: float | None = None
    ended_at: float | None = None
    ts: float = field(default_factory=time.time)
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if len(self.trace_id) != 32:
            raise ValueError("trace_id must be 32 lowercase/uppercase hex characters")
        int(self.trace_id, 16)
        if len(self.span_id) != 16 or int(self.span_id, 16) == 0:
            raise ValueError("span_id must be a non-zero 16-character hex value")
        if self.parent_span_id is not None:
            if len(self.parent_span_id) != 16 or int(self.parent_span_id, 16) == 0:
                raise ValueError("parent_span_id must be a non-zero 16-character hex value")
        if self.ended_at is not None and self.started_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.outcome is not None:
            normalized = self.outcome.normalized()
            data["outcome"] = asdict(normalized)
            data["outcome"]["tier"] = normalized.tier()
        data["schema"] = SCHEMA
        return _drop_none(data)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TokenomicsEvent":
        if raw.get("schema") not in (None, SCHEMA):
            raise ValueError(f"unsupported schema: {raw.get('schema')}")
        nested = {
            "model": ModelRef,
            "usage": TokenUsage,
            "economics": Economics,
            "latency": Latency,
            "context": ContextEconomics,
            "quota_before": QuotaSnapshot,
            "quota_after": QuotaSnapshot,
            "experiment": Experiment,
            "outcome": Outcome,
        }
        kwargs = dict(raw)
        kwargs.pop("schema", None)
        for key, typ in nested.items():
            value = kwargs.get(key)
            if isinstance(value, dict):
                if key == "outcome":
                    value = {k: v for k, v in value.items() if k != "tier"}
                kwargs[key] = typ(**value)
        known = cls.__dataclass_fields__
        extras = {k: kwargs.pop(k) for k in list(kwargs) if k not in known}
        if extras:
            current = dict(kwargs.get("extra") or {})
            current.update(extras)
            kwargs["extra"] = current
        return cls(**kwargs)
