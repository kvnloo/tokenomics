# Roadmap

## v0.1: contract extraction

- canonical event/outcome/experiment schemas;
- Python and TypeScript SDKs;
- append-only JSONL;
- OTel GenAI mapping and optional OTLP export;
- z0int/Kerdoios adapters;
- trace-level verified economics;
- Phoenix/Collector local example.

## Validation before v0.2

1. Instrument OMP root model calls and RLM worker calls.
2. Reconcile Tokenomics totals with OMP's existing session/provider usage.
3. Dual-write z0int receipts and compare outcome/token aggregates.
4. Dual-write Kerdoios observations and compare placement feedback aggregates.
5. Run native-vs-RLM real-task experiments using cost/tokens per verified task.

## Only after parity

- move copied receipt/outcome helpers out of source repos;
- add richer latency distributions if real traces need them;
- add a Langfuse/Phoenix experiment adapter only if OTLP + custom attributes is insufficient;
- propose stable `tokenomics.*` semantic conventions from observed integrations.

## v0.2: savings report contract (T0)

- `tokenomics.report.v1` aggregator with **measured / estimated / unknown** tiers (never collapsed);
- CLI: `tokenomics savings --range today|7d|30d|all [--json]` and `tokenomics report`;
- default sources: `~/.z0int/receipts` + tokenomics JSONL;
- quality-adjusted metric: tokens / verified success.

## After T0 (not in-core UI)

- T1: AgentTrace native Tokenomics parser + Savings TUI/HTML;
- T2: optional `tokenomics-web` consuming only `tokenomics.report.v1`.
