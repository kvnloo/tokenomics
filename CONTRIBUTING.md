# Contributing

Keep the project small and backend-neutral.

## Design rules

1. Prefer OpenTelemetry semantic conventions for concepts OTel already defines.
2. Add `tokenomics.*` only for semantics needed by verified agent/harness economics.
3. Do not add a database, hosted service, dashboard, provider router, or prompt store to core.
4. Preserve JSONL compatibility and schema-versioned adapters.
5. A new metric needs a clear denominator and attribution rule.
6. Execution success must never silently become verified task success.

## Checks

```bash
PYTHONPATH=packages/python/src pytest -q
cd packages/typescript && tsc -p tsconfig.json && node --test dist/test/*.test.js
PYTHONPATH=packages/python/src python scripts/check_conformance.py
```
