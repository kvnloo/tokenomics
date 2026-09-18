import { createHash } from "node:crypto";

const FIELDS = [
  "model_version", "reasoning_effort", "system_prompt_hash", "skills_hash",
  "context_policy", "tool_schema_hash", "temperature"
] as const;

export type TreatmentFields = Partial<Record<(typeof FIELDS)[number], string | number | null>>;

export function treatmentHash(fields: TreatmentFields = {}): string {
  const payload: Record<string, string | number | null> = {};
  for (const key of [...FIELDS].sort()) payload[key] = fields[key] ?? null;
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex").slice(0, 16);
}
