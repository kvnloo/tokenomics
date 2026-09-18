# OMP / RLM integration

The immediate OMP experiment is **whole-session accounting**, not a new analytics system inside `RlmStore`.

## Trace topology

Use one task/session experiment trace:

```text
trace
├─ root LLM operation        role=root
├─ RLM retrieval/context     kind=retrieval/context
├─ RLM query/subcall         role=rlm_worker
├─ subagent calls            role=subagent
└─ test/verifier outcome     role=verifier
```

## Root and worker usage

Emit provider-reported model usage as `attribution=incremental` for each actual provider operation. If OMP also exposes a session/provider total, record it as `attribution=aggregate`; aggregation uses it for reconciliation, not summation.

This directly measures:

```text
total_task_tokens = root + RLM workers + subagents + verifier model calls
```

without counting a session-total event twice.

## RLM context fields

A context/retrieval event can carry:

```text
context.policy = rlm-search-grants
spilled_bytes
spill_count
retrieval_calls
granted_bytes
reintroduced_bytes
worker_calls_avoided
missed_evidence_count
unsupported_claim_count
```

The last two should be populated only when a deterministic/manual verifier exists.

## Experiment arms

For the current RLM A/B/C work:

- A: native OMP;
- B: fixed 8 KiB grant;
- C: search-driven grants.

Use the same `experiment_id`, a shared `task_snapshot_id`, distinct `arm_id`, and a `treatment_hash` that includes `context_policy`.

## Minimal TypeScript integration

OMP does not need Phoenix as a dependency. It needs only the TypeScript SDK plus a local sink or adapter into OMP's existing telemetry path.

Recommended sequence:

1. map OMP's canonical provider usage into `TokenomicsEvent`;
2. map RLM store counters into context events;
3. append local JSONL or feed existing telemetry;
4. add OTel export only at the existing telemetry boundary;
5. verify trace totals reconcile with current `/session` or stats usage.
