# Lineage

This repository extracts a neutral measurement contract from concepts already proven in the author's projects:

- **z0int**: decision receipts, outcome joins, verified-vs-executed semantics, experiment identity, treatment fingerprints, baseline/measured token economics.
- **Kerdoios**: observed execution, model/provider token-cost-latency feedback, quota snapshots, capability-aware economics.
- **OMP RLM experiments**: root-vs-worker token attribution, context bytes spilled/granted/reintroduced, evidence-grounding outcomes.

The extraction deliberately leaves domain policy in the source projects. Tokenomics is the shared measurement layer, not a new router or decision engine.

OpenTelemetry/OTLP is used as the interoperable telemetry projection. Phoenix and Langfuse are optional consumers and are not part of the canonical schema.
