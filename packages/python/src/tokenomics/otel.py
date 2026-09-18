from __future__ import annotations

from typing import Any

from .models import TokenomicsEvent


def _put(attrs: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        attrs[key] = value


def to_otel_attributes(event: TokenomicsEvent) -> dict[str, str | int | float | bool]:
    """Map a tokenomics event onto OTel GenAI conventions + tokenomics extensions.

    Content is intentionally absent: this package records economics and provenance,
    not prompts/completions, unless the host adds content through its own policy.
    """
    attrs: dict[str, Any] = {
        "tokenomics.schema": event.schema,
        "tokenomics.event.kind": event.kind,
        "tokenomics.event.id": event.event_id,
        "tokenomics.trace.id": event.trace_id,
        "tokenomics.span.id": event.span_id,
        "tokenomics.execution.role": event.role,
        "tokenomics.status": event.status,
    }
    _put(attrs, "tokenomics.parent_span.id", event.parent_span_id)
    _put(attrs, "tokenomics.session.id", event.session_id)
    _put(attrs, "tokenomics.task.id", event.task_id)
    _put(attrs, "tokenomics.capability.id", event.capability_id)
    _put(attrs, "tokenomics.harness.name", event.harness)
    _put(attrs, "service.name", event.service)

    if event.model:
        _put(attrs, "gen_ai.provider.name", event.model.provider)
        _put(attrs, "gen_ai.request.model", event.model.name)
        _put(attrs, "tokenomics.model.role", event.model.role)
        _put(attrs, "tokenomics.provider.origin", event.model.origin_provider)
        _put(attrs, "tokenomics.model.revision", event.model.revision)
    if event.usage:
        _put(attrs, "gen_ai.usage.input_tokens", event.usage.input_tokens)
        _put(attrs, "gen_ai.usage.output_tokens", event.usage.output_tokens)
        _put(attrs, "gen_ai.usage.cache_read.input_tokens", event.usage.cached_input_tokens)
        _put(attrs, "gen_ai.usage.cache_creation.input_tokens", event.usage.cache_write_input_tokens)
        _put(attrs, "gen_ai.usage.reasoning.output_tokens", event.usage.reasoning_tokens)
        _put(attrs, "tokenomics.usage.context_tokens", event.usage.context_tokens)
        _put(attrs, "tokenomics.usage.reported_total_tokens", event.usage.reported_total_tokens)
        _put(attrs, "tokenomics.usage.attribution", event.usage.attribution)
        _put(attrs, "tokenomics.usage.source", event.usage.source)
    if event.economics:
        _put(attrs, "tokenomics.cost.usd", event.economics.cost_usd)
        _put(attrs, "tokenomics.baseline.cost.usd", event.economics.baseline_cost_usd)
        _put(attrs, "tokenomics.price.input_usd_per_million", event.economics.input_price_usd_per_million)
        _put(attrs, "tokenomics.price.output_usd_per_million", event.economics.output_price_usd_per_million)
        _put(attrs, "tokenomics.price.cache_read_usd_per_million", event.economics.cache_read_price_usd_per_million)
        _put(attrs, "tokenomics.price.cache_write_usd_per_million", event.economics.cache_write_price_usd_per_million)
        _put(attrs, "tokenomics.tokens.avoided.estimated", event.economics.estimated_tokens_avoided)
        _put(attrs, "tokenomics.tokens.avoided.measured", event.economics.measured_tokens_avoided)
    if event.latency:
        _put(attrs, "tokenomics.latency.duration_ms", event.latency.duration_ms)
        _put(attrs, "gen_ai.response.time_to_first_chunk", None if event.latency.ttft_ms is None else event.latency.ttft_ms / 1000.0)
        _put(attrs, "tokenomics.latency.queue_ms", event.latency.queue_ms)
    if event.context:
        for field, value in {
            "policy": event.context.policy,
            "spilled_bytes": event.context.spilled_bytes,
            "granted_bytes": event.context.granted_bytes,
            "reintroduced_bytes": event.context.reintroduced_bytes,
            "spill_count": event.context.spill_count,
            "retrieval_calls": event.context.retrieval_calls,
            "worker_calls_avoided": event.context.worker_calls_avoided,
            "compaction_count": event.context.compaction_count,
            "citation_count": event.context.citation_count,
            "missed_evidence_count": event.context.missed_evidence_count,
            "unsupported_claim_count": event.context.unsupported_claim_count,
        }.items():
            _put(attrs, f"tokenomics.context.{field}", value)
    for prefix, quota in (("before", event.quota_before), ("after", event.quota_after)):
        if quota:
            _put(attrs, f"tokenomics.quota.{prefix}.remaining", quota.remaining)
            _put(attrs, f"tokenomics.quota.{prefix}.reset_seconds", quota.reset_seconds)
            _put(attrs, f"tokenomics.quota.{prefix}.remaining_credits", quota.remaining_credits)
            _put(attrs, f"tokenomics.quota.{prefix}.source", quota.source)
    if event.experiment:
        for field, value in event.experiment.__dict__.items():
            _put(attrs, f"tokenomics.experiment.{field}", value)
    if event.outcome:
        outcome = event.outcome.normalized()
        _put(attrs, "tokenomics.outcome.tier", outcome.tier())
        _put(attrs, "tokenomics.outcome.verification_source", outcome.verification_source)
        _put(attrs, "tokenomics.outcome.source", outcome.source)
        _put(attrs, "tokenomics.outcome.retries", outcome.retries)
    attrs.update(event.attributes)
    return {k: v for k, v in attrs.items() if isinstance(v, (str, int, float, bool))}


class OtelSink:
    """Optional OpenTelemetry trace sink.

    Pass an existing tracer to reuse an application's provider, or use `from_otlp`
    for a standalone exporter. Post-hoc events preserve tokenomics trace ids as
    attributes; live callers should instrument their native span hierarchy and use
    these attributes on those spans when exact OTel parentage matters.
    """

    def __init__(self, tracer: Any):
        self.tracer = tracer

    @classmethod
    def from_otlp(
        cls,
        endpoint: str = "http://localhost:4318/v1/traces",
        *,
        service_name: str = "agent-tokenomics",
        headers: dict[str, str] | None = None,
    ) -> "OtelSink":
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            raise RuntimeError("install agent-tokenomics[otel] to use OTLP export") from exc
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers or {})
        provider.add_span_processor(BatchSpanProcessor(exporter))
        # Do not replace the process global provider. The sink owns its provider.
        tracer = provider.get_tracer("agent-tokenomics")
        sink = cls(tracer)
        sink._provider = provider  # type: ignore[attr-defined]
        return sink

    def emit(self, event: TokenomicsEvent) -> None:
        attrs = to_otel_attributes(event)
        start_ns = int((event.started_at or event.ts) * 1_000_000_000)
        end_s = event.ended_at
        if end_s is None and event.latency and event.latency.duration_ms is not None:
            end_s = (event.started_at or event.ts) + event.latency.duration_ms / 1000.0
        end_ns = int((end_s or event.ts) * 1_000_000_000)
        span = self.tracer.start_span(event.name, start_time=start_ns, attributes=attrs)
        if event.status == "error":
            try:
                from opentelemetry.trace import Status, StatusCode
                span.set_status(Status(StatusCode.ERROR))
            except ImportError:
                pass
        span.end(end_time=max(start_ns, end_ns))

    def shutdown(self) -> None:
        provider = getattr(self, "_provider", None)
        if provider is not None:
            provider.shutdown()
