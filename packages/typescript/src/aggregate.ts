import { outcomeTier } from "./outcome.js";
import { usageTotal, type TokenomicsEvent } from "./types.js";

export interface TraceSummary {
  trace_id: string;
  event_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cached_input_tokens: number;
  reasoning_tokens: number;
  cost_usd: number;
  verified: boolean;
  outcome_tier: string;
  root_tokens: number;
  worker_tokens: number;
  subagent_tokens: number;
  verifier_tokens: number;
  aggregate_reported_tokens?: number;
  reconciliation_delta?: number;
}

export function summarizeTrace(events: TokenomicsEvent[]): TraceSummary {
  if (!events.length) throw new Error("cannot summarize empty trace");
  if (new Set(events.map(e => e.trace_id)).size !== 1) throw new Error("requires one trace_id");
  const incremental = events.filter(e => e.usage && (e.usage.attribution ?? "incremental") === "incremental");
  const aggregate = events.filter(e => e.usage && e.usage.attribution === "aggregate").sort((a,b) => a.ts-b.ts);
  const total = incremental.reduce((n,e) => n + (usageTotal(e.usage) ?? 0), 0);
  const byRole = (role: string) => incremental.filter(e => e.role === role).reduce((n,e) => n + (usageTotal(e.usage) ?? 0), 0);
  const tiers = events.map(e => outcomeTier(e.outcome));
  const tier = tiers.includes("negative") ? "negative" : tiers.includes("gold") ? "gold" : tiers.includes("execution") ? "execution" : tiers.includes("soft") ? "soft" : "unknown";
  const reported = aggregate.length ? usageTotal(aggregate.at(-1)?.usage) : undefined;
  return {
    trace_id: events[0]!.trace_id,
    event_count: events.length,
    input_tokens: incremental.reduce((n,e) => n + (e.usage?.input_tokens ?? 0), 0),
    output_tokens: incremental.reduce((n,e) => n + (e.usage?.output_tokens ?? 0), 0),
    total_tokens: total,
    cached_input_tokens: incremental.reduce((n,e) => n + (e.usage?.cached_input_tokens ?? 0), 0),
    reasoning_tokens: incremental.reduce((n,e) => n + (e.usage?.reasoning_tokens ?? 0), 0),
    cost_usd: incremental.reduce((n,e) => n + (e.economics?.cost_usd ?? 0), 0),
    verified: tier === "gold",
    outcome_tier: tier,
    root_tokens: byRole("root"),
    worker_tokens: byRole("rlm_worker"),
    subagent_tokens: byRole("subagent"),
    verifier_tokens: byRole("verifier"),
    aggregate_reported_tokens: reported,
    reconciliation_delta: reported === undefined ? undefined : reported-total,
  };
}

export function summarizeTraces(events: TokenomicsEvent[]): TraceSummary[] {
  const by = new Map<string, TokenomicsEvent[]>();
  for (const e of events) by.set(e.trace_id, [...(by.get(e.trace_id) ?? []), e]);
  return [...by.values()].map(summarizeTrace);
}
