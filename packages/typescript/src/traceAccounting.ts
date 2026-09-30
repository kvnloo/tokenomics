import { outcomeTier } from "./outcome.js";
import { usageTotal, type TokenomicsEvent } from "./types.js";

export type MeasurementLevel = "M0" | "M1" | "M2" | "M3";
export type ActualUsageClass = "incremental" | "aggregate_only" | "unmetered" | "zero_local";
export type BaselineClass = "paired_measured" | "estimated" | "missing";
export type OutcomeClass = "verified" | "negative" | "execution_only" | "unknown";
export type SavingsTier = "measured" | "estimated" | "unknown";

export interface TraceFrontierRollup {
  trace_id: string;
  harness: string;
  measurement_level: MeasurementLevel;
  actual_usage: ActualUsageClass;
  baseline: BaselineClass;
  outcome: OutcomeClass;
  attribution: string[];
  actual_frontier_tokens: number;
  baseline_frontier_tokens?: number;
  tokens_avoided: number;
  savings_tier: SavingsTier;
  incremental_events: number;
  aggregate_reported?: number;
  reconciliation_delta?: number;
  event_count: number;
  verified: boolean;
  measurement_state: string;
  authoritative: boolean;
}

export function isPrepareEvent(event: TokenomicsEvent): boolean {
  return event.kind === "prepare" || Boolean(event.economics?.prepare_outcome);
}

export function isFrontierEvent(event: TokenomicsEvent): boolean {
  return !isPrepareEvent(event);
}

function eventMeasurementState(event: TokenomicsEvent): string {
  return event.measurement_source?.measurement_state ?? "unknown";
}

function aggregateMeasurementState(events: TokenomicsEvent[]): string {
  const states = events.map(eventMeasurementState);
  if (!states.length) return "unknown";
  if (states.includes("failed")) return "failed";
  if (states.includes("partial")) return "partial";
  if (states.includes("unsupported")) {
    return states.every((state) => state === "unsupported") ? "unsupported" : "partial";
  }
  if (states.includes("unknown")) return "unknown";
  return states.every((state) => state === "complete") ? "complete" : "unknown";
}

function hasExplicitIncompleteMeasurement(events: TokenomicsEvent[]): boolean {
  return events.some((event) => {
    const state = event.measurement_source?.measurement_state;
    return state === "partial" || state === "unsupported" || state === "failed";
  });
}

export function incrementalProviderTokens(event: TokenomicsEvent): number {
  if (!event.usage || event.usage.attribution !== "incremental") return 0;
  if (event.usage.source !== "provider" && event.usage.source !== "derived") return 0;
  const reuse = String(event.extra?.reuse_kind ?? "");
  if (reuse === "cache" || reuse === "offline_replay" || reuse === "offline") return 0;
  return usageTotal(event.usage) ?? 0;
}

export function aggregateReportedTokens(event: TokenomicsEvent): number | undefined {
  if (!event.usage || event.usage.attribution !== "aggregate") return undefined;
  return usageTotal(event.usage) ?? 0;
}

function finiteInteger(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.trunc(parsed);
  }
  return undefined;
}

function baselineFromEvent(event: TokenomicsEvent): number | undefined {
  return finiteInteger(event.extra?.baseline_total_tokens);
}

function measuredFrontierFromEvent(event: TokenomicsEvent): number | undefined {
  return finiteInteger(event.extra?.measured_frontier_tokens) ?? event.usage?.reported_total_tokens;
}

function estimatedAvoided(event: TokenomicsEvent): number | undefined {
  if (event.extra?.placement_only || event.kind === "placement") return undefined;
  const value = event.economics?.estimated_tokens_avoided;
  return value !== undefined && Number.isFinite(value) && value > 0 ? Math.trunc(value) : undefined;
}

function route(event: TokenomicsEvent): string {
  return String(event.extra?.route ?? "").toLowerCase();
}

