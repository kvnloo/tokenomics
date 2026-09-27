import assert from "node:assert/strict";
import { test } from "node:test";
import {
  fromKerdoiosObservation,
  fromZ0intReceipt,
  makeEvent,
  normalizeOutcome,
  outcomeTier,
  summarizeTrace,
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

test("measurement completeness is independent of execution status", () => {
  const event = makeEvent({
    kind: "quota",
    name: "partial-read",
    status: "ok",
    measurement: { completeness: "partial", reason: "one transcript unreadable" },
  });
  assert.equal(event.status, "ok");
  assert.equal(event.measurement?.completeness, "partial");
  const attrs = toOtelAttributes(event);
  assert.equal(attrs["tokenomics.measurement.completeness"], "partial");
  assert.equal(attrs["tokenomics.measurement.reason"], "one transcript unreadable");
});

test("unsupported and failed measurements remain distinct", () => {
  const unsupported = makeEvent({ kind: "quota", name: "unsupported", measurement: { completeness: "unsupported" } });
  const failed = makeEvent({ kind: "quota", name: "failed", measurement: { completeness: "failed" } });
  assert.notEqual(unsupported.measurement?.completeness, failed.measurement?.completeness);
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
