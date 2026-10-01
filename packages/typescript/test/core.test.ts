import assert from "node:assert/strict";
import { test } from "node:test";
import {
  fromKerdoiosObservation,
  fromZ0intReceipt,
  makeEvent,
  normalizeOutcome,
  outcomeTier,
  summarizeTrace,
  rollupTrace,
  assertNoDoubleCount,
  toOtelAttributes,
  treatmentHash,
} from "../src/index.js";

const FIXTURE_HASH = "9977437ebc20cfaa";

test("outcome completion is not gold", () => {
  assert.equal(outcomeTier({ execution_completed: true, success: true }), "execution");
  assert.equal(outcomeTier({ execution_completed: true, verified_success: true, verification_source: "tests" }), "gold");
});

test("ambient close is sanitized", () => {
  const out = normalizeOutcome({ execution_completed: true, test_pass: true, source: "omp_turn_end" });
  assert.equal(outcomeTier(out), "execution");
  assert.match(out.note ?? "", /ambient_close_sanitized/);
});

test("treatment hash agrees with Python fixture", () => {
  assert.equal(treatmentHash({
    model_version: "provider/model@1",
    reasoning_effort: "high",
    system_prompt_hash: "abc",
    skills_hash: null,
    context_policy: "rlm-search-grants",
    tool_schema_hash: "def",
    temperature: 0,
  }), FIXTURE_HASH);
});

test("trace aggregation does not double-count aggregate event", () => {
  const trace = "1".repeat(32);
  const root = makeEvent({ kind: "llm", name: "root", trace_id: trace, role: "root", usage: { input_tokens: 100, output_tokens: 10, attribution: "incremental", source: "provider" } });
  const worker = makeEvent({ kind: "llm", name: "rlm", trace_id: trace, role: "rlm_worker", usage: { input_tokens: 20, output_tokens: 5, attribution: "incremental", source: "provider" } });
  const aggregate = makeEvent({ kind: "task", name: "session", trace_id: trace, usage: { reported_total_tokens: 135, attribution: "aggregate", source: "provider" } });
  const verified = makeEvent({ kind: "verification", name: "tests", trace_id: trace, role: "verifier", outcome: { verified_success: true, verification_source: "tests" } });
  const summary = summarizeTrace([root, worker, aggregate, verified]);
  assert.equal(summary.total_tokens, 135);
  assert.equal(summary.root_tokens, 110);
  assert.equal(summary.worker_tokens, 25);
  assert.equal(summary.reconciliation_delta, 0);
  assert.equal(summary.verified, true);
});

test("trace totals keep partial observations without claiming authority", () => {
  const trace = "2".repeat(32);
  const root = makeEvent({
    kind: "llm",
    name: "root",
    trace_id: trace,
    role: "root",
    usage: { input_tokens: 10, output_tokens: 1, attribution: "incremental", source: "provider" },
    measurement_source: { measurement_state: "partial" },
  });
  const worker = makeEvent({
    kind: "llm",
    name: "worker",
    trace_id: trace,
    role: "rlm_worker",
    usage: { input_tokens: 5, output_tokens: 1, attribution: "incremental", source: "provider" },
    measurement_source: { measurement_state: "complete" },
  });
  const summary = summarizeTrace([root, worker]);
  assert.equal(summary.total_tokens, 17);
  assert.equal(summary.measurement_state, "partial");
  assert.equal(summary.authoritative, false);
});

test("complete trace totals are authoritative while legacy totals remain provisional", () => {
  const completeTrace = "3".repeat(32);
  const complete = makeEvent({
    kind: "llm",
    name: "root",
    trace_id: completeTrace,
    usage: { input_tokens: 10, output_tokens: 1, attribution: "incremental", source: "provider" },
    measurement_source: { measurement_state: "complete" },
  });
  assert.equal(summarizeTrace([complete]).authoritative, true);

  const legacyTrace = "4".repeat(32);
  const legacy = makeEvent({
    kind: "llm",
    name: "root",
    trace_id: legacyTrace,
    usage: { input_tokens: 10, output_tokens: 1, attribution: "incremental", source: "provider" },
  });
  const legacySummary = summarizeTrace([legacy]);
  assert.equal(legacySummary.total_tokens, 11);
  assert.equal(legacySummary.measurement_state, "unknown");
  assert.equal(legacySummary.authoritative, false);
});

test("measurement state is independent from event execution status", () => {
  const event = makeEvent({
    kind: "quota",
    name: "limits.read",
    status: "ok",
    usage: { reported_total_tokens: 42, attribution: "aggregate", source: "provider" },
    measurement_source: {
      logical_source_id: "account-a",
      measurement_state: "partial",
      state_reason: "sparse_runtime_update",
    },
  });
  assert.equal(event.status, "ok");
  assert.equal(event.measurement_source?.measurement_state, "partial");
  assert.equal(toOtelAttributes(event)["tokenomics.measurement.state"], "partial");
  assert.equal(
    toOtelAttributes(event)["tokenomics.measurement.state_reason"],
    "sparse_runtime_update",
  );
});

