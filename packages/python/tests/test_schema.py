import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tokenomics import Experiment, Outcome, TokenomicsEvent

ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "spec/schemas"


def test_event_schema_accepts_sdk_output_with_nested_refs():
    raw_schemas = {}
    for name in ("event.schema.json", "experiment.schema.json", "outcome.schema.json"):
        raw = json.loads((SCHEMAS / name).read_text())
        raw_schemas[name] = raw
    registry = Registry().with_resources(
        [(raw["$id"], Resource.from_contents(raw)) for raw in raw_schemas.values()]
    )
    event = TokenomicsEvent(
        kind="task",
        name="x",
        request_id="req-1",
        experiment=Experiment(experiment_id="e", arm_id="a"),
        outcome=Outcome(verified_success=True, verification_source="tests"),
    )
    Draft202012Validator(raw_schemas["event.schema.json"], registry=registry).validate(event.to_dict())
