# Tokenomics spec

`tokenomics.event.v0` is the durable domain record. It is intentionally smaller than a full observability product.

The schema distinguishes four concepts that agent harnesses often collapse:

- **execution status**: did the request/tool transport complete?
- **verified outcome**: did an independent verifier establish quality?
- **usage/economics**: what tokens, cost and latency were attributable to the operation?
- **context economics**: what evidence was externalized, granted and reintroduced?

## OpenTelemetry mapping

Use standard `gen_ai.*` semantic conventions for provider/model/token fields. `tokenomics.*` extends them only for experiment identity, verified outcomes, quota and context economics.

The durable JSONL record remains backend-neutral. OTLP/Phoenix/Langfuse are projections, not the source of truth.
