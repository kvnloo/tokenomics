import { outcomeTier } from "./outcome.js";
import type { TokenomicsEvent } from "./types.js";

export type OtelAttributeValue = string | number | boolean;

function put(out: Record<string, OtelAttributeValue>, key: string, value: unknown): void {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") out[key] = value;
}

export function toOtelAttributes(event: TokenomicsEvent): Record<string, OtelAttributeValue> {
  const out: Record<string, OtelAttributeValue> = {
    "tokenomics.schema": event.schema,
    "tokenomics.event.kind": event.kind,
    "tokenomics.event.id": event.event_id,
    "tokenomics.trace.id": event.trace_id,
    "tokenomics.span.id": event.span_id,
    "tokenomics.execution.role": event.role,
    "tokenomics.status": event.status,
  };
  put(out, "tokenomics.parent_span.id", event.parent_span_id);
  put(out, "tokenomics.session.id", event.session_id);
  put(out, "tokenomics.task.id", event.task_id);
  put(out, "tokenomics.capability.id", event.capability_id);
  put(out, "tokenomics.harness.name", event.harness);
  put(out, "service.name", event.service);
  if (event.model) {
    put(out, "gen_ai.provider.name", event.model.provider);
    put(out, "gen_ai.request.model", event.model.name);
    put(out, "tokenomics.model.role", event.model.role);
    put(out, "tokenomics.provider.origin", event.model.origin_provider);
    put(out, "tokenomics.model.revision", event.model.revision);
  }
  if (event.usage) {
    put(out, "gen_ai.usage.input_tokens", event.usage.input_tokens);
    put(out, "gen_ai.usage.output_tokens", event.usage.output_tokens);
    put(out, "gen_ai.usage.cache_read.input_tokens", event.usage.cached_input_tokens);
    put(out, "gen_ai.usage.cache_creation.input_tokens", event.usage.cache_write_input_tokens);
    put(out, "gen_ai.usage.reasoning.output_tokens", event.usage.reasoning_tokens);
    put(out, "tokenomics.usage.context_tokens", event.usage.context_tokens);
    put(out, "tokenomics.usage.reported_total_tokens", event.usage.reported_total_tokens);
    put(out, "tokenomics.usage.attribution", event.usage.attribution ?? "incremental");
    put(out, "tokenomics.usage.source", event.usage.source ?? "unknown");
  }
  if (event.economics) {
    put(out, "tokenomics.cost.usd", event.economics.cost_usd);
    put(out, "tokenomics.baseline.cost.usd", event.economics.baseline_cost_usd);
    put(out, "tokenomics.price.input_usd_per_million", event.economics.input_price_usd_per_million);
    put(out, "tokenomics.price.output_usd_per_million", event.economics.output_price_usd_per_million);
    put(out, "tokenomics.price.cache_read_usd_per_million", event.economics.cache_read_price_usd_per_million);
    put(out, "tokenomics.price.cache_write_usd_per_million", event.economics.cache_write_price_usd_per_million);
    put(out, "tokenomics.tokens.avoided.estimated", event.economics.estimated_tokens_avoided);
    put(out, "tokenomics.tokens.avoided.measured", event.economics.measured_tokens_avoided);
  }
  if (event.latency) {
    put(out, "tokenomics.latency.duration_ms", event.latency.duration_ms);
    put(out, "gen_ai.response.time_to_first_chunk", event.latency.ttft_ms === undefined ? undefined : event.latency.ttft_ms / 1000);
    put(out, "tokenomics.latency.queue_ms", event.latency.queue_ms);
  }
  if (event.context) for (const [key, value] of Object.entries(event.context)) put(out, `tokenomics.context.${key}`, value);
  for (const [label, quota] of [["before", event.quota_before], ["after", event.quota_after]] as const) {
    if (!quota) continue;
    put(out, `tokenomics.quota.${label}.remaining`, quota.remaining);
    put(out, `tokenomics.quota.${label}.reset_seconds`, quota.reset_seconds);
    put(out, `tokenomics.quota.${label}.remaining_credits`, quota.remaining_credits);
    put(out, `tokenomics.quota.${label}.source`, quota.source);
  }
  if (event.experiment) for (const [key, value] of Object.entries(event.experiment)) put(out, `tokenomics.experiment.${key}`, value);
  if (event.outcome) {
    put(out, "tokenomics.outcome.tier", outcomeTier(event.outcome));
    put(out, "tokenomics.outcome.verification_source", event.outcome.verification_source);
    put(out, "tokenomics.outcome.source", event.outcome.source);
    put(out, "tokenomics.outcome.retries", event.outcome.retries);
  }
  Object.assign(out, event.attributes ?? {});
  return out;
}

/** Structural interface accepted from @opentelemetry/api without making it a hard dependency. */
export interface OtelSpanLike {
  setAttribute(name: string, value: OtelAttributeValue): unknown;
  end(endTime?: unknown): void;
}
export interface OtelTracerLike {
  startSpan(name: string, options?: { startTime?: unknown; attributes?: Record<string, OtelAttributeValue> }): OtelSpanLike;
}

export class OtelSink {
  constructor(readonly tracer: OtelTracerLike) {}
  emit(event: TokenomicsEvent): void {
    const span = this.tracer.startSpan(event.name, { attributes: toOtelAttributes(event) });
    span.end();
  }
}
