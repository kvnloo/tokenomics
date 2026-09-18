# Measurement semantics

## Never equate transport success with task quality

A provider response, tool success, `turn_end`, or agent process exit is an execution signal. It becomes verified quality only when an independent source says so.

Examples of gold signals:

- test/verifier passes;
- CI passes for the claimed change;
- PR merged when merge is the declared verifier;
- explicit `verified_success` with `verification_source`.

Examples of negative signals:

- user correction;
- revert;
- CI failure;
- explicit failed verifier signal.

## Economics denominator

Prefer:

```text
cost_per_verified_task
tokens_per_verified_task
latency_per_verified_task
```

over request-level averages when studying agent/harness value.

## Baselines and experiments

A treatment should identify model, reasoning effort, system prompt hash, skills hash, context policy, tool schema hash and temperature. `treatment_hash()` generates a stable short SHA-256 fingerprint across Python and TypeScript.

Counterfactual fields preserve:

- experiment and pair ids;
- task snapshot id;
- arm id;
- assignment probability;
- replay grade;
- verifier class.

## Context economics

Context-management experiments should record both reduction and reintroduction:

```text
spilled_bytes
selected/granted_bytes
reintroduced_bytes
worker_calls_avoided
missed_evidence_count
unsupported_claim_count
```

A smaller root prompt is not a win if worker inference costs more or retrieval hides necessary evidence.
