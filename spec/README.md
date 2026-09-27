# Tokenomics spec

`tokenomics.event.v0` is the durable domain record. It is intentionally smaller than a full observability product.

The schema distinguishes six concepts that agent harnesses often collapse:

- **execution status**: did the request/tool transport complete?
- **verified outcome**: did an independent verifier establish quality?
- **usage/economics**: what tokens, cost and latency were attributable to the operation?
- **measurement identity**: who observed the measurement, what logical source it represents, and whether an adapter explicitly asserted a physical source safe for dedupe?
- **measurement completeness**: whether the declared measurement scope is complete, partial, unsupported, failed, or unknown?
- **context economics**: what evidence was externalized, granted and reintroduced?

## OpenTelemetry mapping

Use standard `gen_ai.*` semantic conventions for provider/model/token fields. `tokenomics.*` extends them only for experiment identity, verified outcomes, quota and context economics.

The durable JSONL record remains backend-neutral. OTLP/Phoenix/Langfuse are projections, not the source of truth.


## Measurement source identity

`measurement_source` separates observer, logical source, and physical source identity.

- `observer_id` is the runtime/environment that observed or emitted a record.
- `logical_source_id` is the provider account, quota pool, session, or other domain identity used for grouping. Prefer a stable provider-native opaque id when one exists; do not substitute email addresses, plan names, organization display names, or other mutable labels.
- `physical_source_id` is an explicit adapter assertion for the underlying measurement source. It is the only generic identity Tokenomics describes as safe for cross-observer dedupe.
- `identity_basis` records how that identity was established (`provider`, `storage`, `operator`, `derived`, or `unknown`).

Missing `physical_source_id` means physical equivalence is unknown, not that the source is unique. Core never infers physical equivalence from matching path strings, hostnames, session/content overlap, or logical source ids. Platform/provider adapters own those assertions.


### Logical source identity rules

`logical_source_id` is grouping identity, not display metadata.

- Prefer provider-native stable ids such as a workspace/account UUID.
- Scope ids by provider/domain in the adapter so unrelated providers cannot collide.
- Email, plan/tier names, organization names, and model-provider labels are fallback evidence, not durable logical ids.
- Two observations with the same email but different stable logical ids are different sources.
- A missing logical id means identity is unresolved; it must not be guessed from a mutable label.
- Adapters may keep display metadata separately in attributes or provider-native fields.

For example, an adapter may map a ChatGPT workspace account id or an Anthropic organization UUID into `logical_source_id`, while retaining the email/plan/org name only for display. Tokenomics core does not define provider-specific extraction logic.


## Measurement completeness

`measurement.completeness` is categorical provenance about coverage, not execution status and not a probability.

- `complete`: the producer asserts the declared measurement scope was fully observed.
- `partial`: usable evidence exists, but some declared scope is missing, unreadable, rejected, or otherwise incomplete.
- `unsupported`: the source cannot produce this measurement by capability or contract.
- `failed`: the source should be able to produce the measurement, but this observation attempt failed.
- `unknown`: completeness has not been established.

Hard invariants:

- `status: "ok"` does not imply `measurement.completeness: "complete"`.
- Missing completeness means unknown, never complete.
- Failed measurements are not zero-valued measurements.
- Unsupported measurements are not failed probes.
- A partial observation may carry useful counters, but downstream merges, caches, and replays must preserve its partial state unless a later complete observation replaces it.
- A derived or cached observation must not upgrade completeness without evidence covering the missing scope.