test("physical measurement identity is explicit across observers", () => {
  const first = makeEvent({
    kind: "llm",
    name: "observer-a",
    measurement_source: {
      observer_id: "runtime-a",
      logical_source_id: "account-a",
      physical_source_id: "host-a:store-1",
      identity_basis: "storage",
    },
  });
  const second = makeEvent({
    kind: "llm",
    name: "observer-b",
    measurement_source: {
      observer_id: "runtime-b",
      logical_source_id: "account-a",
      physical_source_id: "host-a:store-1",
      identity_basis: "storage",
    },
  });
  assert.notEqual(first.measurement_source?.observer_id, second.measurement_source?.observer_id);
  assert.equal(first.measurement_source?.physical_source_id, second.measurement_source?.physical_source_id);
});

test("OTel mapping uses standard GenAI token attributes", () => {
  const event = makeEvent({
    kind: "llm", name: "root", role: "root",
    model: { provider: "openai", name: "gpt-x" },
    usage: { input_tokens: 42, output_tokens: 5, source: "provider" },
    measurement_source: {
      observer_id: "desktop-wsl",
      logical_source_id: "claude-account-a",
      physical_source_id: "host-a:claude-store",
      identity_basis: "storage",
    },
    context: { policy: "rlm-search", granted_bytes: 1024 },
  });
  const attrs = toOtelAttributes(event);
  assert.equal(attrs["gen_ai.usage.input_tokens"], 42);
  assert.equal(attrs["tokenomics.measurement.observer_id"], "desktop-wsl");
  assert.equal(attrs["tokenomics.measurement.logical_source_id"], "claude-account-a");
  assert.equal(attrs["tokenomics.measurement.physical_source_id"], "host-a:claude-store");
  assert.equal(attrs["tokenomics.measurement.identity_basis"], "storage");
  assert.equal(attrs["tokenomics.context.granted_bytes"], 1024);
});

test("legacy adapters preserve key semantics", () => {
  const z = fromZ0intReceipt({ trace_id: "0".repeat(31)+"1", capability_id: "coding.delegate", input_tokens: 10, output_tokens: 2, outcome: { verified_success: true, verification_source: "tests" } });
  assert.equal(z.capability_id, "coding.delegate");
  assert.equal(outcomeTier(z.outcome), "gold");
  const k = fromKerdoiosObservation({ trace_id: "f".repeat(32), provider: "groq", model: "m", task_type: "coding", completed: true, actual_cost: 0, quota_before: 100, quota_after: 90 });
  assert.equal(k.quota_before?.remaining, 100);
  assert.equal(k.quota_after?.remaining, 90);
});

test("frontier rollup separates aggregate reconciliation from incremental usage", () => {
  const trace = "a".repeat(32);
  const root = makeEvent({
    kind: "llm",
    name: "root",
    trace_id: trace,
    harness: "omp",
    role: "root",
    usage: { input_tokens: 80, output_tokens: 20, attribution: "incremental", source: "provider" },
    measurement_source: { measurement_state: "complete" },
    extra: { baseline_total_tokens: 160, measured_frontier_tokens: 100, route: "frontier" },
  });
  const session = makeEvent({
    kind: "task",
    name: "session",
    trace_id: trace,
    usage: { reported_total_tokens: 100, attribution: "aggregate", source: "provider" },
    measurement_source: { measurement_state: "complete" },
  });
  const verified = makeEvent({
    kind: "verification",
    name: "tests",
    trace_id: trace,
    outcome: { verified_success: true, verification_source: "tests" },
  });

  const rollup = rollupTrace([root, session, verified]);
  assert.equal(rollup.actual_frontier_tokens, 100);
  assert.equal(rollup.aggregate_reported, 100);
  assert.equal(rollup.reconciliation_delta, 0);
  assert.equal(rollup.tokens_avoided, 60);
  assert.equal(rollup.savings_tier, "measured");
  assert.equal(rollup.measurement_level, "M3");
  assert.equal(rollup.authoritative, true);
  assert.equal(rollup.verified, true);
  assert.ok(rollup.attribution.includes("omp"));
});

test("prepare events never mint frontier savings", () => {
  const trace = "b".repeat(32);
  const prepared = makeEvent({
    kind: "prepare",
    name: "flow.prepare",
    trace_id: trace,
    economics: {
      prepare_outcome: "prepare_created",
      estimated_tokens_avoided: 500,
    },
  });
  const root = makeEvent({
    kind: "llm",
    name: "root",
    trace_id: trace,
    usage: { input_tokens: 10, output_tokens: 5, attribution: "incremental", source: "provider" },
  });
  const rollup = rollupTrace([prepared, root]);
  assert.equal(rollup.actual_frontier_tokens, 15);
  assert.equal(rollup.tokens_avoided, 0);
  assert.equal(rollup.event_count, 1);
});

test("double-count guard rejects incremental sums above provider aggregate", () => {
  const trace = "c".repeat(32);
  const first = makeEvent({
    kind: "llm",
    name: "root",
    trace_id: trace,
    usage: { reported_total_tokens: 80, attribution: "incremental", source: "provider" },
  });
  const second = makeEvent({
    kind: "llm",
    name: "child",
    trace_id: trace,
    usage: { reported_total_tokens: 40, attribution: "incremental", source: "provider" },
  });
  const aggregate = makeEvent({
    kind: "task",
    name: "provider-total",
    trace_id: trace,
    usage: { reported_total_tokens: 100, attribution: "aggregate", source: "provider" },
  });
  assert.throws(() => assertNoDoubleCount([first, second, aggregate]), /aggregate reported/);
});
