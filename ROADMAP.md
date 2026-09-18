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
