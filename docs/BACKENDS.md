# Backends

## OpenTelemetry Collector

The included Collector accepts OTLP HTTP/gRPC and forwards traces to Phoenix. Replace the exporter to target another OTel backend without changing application instrumentation.

## Phoenix

Phoenix is a strong local development backend because it is OTel-native and supports traces, evaluations, datasets and experiments. The application contract remains OTLP, not Phoenix-specific APIs.

## Langfuse

Langfuse accepts OTLP at its OpenTelemetry endpoint. Point an OTLP exporter/Collector there when session cost tracking or its UI is preferable.

## No backend

JSONL alone is supported and expected to remain useful for CI, offline experiment replay and reproducibility.
