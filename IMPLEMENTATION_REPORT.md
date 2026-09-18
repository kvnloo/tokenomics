# Agent Tokenomics v0.1.0 implementation report

Commit: `172c6486c7cb47c51e5dca1f3a403aebd1fe8654`

## Implemented

- `tokenomics.event.v0` JSON Schema plus outcome/experiment schemas.
- Python SDK with zero required runtime dependencies.
- TypeScript SDK suitable for OMP/Node/Bun integration.
- Cross-language treatment hashing/conformance fixture.
- Append-only JSONL durability.
- Trace-level aggregation for root/RLM/subagent/verifier usage without double-counting aggregate totals.
- Verified outcome semantics extracted from z0int.
- z0int decision-receipt adapter.
- Kerdoios observed-execution adapter and quota snapshots.
- Standard OTel GenAI attribute mapping plus `tokenomics.*` extensions.
- Optional Python OTLP exporter.
- Structural TypeScript OTel sink with no hard OTel dependency.
- Phoenix + OpenTelemetry Collector local example.
- OMP/RLM integration guidance.
- Migration and experiment-discipline docs.
- CI configuration.

## Validation

- Python: 15 tests passed.
- TypeScript: 6 tests passed.
- Cross-language conformance: passed, treatment hash `9977437ebc20cfaa`.
- TypeScript package dry-run: 24 files, ~23.5 kB unpacked.
- Python editable packaging validated with local build isolation disabled because the execution container has no internet access.
- Docker Compose syntax could not be executed because Docker is not installed in the execution container.

## Intentional exclusions

- no database;
- no dashboard;
- no hosted service;
- no provider routing policy;
- no provider-specific quota parsing;
- no prompt/completion capture by default;
- no automatic quality judge.

## Immediate integration experiment

1. Add TypeScript emission at OMP's canonical provider-usage boundary.
2. Emit RLM context events for spill/search/grant/reintroduction.
3. Reconcile Tokenomics trace totals with OMP session stats.
4. Run native vs RLM real-task experiments and measure tokens/cost per verified task.
5. Dual-write z0int/Kerdoios before removing their legacy receipt/observation helpers.
