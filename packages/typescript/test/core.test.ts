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

test("OTel mapping uses standard GenAI token attributes", () => {
  const event = makeEvent({
    kind: "llm", name: "root", role: "root",
    model: { provider: "openai", name: "gpt-x" },
    usage: { input_tokens: 42, output_tokens: 5, source: "provider" },
    context: { policy: "rlm-search", granted_bytes: 1024 },
  });
  const attrs = toOtelAttributes(event);
  assert.equal(attrs["gen_ai.usage.input_tokens"], 42);
  assert.equal(attrs["tokenomics.context.granted_bytes"], 1024);
});

test("legacy adapters preserve key semantics", () => {
  const z = fromZ0intReceipt({ trace_id: "0".repeat(31)+"1", capability_id: "coding.delegate", input_tokens: 10, output_tokens: 2, outcome: { verified_success: true, verification_source: "tests" } });
  assert.equal(z.capability_id, "coding.delegate");
  assert.equal(outcomeTier(z.outcome), "gold");
  const k = fromKerdoiosObservation({ trace_id: "f".repeat(32), provider: "groq", model: "m", task_type: "coding", task_id: "w-9", completed: true, actual_cost: 0, request_id: "req-1", started_at: 10, ended_at: 11, fallback_count: 2, quota_before: 100, quota_after: 90 });
  assert.equal(k.quota_before?.remaining, 100);
  assert.equal(k.quota_after?.remaining, 90);
  assert.equal(k.request_id, "req-1");
  assert.equal(k.task_id, "w-9");
  assert.equal(k.started_at, 10);
  assert.equal(k.ended_at, 11);
  assert.equal(k.ts, 11);
  assert.equal(k.economics?.cost_usd, 0);
  assert.equal(k.outcome?.execution_completed, true);
  assert.equal(k.outcome?.verified_success, undefined);
  assert.equal(k.outcome?.retries, 2);
});

test("kerdoios adapter leaves unknown execution and cost unset", () => {
  const k = fromKerdoiosObservation({ trace_id: "e".repeat(32), provider: "cerebras", model: "m" });
  assert.equal(k.status, "unknown");
  assert.equal(k.outcome?.execution_completed, undefined);
  assert.equal(k.outcome?.retries, undefined);
  assert.equal(k.economics, undefined);
});
