# Curation lineage (optional Bespoke)

Tokenomics stays dependency-free. Bespoke/Curator is an **optional producer**.

## Hard rule

```text
curation.accepted = true
    ≠
outcome.verified_success = true
```

Synthetic construction checks are not live agent-task success.

## Reuse

| reuse_kind     | provider cost | usage source |
|----------------|---------------|--------------|
| fresh          | counted       | provider     |
| cache          | not recounted | derived      |
| offline_replay | not recounted | derived      |

## Importer

```python
from tokenomics import from_bespoke_curation
event = from_bespoke_curation(record)
assert event.outcome.verified_success is None
assert event.experiment.production_credit_eligible is False
```
