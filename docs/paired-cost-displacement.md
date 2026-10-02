# Paired cost-displacement reports

Issue [#20](https://github.com/kvnloo/tokenomics/issues/20) asks whether fewer
frontier tokens represent a measured improvement or move cost elsewhere.
`tokenomics compare-costs study.json` is an offline reporting slice of that study.
It does not run a model, choose a provider, price human attention, or claim causal
credit. It reads only the explicitly supplied local file.

## What is reused, and what is new

Canonical `tokenomics.event.v0` already provides token attribution, experiment
identity, measurement state, and verified-outcome tiers. The report reuses
`incremental_provider_tokens`, `aggregate_measurement_state`, and
`trace_outcome_class`; it does not change the event schema or existing savings
reports. Aggregate token counters remain reconciliation evidence, never an
additional charge. Cached/offline-replay usage is excluded under the existing
physical-token accounting rule.

The new input is a small, versioned **study manifest**, not a second event format.
It pairs existing traces and supplies the cost observations absent from those
receipts. This Python report/CLI emits portable JSON for consumers such as
z0evals. There is no separate TypeScript implementation or duplicated accounting
policy.

## Input: `tokenomics.paired_cost_study.v1`

- `study_id`: nonempty identifier
- `evidence_origin`: `synthetic`, `observed`, `replay`, or `unknown`; missing
  origin remains unknown and cannot establish an improvement
- `baseline_arm`, `treatment_arm`: distinct names
- `work_items`: nonempty frozen cohort of unique `work_item_id` and
  `task_snapshot_id` pairs; use an immutable snapshot reference in real studies
- `runs`: at most one run for each work item and arm, containing:
  - matching `work_item_id`, `task_snapshot_id`, and `arm_id`
  - `revision`: immutable 40- or 64-character lowercase hex revision
  - `events`: one nonempty canonical trace; explicit stable event/trace/span IDs
    and timestamps. Event IDs are unique across the entire study. Any canonical
    experiment ID, arm, or snapshot metadata must agree with the study wrapper
  - `token_measurement_state`: explicit whole-run token coverage using the
    existing complete/partial/unsupported/failed/unknown vocabulary
  - `frontier_event_ids`: explicit unique IDs of incremental usage events
    classified as frontier by the study; Tokenomics does not infer capability
    from a provider name. Missing classification is unknown, not zero
  - `cost_observations`: optional entries from the dimensions below

Supplementary dimensions are `frontier_calls`, `local_compute_ms`,
`wall_time_ms`, `tool_calls`, `network_calls`, `retries`, `replans`, and
`human_interventions`. Each entry has `value`, `measurement_state`,
`attribution: trace_total`, and a nonempty `evidence_ref` linking the observation.
Missing dimensions stay unknown. A complete measurement requires an explicit
nonnegative value, including zero; count dimensions must be integers.

Each supplementary entry is **one total for the entire trace**, including
retries and recovery, not a stream of incremental counters. Instrumentation must
reconcile cumulative/incremental observations before supplying that total. The
report does not sum both kinds or infer missing counters by counting incomplete
logs. A `partial`, `failed`, `unsupported`, or `unknown` numeric value is retained
as `observed_value` but is not an authoritative `value`.

Trace scope is declared by the producer, not independently proven by this
report. Canonical usage must correctly mark aggregate vs incremental events.
Do not duplicate a physical charge under new event IDs or supply an estimated
counter as measured. Event and trace IDs cannot be reused within a study. Hexadecimal trace IDs are
compared case-insensitively; their original spelling remains in the output
provenance.

Outcome classification uses Tokenomics' existing negative-dominates rule. A run
enters the verified-success denominator only with a gold outcome and an explicit
`verification_source` on that positive evidence. An execution-completed event
or a source name attached only to execution evidence cannot supply verification.
The report preserves source identities; it cannot authenticate their independence
or reproduce their underlying quality checks.

Nonzero aggregate-vs-incremental token reconciliation is exposed and makes token
comparisons inconclusive. It is not resolved by choosing whichever number makes
the treatment look cheaper. Conflicting totals tied at the newest aggregate
timestamp are marked ambiguous, independent of input order. Experiment reuse and production-credit lineage are
preserved. Replayed/cached or explicitly ineligible evidence cannot establish a
fresh cost improvement in this report.

## Output: `tokenomics.cost_displacement.v1`

The report includes per-run costs and provenance, matched pair deltas, and
per-arm coverage/denominators. Deltas are **treatment minus baseline**.
No vector is collapsed into a scalar score or a dollar saving.

- `vector_improvement`: both runs verified, every dimension complete, frontier
  tokens decreased, and no measured dimension increased
- `cost_displacement`: both runs verified, frontier tokens decreased, and at
  least one measured dimension increased. Any remaining unknown dimensions are
  still listed; this is a visible tradeoff, not a claim that the intervention is
  better or worse overall
- `no_frontier_reduction`: complete verified pair without lower frontier tokens
- `inconclusive`: missing arm, unverified result, unknown frontier usage, or
  insufficient coverage to claim a vector improvement

A missing run stays in the expected cohort. Arm totals are authoritative only
when every expected work item has a complete observation for that dimension.
`per_verified_success` divides **all cohort cost, including unsuccessful work**,
by the explicit verified-success count; zero successes yields null. Partial
observed totals and measurement coverage remain visible separately.

Wall-time p95/p99 use nearest-rank quantiles over the same cohort, with `n` and
method printed. Missing wall-time observations suppress headline quantiles.
Small samples, including the two-pair fixture, do not support population-tail
claims. Local compute time is a separately instrumented quantity, not a sum of
possibly overlapping wall durations. Human interventions remain unpriced counts.

Output carries its evidence origin, uses `synthetic_example` for synthetic data
and `paired_observational` otherwise, and always has `causal_claim: false`. It does
not control assignment, leakage, workload difficulty, or an independent verifier.
Those are required before a real study makes stronger causal claims.

## Reproducible synthetic example

```bash
python -m tokenomics.cli compare-costs fixtures/paired-cost-study.json
python -m pytest packages/python/tests/test_cost_displacement.py
```

Python consumers can call `build_cost_displacement_report(study)` from
`tokenomics.cost_displacement`; z0evals can consume the versioned JSON directly.

The fixture is entirely synthetic. Its `savings` pair lowers frontier/total
model tokens from 1,000 to 400 with no increased dimension; its `displacement`
pair shows the same token reduction alongside 600 ms local compute, increased
wall time, one retry, and one human intervention. It demonstrates interpretation,
not achieved savings in a real system.

A real follow-up study must supply paired measurements over a frozen cohort,
review each telemetry scope and verifier, and retain negative/inconclusive
pairs. This implementation deliberately does not close the empirical study.
