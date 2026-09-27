# Tokenomics spec

`tokenomics.event.v0` is the durable domain record. It is intentionally smaller than a full observability product.

The schema distinguishes five concepts that agent harnesses often collapse:

- **execution status**: did the request/tool transport complete?
- **verified outcome**: did an independent verifier establish quality?
- **usage/economics**: what tokens, cost and latency were attributable to the operation?
- **measurement identity**: who observed the measurement, what logical source it represents, and whether an adapter explicitly asserted a physical source safe for dedupe?
- **context economics**: what evidence was externalized, granted and reintroduced?

## OpenTelemetry mapping

Use standard `gen_ai.*` semantic conventions for provider/model/token fields. `tokenomics.*` extends them only for experiment identity, verified outcomes, quota and context economics.

The durable JSONL record remains backend-neutral. OTLP/Phoenix/Langfuse are projections, not the source of truth.


## Measurement source identity

`measurement_source` separates observer, logical source, and physical source identity.

- `observer_id` is the runtime/environment that observed or emitted a record.
- `logical_source_id` is the provider account, quota pool, session, or other domain identity used for grouping.
- `physical_source_id` is an explicit adapter assertion for the underlying measurement source. It is the only generic identity Tokenomics describes as safe for cross-observer dedupe.
- `identity_basis` records how that identity was established (`provider`, `storage`, `operator`, `derived`, or `unknown`).

Missing `physical_source_id` means physical equivalence is unknown, not that the source is unique. Core never infers physical equivalence from matching path strings, hostnames, session/content overlap, or logical source ids. Platform/provider adapters own those assertions.
