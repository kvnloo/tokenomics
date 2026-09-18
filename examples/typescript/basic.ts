import { makeEvent, MemorySink, Recorder } from "@agent-tokenomics/core";

const sink = new MemorySink();
const recorder = new Recorder(sink);
const trace = crypto.randomUUID().replaceAll("-", "");

await recorder.record(makeEvent({
  kind: "llm",
  name: "omp.root",
  trace_id: trace,
  role: "root",
  status: "ok",
  usage: { input_tokens: 5000, output_tokens: 300, source: "provider" },
}));

await recorder.record(makeEvent({
  kind: "context",
  name: "rlm.search-grants",
  trace_id: trace,
  context: { policy: "rlm-search-grants", spilled_bytes: 100_000, granted_bytes: 4096 },
}));

console.log(sink.events);
