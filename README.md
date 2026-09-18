# Agent Tokenomics

**Vendor-neutral measurement contracts for LLMs, agents, harnesses, context, latency, cost, quota, experiments, and verified outcomes.**

Agent Tokenomics is intentionally not another observability platform. It owns the semantics that generic telemetry systems do not: verified task outcomes, experiment identity, context economics, quota snapshots, and trace-level token accounting. It reuses OpenTelemetry/OTLP for transport and can feed Phoenix, Langfuse, a Collector, or any other OTel backend.

## Why

A request returning `200 OK` does not mean an agent solved the task. A tool call completing does not mean the patch is correct. Root prompt tokens alone do not tell you whether an RLM/context strategy actually saved money.

The canonical measurement unit is a task trace composed of operations:

```text
Task trace
├─ root LLM call
├─ tool / retrieval calls
├─ RLM worker call
├─ subagent calls
└─ verifier outcome
```

From that trace you can compute **tokens per verified task**, **cost per verified task**, context bytes spilled/granted/reintroduced, latency, retries, quota use, and experimental treatment effects.

## Design

```text
OMP / Hermes / z0int / Kerdoios
              │
              ▼
       Tokenomics event v0
        │              │
        ▼              ▼
 append-only JSONL    OTel attributes / OTLP
                        │
                 ┌──────┴──────┐
                 ▼             ▼
              Phoenix       Langfuse
```

- JSONL is the durable offline truth.
- OTel GenAI attributes carry standard provider/model/token fields.
- `tokenomics.*` attributes add verified outcomes, context economics, experiment identity and quota.
- Prompt/completion content is not captured by default.

## Core semantics

### Outcome tiers

| Tier | Meaning |
| --- | --- |
| `gold` | Independent verification exists, such as tests, CI, verifier, merge, or explicit task completion signal. |
| `negative` | Revert, user correction, CI failure, or explicit failed verification. |
| `execution` | Harness/turn completed, but quality was not independently verified. |
| `soft` | Weak legacy signal such as `success=true` or `tool_ok=true`. |
| `unknown` | No quality signal. |

Ambient `turn_end` / `agent_end` events cannot mint gold without a `verification_source`.

### Usage attribution

`TokenUsage.attribution` prevents double counting:

- `incremental`: one operation's usage; summed into task totals.
- `aggregate`: a provider/session total used only for reconciliation.
- `unknown`: retained but not assumed safe to sum.

This lets an OMP trace contain root + RLM worker calls and also a final provider/session usage total without counting both.

## Quick start: Python

```bash
pip install -e '.[test]'
```

```python
from tokenomics import JsonlSink, Outcome, Recorder, TokenUsage, TokenomicsEvent

recorder = Recorder(JsonlSink("~/.local/share/tokenomics/events.jsonl"))

trace_id = "0123456789abcdef0123456789abcdef"
recorder.record(TokenomicsEvent(
    kind="llm",
    name="omp.root",
    trace_id=trace_id,
    role="root",
    status="ok",
    usage=TokenUsage(input_tokens=1200, output_tokens=180, source="provider"),
))
recorder.record(TokenomicsEvent(
    kind="verification",
    name="tests",
    trace_id=trace_id,
    role="verifier",
    status="ok",
    outcome=Outcome(verified_success=True, verification_source="pytest"),
))
```

```bash
tokenomics summary ~/.local/share/tokenomics/events.jsonl
```

## Quick start: TypeScript

```ts
import { makeEvent, MemorySink, Recorder } from "@agent-tokenomics/core";

const sink = new MemorySink();
const recorder = new Recorder(sink);
const trace = "0123456789abcdef0123456789abcdef";

await recorder.record(makeEvent({
  kind: "llm",
  name: "omp.root",
  trace_id: trace,
  role: "root",
  status: "ok",
  usage: { input_tokens: 1200, output_tokens: 180, source: "provider" },
}));
```

## OpenTelemetry / Phoenix

Python has an optional OTLP sink:

```bash
pip install -e '.[otel]'
```

```python
from tokenomics import JsonlSink, MultiSink, OtelSink, Recorder

sink = MultiSink(
    JsonlSink("events.jsonl"),
    OtelSink.from_otlp("http://localhost:4318/v1/traces", service_name="omp"),
)
recorder = Recorder(sink)
```

Start the included local stack:

```bash
docker compose up -d
# Phoenix UI: http://localhost:6006
# OTLP HTTP:  http://localhost:4318
# OTLP gRPC:  localhost:4317
```

The Collector is pinned to the current 0.161.0 release in the example. Phoenix remains replaceable because the application emits OTLP, not Phoenix-specific records.

## Repository layout

```text
spec/                    canonical JSON schemas + tokenomics semantic conventions
packages/python/         dependency-light Python SDK + optional OTLP exporter
packages/typescript/     TypeScript SDK for OMP/Node/Bun harnesses
fixtures/                cross-language and legacy migration fixtures
collector/               local OTLP Collector configuration
examples/                minimal SDK examples
scripts/                 conformance checks
docs/                    architecture and migration guidance
```

## Existing system migration

- **z0int**: `DecisionReceipt`, `Outcome`, experiment identity and treatment fingerprints map into Tokenomics. z0int keeps decision intelligence and training.
- **Kerdoios**: observations, token/cost/latency and quota snapshots map into Tokenomics. Kerdoios keeps provider discovery and placement/routing.
- **OMP/RLM**: emit one incremental event for each root/worker/provider operation plus context events for bytes spilled/granted/reintroduced. Verification is a separate event on the same trace.

See [`docs/MIGRATION.md`](docs/MIGRATION.md) and [`docs/OMP_RLM.md`](docs/OMP_RLM.md).

## Non-goals

- A hosted observability product.
- A replacement for OpenTelemetry, Phoenix or Langfuse.
- Capturing prompts or completions by default.
- Provider routing policy.
- Deciding whether an unverified agent turn was "good".
- Automatically estimating missing prices as zero.

## Status

`v0.1.0` is an extraction-oriented MVP. Schema name remains `tokenomics.event.v0` while integrations are proven in OMP, z0int and Kerdoios.
