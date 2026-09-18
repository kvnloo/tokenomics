import type { Outcome, OutcomeTier } from "./types.js";

const GOLD_SIGNALS = ["verified_success", "verified", "test_pass", "verifier_ok", "pr_merged", "task_done"] as const;
const NEGATIVE_TRUE = ["user_correction", "reverted", "ci_failed"] as const;
const AMBIENT = new Set(["bridge_turn_end", "bridge_agent_end", "bridge_agent_start", "omp_turn_end", "omp_agent_end", "close_turn"]);

export function normalizeOutcome(input: Outcome): Outcome {
  const out: Outcome = { ...input };
  const source = out.source ?? "";
  const ambient = AMBIENT.has(source) || (source.startsWith("bridge_") && source !== "bridge_manual" && source !== "bridge_verified");
  if (ambient && !out.verification_source) {
    for (const key of GOLD_SIGNALS) if (out[key] === true) delete out[key];
    if (out.execution_completed !== false) out.execution_completed = true;
    if (!out.note) out.note = "ambient_close_sanitized";
    else if (!out.note.includes("ambient_close_sanitized")) out.note += "|ambient_close_sanitized";
  }
  return out;
}

export function outcomeTier(input?: Outcome): OutcomeTier {
  if (!input) return "unknown";
  const out = normalizeOutcome(input);
  if (NEGATIVE_TRUE.some(k => out[k] === true) || GOLD_SIGNALS.some(k => out[k] === false)) return "negative";
  if (GOLD_SIGNALS.some(k => out[k] === true)) return "gold";
  if (out.execution_completed === true) return "execution";
  if (out.success === true || out.tool_ok === true) return "soft";
  return "unknown";
}
