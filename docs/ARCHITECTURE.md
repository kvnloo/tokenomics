# Architecture

## Boundary

Agent Tokenomics owns **measurement semantics**, not generic observability infrastructure.

Own here:

- verified outcome tiers;
- experiment/counterfactual identity;
- trace-level usage reconciliation;
- context economics;
- quota snapshots;
- compatibility views for z0int and Kerdoios.

Reuse elsewhere:

- trace transport and collection: OpenTelemetry / OTLP;
- storage/UI: Phoenix, Langfuse, Grafana-compatible OTel backends;
- provider-specific quota header parsing: Kerdoios/provider adapters;
- decision policy/training: z0int;
- resource placement: Kerdoios.

## Event, trace, receipt

A `TokenomicsEvent` represents one operation or observation. Events sharing `trace_id` represent one task/session-level experiment unit.

A legacy z0int `DecisionReceipt` is therefore a compatibility/materialized view, not the only storage model.

This fixes the root + worker accounting problem: one task may have several model calls at different times while a verifier arrives later.

## Durable-first

JSONL is intentionally first-class:

1. host emits a canonical event;
2. local JSONL append succeeds independently of backend availability;
3. an OTLP sink may project the same event into an observability backend;
4. later joins or verification append new events rather than rewriting history.

## Standard and custom fields

Use current OTel GenAI conventions for standard model-call fields, for example:

- `gen_ai.provider.name`
- `gen_ai.request.model`
- `gen_ai.usage.input_tokens`
- `gen_ai.usage.output_tokens`
- `gen_ai.usage.cache_read.input_tokens`
- `gen_ai.usage.cache_creation.input_tokens`
- `gen_ai.usage.reasoning.output_tokens`
- `gen_ai.response.time_to_first_chunk`

Use `tokenomics.*` only where the standard does not express the needed research semantic.

## Privacy

The canonical schema has no prompt/completion content field. Harnesses may attach their own content telemetry under their own privacy policy, but Agent Tokenomics does not require it for token/cost/outcome studies.
