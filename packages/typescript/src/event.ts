import { newEventId, newSpanId, newTraceId } from "./ids.js";
import { normalizeOutcome, outcomeTier } from "./outcome.js";
import { TOKENOMICS_SCHEMA, type TokenomicsEvent } from "./types.js";

export type NewEvent = Omit<TokenomicsEvent, "schema" | "trace_id" | "span_id" | "event_id" | "role" | "status" | "ts"> &
  Partial<Pick<TokenomicsEvent, "trace_id" | "span_id" | "event_id" | "role" | "status" | "ts">>;

export function makeEvent(input: NewEvent): TokenomicsEvent {
  const outcome = input.outcome ? normalizeOutcome(input.outcome) : undefined;
  if (outcome) outcome.tier = outcomeTier(outcome);
  const event: TokenomicsEvent = {
    ...input,
    schema: TOKENOMICS_SCHEMA,
    trace_id: input.trace_id ?? newTraceId(),
    span_id: input.span_id ?? newSpanId(),
    event_id: input.event_id ?? newEventId(),
    role: input.role ?? "other",
    status: input.status ?? "unknown",
    ts: input.ts ?? Date.now() / 1000,
    outcome,
  };
  validateEvent(event);
  return event;
}

export function validateEvent(event: TokenomicsEvent): void {
  if (!/^[0-9a-f]{32}$/i.test(event.trace_id)) throw new Error("trace_id must be 32 hex chars");
  if (!/^[0-9a-f]{16}$/i.test(event.span_id) || /^0{16}$/.test(event.span_id)) throw new Error("span_id must be non-zero 16 hex chars");
  if (event.parent_span_id && (!/^[0-9a-f]{16}$/i.test(event.parent_span_id) || /^0{16}$/.test(event.parent_span_id))) throw new Error("invalid parent_span_id");
  if (event.started_at !== undefined && event.ended_at !== undefined && event.ended_at < event.started_at) throw new Error("ended_at cannot precede started_at");
}
