
from tokenomics import from_bespoke_curation


def test_accepted_is_not_verified_success():
    e = from_bespoke_curation(
        {
            "trace_id": "0123456789abcdef0123456789abcdef",
            "accepted": True,
            "pair_id": "pair-1",
            "source_family_id": "project_status",
            "intervention_kind": "relevant_edit",
            "supervision_kind": "deterministic",
            "input_tokens": 100,
            "output_tokens": 10,
            "cost_usd": 0.01,
            "reuse_kind": "fresh",
            "pair_pass": True,
        }
    )
    assert e.kind == "curation"
    assert e.outcome is not None
    assert e.outcome.verified_success is None
    assert e.outcome.tier() != "gold"
    assert e.experiment is not None
    assert e.experiment.production_credit_eligible is False
    assert e.experiment.contrast_group_id == "pair-1"
    assert e.economics and e.economics.cost_usd == 0.01


def test_cache_reuse_does_not_charge():
    e = from_bespoke_curation(
        {
            "trace_id": "0123456789abcdef0123456789abcdef",
            "accepted": True,
            "cost_usd": 0.01,
            "input_tokens": 50,
            "reuse_kind": "cache",
            "original_event_ref": "evt-1",
        }
    )
    assert e.economics is None or e.economics.cost_usd is None
    assert e.usage is None or e.usage.source == "derived"