export function mechanismLabels(event: TokenomicsEvent): string[] {
  const labels: string[] = [];
  const harness = String(event.harness ?? "").toLowerCase();
  const capability = String(event.capability_id ?? event.name ?? "").toLowerCase();
  const eventRoute = route(event);
  const provider = String(event.model?.provider ?? "").toLowerCase();

  if (harness === "flow" || event.economics?.prepare_outcome) labels.push("flow_prepare");
  if (harness === "omp" || provider === "omp" || capability.includes("omp")) labels.push("omp");
  if (harness === "hermes" || ["hermes", "nous"].includes(provider) || capability.includes("hermes")) labels.push("hermes");
  if (event.role === "rlm_worker" || capability.includes("rlm") || String(event.extra?.context_policy ?? "").startsWith("rlm")) labels.push("rlm");
  if (["local", "local_model"].includes(eventRoute) || capability.includes("jev") || capability.includes("openjev") || capability.includes("nanojev")) {
    labels.push(capability.includes("nanojev") || provider === "nanojev" ? "nanojev" : capability.includes("openjev") ? "openjev" : "jev");
  }
  if (provider === "local_mb" || capability.includes("local_mb")) labels.push("local_mb");
  if (harness === "kerdoios" || provider === "kerdoios_plan" || event.kind === "placement") labels.push("kerdoios");
  if (eventRoute === "routine" || capability.includes("routine")) labels.push("routine");
  if (capability.includes("compress") || event.context?.policy) labels.push("context");
  if (capability.includes("cache") || (event.usage?.cached_input_tokens ?? 0) > 0) labels.push("cache");
  if (["model", "frontier", "cloud"].includes(eventRoute) || event.model?.provider) labels.push("routing");
  if (!labels.length) labels.push("other");
  return [...new Set(labels)];
}

export function traceOutcomeClass(events: TokenomicsEvent[]): OutcomeClass {
  const tiers = events.filter((event) => event.outcome).map((event) => outcomeTier(event.outcome));
  if (tiers.includes("negative")) return "negative";
  if (tiers.includes("gold")) return "verified";
  if (tiers.includes("execution") || tiers.includes("soft")) return "execution_only";
  return "unknown";
}

