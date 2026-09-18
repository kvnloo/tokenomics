# Security and privacy

Agent Tokenomics intentionally does not require prompt, completion, secret, tool-argument, or source-code content.

Applications should treat telemetry as potentially sensitive even when content capture is disabled. Session ids, model names, capability ids and custom attributes may still reveal operational details.

Recommendations:

- keep local JSONL mode `0600`;
- redact custom attributes at the host boundary;
- do not attach credentials or authorization headers;
- use TLS/authentication for remote OTLP exporters;
- preserve authority boundaries when caching or joining traces;
- do not infer that identical content hashes imply identical access authority.
