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
        experiment=Experiment(
            experiment_id="e",
            arm_id="a",
            parent_example_id="parent-1",
            contrast_group_id="contrast-1",
            source_family_id="family-1",
            intervention_kind="relevant_edit",
            supervision_kind="model_checked_synthetic",
            acceptance_status="accepted",
            rejection_stage="gate-2",
            gate_revision="rev-1",
            reuse_kind="offline_replay",
            original_event_ref="event-1",
            evaluation_cohort="cohort-1",
            production_credit_eligible=False,
        ),
        outcome=Outcome(verified_success=True, verification_source="tests"),
    )
    Draft202012Validator(raw_schemas["event.schema.json"], registry=registry).validate(event.to_dict())
