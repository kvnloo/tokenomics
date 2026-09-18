from tokenomics import (
    ContextEconomics,
    JsonlSink,
    MultiSink,
    OtelSink,
    Outcome,
    Recorder,
    TokenUsage,
    TokenomicsEvent,
    new_trace_id,
)

trace = new_trace_id()
sinks = [JsonlSink("./tokenomics-example.jsonl")]
# Uncomment after `pip install -e '.[otel]'` and `docker compose up -d`:
# sinks.append(OtelSink.from_otlp("http://localhost:4318/v1/traces", service_name="example"))
recorder = Recorder(MultiSink(*sinks))

recorder.record(TokenomicsEvent(
    kind="llm",
    name="root",
    trace_id=trace,
    role="root",
    status="ok",
    usage=TokenUsage(input_tokens=5000, output_tokens=300, source="provider"),
))
recorder.record(TokenomicsEvent(
    kind="context",
    name="rlm.search-grants",
    trace_id=trace,
    context=ContextEconomics(policy="rlm-search-grants", spilled_bytes=100_000, granted_bytes=4_096),
))
recorder.record(TokenomicsEvent(
    kind="verification",
    name="tests",
    trace_id=trace,
    role="verifier",
    outcome=Outcome(verified_success=True, verification_source="pytest"),
))
