export const TOKENOMICS_SCHEMA = "tokenomics.event.v0" as const;

export type EventKind =
  | "task" | "decision" | "llm" | "tool" | "retrieval" | "context"
  | "verification" | "quota" | "placement" | "other";
export type EventStatus = "ok" | "error" | "cancelled" | "unknown";
export type ExecutionRole = "root" | "rlm_worker" | "subagent" | "verifier" | "router" | "other";
export type UsageAttribution = "incremental" | "aggregate" | "unknown";
export type UsageSource = "provider" | "estimated" | "derived" | "unknown";
export type OutcomeTier = "gold" | "negative" | "execution" | "soft" | "unknown";

export interface ModelRef {
  provider?: string;
  name?: string;
  role?: string;
  origin_provider?: string;
  revision?: string;
}

export interface TokenUsage {
  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  cache_write_input_tokens?: number;
  reasoning_tokens?: number;
  context_tokens?: number;
  reported_total_tokens?: number;
  attribution?: UsageAttribution;
  source?: UsageSource;
}

export interface Economics {
  cost_usd?: number;
  baseline_cost_usd?: number;
  input_price_usd_per_million?: number;
  output_price_usd_per_million?: number;
  cache_read_price_usd_per_million?: number;
  cache_write_price_usd_per_million?: number;
  estimated_tokens_avoided?: number;
  measured_tokens_avoided?: number;
}

export interface Latency {
  duration_ms?: number;
  ttft_ms?: number;
  queue_ms?: number;
}

export interface ContextEconomics {
  policy?: string;
  spilled_bytes?: number;
  granted_bytes?: number;
  reintroduced_bytes?: number;
  spill_count?: number;
  retrieval_calls?: number;
  worker_calls_avoided?: number;
  compaction_count?: number;
  citation_count?: number;
  missed_evidence_count?: number;
  unsupported_claim_count?: number;
}

export interface QuotaSnapshot {
  remaining?: number;
  reset_seconds?: number;
  remaining_credits?: number;
  source?: string;
}

export interface Experiment {
  experiment_id?: string;
  pair_id?: string;
  task_snapshot_id?: string;
  arm_id?: string;
  treatment_hash?: string;
  selection_policy?: string;
  assignment_probability?: number;
  reference_requested?: boolean;
  reason_for_reference?: string;
  replay_grade?: string;
  verifier_class?: string;
}

export interface Outcome {
  execution_completed?: boolean;
  verified_success?: boolean;
  verified?: boolean;
  success?: boolean;
  tool_ok?: boolean;
  test_pass?: boolean;
  task_done?: boolean;
  user_correction?: boolean;
  reverted?: boolean;
  verifier_ok?: boolean;
  ci_failed?: boolean;
  pr_merged?: boolean;
  retries?: number;
  note?: string;
  source?: string;
  verification_source?: string;
  tier?: OutcomeTier;
}

export interface TokenomicsEvent {
  schema: typeof TOKENOMICS_SCHEMA;
  kind: EventKind;
  name: string;
  trace_id: string;
  span_id: string;
  event_id: string;
  parent_span_id?: string;
  session_id?: string;
  task_id?: string;
  capability_id?: string;
  harness?: string;
  service?: string;
  role: ExecutionRole;
  status: EventStatus;
  model?: ModelRef;
  usage?: TokenUsage;
  economics?: Economics;
  latency?: Latency;
  context?: ContextEconomics;
  quota_before?: QuotaSnapshot;
  quota_after?: QuotaSnapshot;
  experiment?: Experiment;
  outcome?: Outcome;
  started_at?: number;
  ended_at?: number;
  ts: number;
  attributes?: Record<string, string | number | boolean>;
  extra?: Record<string, unknown>;
}

export function usageTotal(usage?: TokenUsage): number | undefined {
  if (!usage) return undefined;
  if (usage.reported_total_tokens !== undefined) return usage.reported_total_tokens;
  if (usage.input_tokens === undefined && usage.output_tokens === undefined) return undefined;
  return (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0);
}
