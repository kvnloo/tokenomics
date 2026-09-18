# Experiment discipline

Agent Tokenomics is designed for comparisons that can falsify a harness claim.

## Freeze before observing outputs

For benchmark claims, freeze where practical:

- task/source population and inclusion rules;
- task snapshot/hash;
- verifier and success criterion;
- model/provider/revision and reasoning configuration;
- prompt/skills/tool/context-policy treatment hash;
- aggregation rule and denominator.

Do not silently modify a fixture after seeing candidate outputs.

## Preserve strata

Do not pool unrelated populations into one universal accuracy number. Report meaningful task/source/capability strata and denominators. A routing policy may improve one workload and regress another.

## Mechanism versus product evidence

Synthetic needles and deterministic fixtures establish mechanism behavior. They do not prove production coding value.

A product claim should report total system work, including root and worker model calls, retries, latency, cost, and independent task verification.

## Counterfactual identity

Use `Experiment` fields to retain pair/arm/task identity. `treatment_hash` makes model/prompt/context/tool configuration auditable across runs.

## Unknown is not zero

Missing cost, quota, usage or verification must remain unknown. Do not convert missing provider prices or absent verifier signals to zero/success.
