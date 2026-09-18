import { makeEvent } from "./event.js";
import { newTraceId } from "./ids.js";
import type { Outcome, TokenomicsEvent } from "./types.js";

function normalizeTrace(value: unknown): string {
  const text = String(value ?? "").replaceAll("-", "").toLowerCase();
  return /^[0-9a-f]{32}$/.test(text) ? text : newTraceId();
}

export function fromZ0intReceipt(raw: Record<string, unknown>): TokenomicsEvent {
  const extra = typeof raw.extra === "object" && raw.extra !== null ? raw.extra as Record<string, unknown> : {};
  const expKeys = ["experiment_id","pair_id","task_snapshot_id","arm_id","treatment_hash","selection_policy","assignment_probability","reference_requested","reason_for_reference","replay_grade","verifier_class"];
  const experiment: Record<string, unknown> = {};
  for (const key of expKeys) if (raw[key] !== undefined || extra[key] !== undefined) experiment[key] = raw[key] ?? extra[key];
  return makeEvent({
    kind: "decision",
    name: String(raw.capability_id ?? raw.action_taken ?? "z0int.decision"),
    trace_id: normalizeTrace(raw.trace_id),
    session_id: raw.session_id as string | undefined,
    capability_id: raw.capability_id as string | undefined,
    harness: "z0int",
    role: "router",
    status: raw.outcome_tier === "negative" ? "error" : "ok",
    model: { provider: raw.provider as string | undefined, name: raw.model as string | undefined },
    usage: {
      input_tokens: raw.input_tokens as number | undefined,
      output_tokens: raw.output_tokens as number | undefined,
      cached_input_tokens: raw.cached_input_tokens as number | undefined,
      reported_total_tokens: raw.measured_frontier_tokens as number | undefined,
      attribution: "incremental",
      source: raw.measured_frontier_tokens === undefined ? "unknown" : "provider",
    },
    economics: {
      estimated_tokens_avoided: raw.estimated_frontier_tokens_avoided as number | undefined,
      measured_tokens_avoided: raw.actual_tokens_saved as number | undefined,
    },
    latency: { duration_ms: raw.latency_ms as number | undefined },
    experiment: Object.keys(experiment).length ? experiment : undefined,
    outcome: raw.outcome as Outcome | undefined,
  });
}

export function fromKerdoiosObservation(raw: Record<string, unknown>): TokenomicsEvent {
  return makeEvent({
    kind: "placement",
    name: String(raw.capability_id ?? raw.task_type ?? "kerdoios.placement"),
    trace_id: normalizeTrace(raw.trace_id),
    session_id: raw.session_id as string | undefined,
    capability_id: raw.capability_id as string | undefined,
    harness: "kerdoios",
    role: "router",
    status: raw.completed ? "ok" : "error",
    model: { provider: raw.provider as string | undefined, origin_provider: raw.origin_provider as string | undefined, name: raw.model as string | undefined },
    usage: {
      input_tokens: raw.input_tokens as number | undefined,
      output_tokens: raw.output_tokens as number | undefined,
      cached_input_tokens: raw.cached_input_tokens as number | undefined,
      context_tokens: raw.context_tokens as number | undefined,
      attribution: "incremental",
      source: "provider",
    },
    economics: { cost_usd: Number(raw.actual_cost ?? 0) },
    latency: { duration_ms: raw.latency_ms as number | undefined },
    quota_before: raw.quota_before === undefined ? undefined : { remaining: Number(raw.quota_before), source: raw.remaining_source as string | undefined },
    quota_after: (raw.quota_after ?? raw.remaining_quota) === undefined ? undefined : { remaining: Number(raw.quota_after ?? raw.remaining_quota), source: raw.remaining_source as string | undefined },
    outcome: { execution_completed: Boolean(raw.completed), success: Boolean(raw.completed), source: "kerdoios_observed" },
  });
}