export function rollupTrace(events: TokenomicsEvent[]): TraceFrontierRollup {
  if (!events.length) throw new Error("cannot roll up empty trace");
  const rows = events.filter(isFrontierEvent);
  const frontier = rows.length ? rows : events;
  if (new Set(frontier.map((event) => event.trace_id)).size !== 1) {
    throw new Error("requires one trace_id");
  }

  const incremental = frontier.filter((event) => event.usage?.attribution === "incremental");
  const aggregate = frontier
    .filter((event) => event.usage?.attribution === "aggregate")
    .sort((a, b) => a.ts - b.ts);

  let actual = incremental.reduce((sum, event) => sum + incrementalProviderTokens(event), 0);
  const aggregateReported = aggregate.length
    ? aggregateReportedTokens(aggregate.at(-1)!)
    : undefined;
  const reconciliationDelta =
    aggregateReported === undefined ? undefined : aggregateReported - actual;

  if (actual === 0) {
    const measured = frontier
      .map(measuredFrontierFromEvent)
      .filter((value): value is number => value !== undefined);
    if (measured.length) actual = Math.max(...measured);
    else if (frontier.some((event) => ["local", "local_model", "routine", "specialist"].includes(route(event)))) actual = 0;
  }

  let actualUsage: ActualUsageClass;
  if (incremental.some((event) => incrementalProviderTokens(event) > 0)) actualUsage = "incremental";
  else if (incremental.length && actual === 0 && frontier.some((event) => ["local", "local_model"].includes(route(event)))) actualUsage = "zero_local";
  else if (aggregate.length && aggregateReported !== undefined) actualUsage = "aggregate_only";
  else if (actual > 0) actualUsage = "incremental";
  else actualUsage = "unmetered";

  const baselineValues = frontier
    .map(baselineFromEvent)
    .filter((value): value is number => value !== undefined);
  const baselineTotal = baselineValues.length ? Math.max(...baselineValues) : undefined;
  const paired = frontier.some(
    (event) => measuredFrontierFromEvent(event) !== undefined && baselineFromEvent(event) !== undefined,
  );
  const estimatedAvoidedValues = frontier
    .map(estimatedAvoided)
    .filter((value): value is number => value !== undefined);

  let measurementRows = frontier.filter(
    (event) =>
      event.usage !== undefined ||
      measuredFrontierFromEvent(event) !== undefined ||
      baselineFromEvent(event) !== undefined,
  );
  if (!measurementRows.length) measurementRows = frontier;
  const measurementState = aggregateMeasurementState(measurementRows);
  const explicitIncomplete = hasExplicitIncompleteMeasurement(measurementRows);

  let baseline: BaselineClass;
  let tokensAvoided = 0;
  let savingsTier: SavingsTier;
  let measurementLevel: MeasurementLevel;

  if (paired && baselineTotal !== undefined && !explicitIncomplete) {
    baseline = "paired_measured";
    tokensAvoided = Math.max(0, baselineTotal - actual);
    savingsTier = "measured";
    measurementLevel = "M3";
  } else if (estimatedAvoidedValues.length) {
    baseline = baselineTotal !== undefined ? "estimated" : "missing";
    tokensAvoided = Math.max(...estimatedAvoidedValues);
    savingsTier = "estimated";
    measurementLevel = "M1";
  } else if (paired && baselineTotal !== undefined && explicitIncomplete) {
    baseline = "paired_measured";
    savingsTier = "unknown";
    measurementLevel = "M2";
  } else if (baselineTotal !== undefined && ["incremental", "zero_local", "aggregate_only"].includes(actualUsage)) {
    baseline = "missing";
    savingsTier = "unknown";
    measurementLevel = "M2";
  } else {
    baseline = "missing";
    savingsTier = "unknown";
    measurementLevel = actualUsage === "unmetered" ? "M0" : "M2";
  }

  const attribution = [...new Set(frontier.flatMap(mechanismLabels))].sort();
  const outcome = traceOutcomeClass(frontier);

  return {
    trace_id: frontier[0]!.trace_id,
    harness: String(frontier[0]!.harness ?? "unknown"),
    measurement_level: measurementLevel,
    actual_usage: actualUsage,
    baseline,
    outcome,
    attribution,
    actual_frontier_tokens: actual,
    ...(baselineTotal !== undefined ? { baseline_frontier_tokens: baselineTotal } : {}),
    tokens_avoided: tokensAvoided,
    savings_tier: savingsTier,
    incremental_events: incremental.length,
    ...(aggregateReported !== undefined ? { aggregate_reported: aggregateReported } : {}),
    ...(reconciliationDelta !== undefined ? { reconciliation_delta: reconciliationDelta } : {}),
    event_count: frontier.length,
    verified: outcome === "verified",
    measurement_state: measurementState,
    authoritative: measurementState === "complete",
  };
}

export function rollupTraces(events: TokenomicsEvent[]): TraceFrontierRollup[] {
  const groups = new Map<string, TokenomicsEvent[]>();
  for (const event of events) {
    if (isPrepareEvent(event)) continue;
    groups.set(event.trace_id, [...(groups.get(event.trace_id) ?? []), event]);
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([, rows]) => rollupTrace(rows));
}

export function assertNoDoubleCount(events: TokenomicsEvent[]): void {
  const rollup = rollupTrace(events);
  if (rollup.reconciliation_delta !== undefined && rollup.reconciliation_delta < 0) {
    throw new Error(
      `aggregate reported (${rollup.aggregate_reported}) < incremental sum (${rollup.actual_frontier_tokens})`,
    );
  }
}
