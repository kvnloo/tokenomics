import json
from pathlib import Path

from tokenomics import treatment_hash

ROOT = Path(__file__).resolve().parents[3]


def test_treatment_hash_fixture():
    fixture = json.loads((ROOT / "fixtures/conformance.json").read_text())
    assert treatment_hash(**fixture["treatment"]) == fixture["expected_treatment_hash"]


def test_hash_is_key_order_independent():
    a = treatment_hash(model_version="a", context_policy="b")
    b = treatment_hash(context_policy="b", model_version="a")
    assert a == b
