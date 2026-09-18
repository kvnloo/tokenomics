from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tokenomics import ModelRef, OtelSink, TokenUsage, TokenomicsEvent


def test_otel_sink_emits_completed_span():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    sink = OtelSink(provider.get_tracer("test"))
    sink.emit(TokenomicsEvent(
        kind="llm",
        name="root",
        role="root",
        status="ok",
        model=ModelRef(provider="openai", name="gpt-x"),
        usage=TokenUsage(input_tokens=11, output_tokens=2, source="provider"),
    ))
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].attributes["gen_ai.usage.input_tokens"] == 11
    assert spans[0].attributes["tokenomics.execution.role"] == "root"
