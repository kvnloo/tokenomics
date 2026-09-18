import json
from pathlib import Path

from tokenomics import from_kerdoios_observation, from_z0int_receipt

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    return json.loads((ROOT / "fixtures" / name).read_text())


def test_z0int_adapter_preserves_verification_and_usage():
    e = from_z0int_receipt(load("z0int_receipt.json"))
    assert e.trace_id == "0123456789abcdef0123456789abcdef"
    assert e.outcome and e.outcome.tier() == "gold"
    assert e.usage and e.usage.total() == 1200
    assert e.experiment and e.experiment.arm_id == "search-grants"


def test_kerdoios_adapter_preserves_quota_and_cost():
    e = from_kerdoios_observation(load("kerdoios_observation.json"))
    assert e.model and e.model.provider == "cerebras"
    assert e.quota_before and e.quota_before.remaining == 60000
    assert e.quota_after and e.quota_after.remaining == 59050
    assert e.economics and e.economics.cost_usd == 0.002
