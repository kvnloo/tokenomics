# Migration plan

## z0int

Extract semantics, not intelligence.

Move/generalize into Tokenomics:

- receipt/outcome field contracts;
- verified outcome tiers and ambient-close sanitation;
- experiment identity;
- treatment fingerprint;
- JSONL append/join compatibility;
- token/economics fields.

Keep in z0int:

- capability/decision policies;
- training and specialist models;
- counterfactual policy learning;
- routine compilation and decision intelligence.

During migration, call `from_z0int_receipt()` on old rows. New z0int code should eventually emit Tokenomics events directly and may continue exposing DecisionReceipt as a materialized compatibility view.

## Kerdoios

Move/generalize into Tokenomics:

- observed execution event shape;
- generic token/cost/latency dimensions;
- quota snapshot contract;
- trace-level verified economics helpers.

Keep in Kerdoios:

- provider discovery;
- provider-specific header parsing;
- capacity/resource offers;
- pricing and quota interpretation;
- Pareto placement and fallback policy.

`from_kerdoios_observation()` handles the existing observation rows.

## Duplicate receipt checks

The identical copied receipt checker found in z0int/Kerdoios should be replaced with one conformance/check command from this repository once integrations are proven.

## Rollout strategy

1. Dual-write canonical Tokenomics events beside legacy logs.
2. Compare aggregates and exact rows.
3. Switch readers to Tokenomics.
4. Keep legacy adapters for historical logs.
5. Remove copied schemas/helpers from source repos only after parity tests pass.
