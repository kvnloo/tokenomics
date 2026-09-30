from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/python/src"))

from tokenomics import treatment_hash  # noqa: E402


def main() -> int:
    fixture = json.loads((ROOT / "fixtures/conformance.json").read_text())
    expected = fixture["expected_treatment_hash"]
    actual = treatment_hash(**fixture["treatment"])
    if actual != expected:
        print(f"python treatment hash mismatch: {actual} != {expected}", file=sys.stderr)
        return 1

    ts = ROOT / "packages/typescript/dist/src/experiment.js"
    if ts.exists():
        js = (
            "import { treatmentHash } from '" + ts.as_uri() + "';"
            "console.log(treatmentHash(" + json.dumps(fixture["treatment"]) + "));"
        )
        proc = subprocess.run(["node", "--input-type=module", "-e", js], text=True, capture_output=True)
        if proc.returncode != 0:
            print(proc.stderr, file=sys.stderr)
            return proc.returncode
        got = proc.stdout.strip()
        if got != expected:
            print(f"typescript treatment hash mismatch: {got} != {expected}", file=sys.stderr)
            return 1
    print(f"ok: cross-language treatment hash {expected}")
    return check_claude_code_fixture()


def check_claude_code_fixture() -> int:
    """Canonical Claude Code turn events and legacy rows map to the same usage."""
    from tokenomics.models import TokenomicsEvent
    from tokenomics.report import _coerce_event

    fixture = json.loads((ROOT / "fixtures/claude_code_turn.json").read_text())
    canonical = fixture["canonical_event"]
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("skip: jsonschema not installed; claude-code event schema check skipped", file=sys.stderr)
    else:
        schema = json.loads((ROOT / "spec/schemas/event.schema.json").read_text())
        errors = [e.message for e in Draft202012Validator(schema).iter_errors(canonical)]
        if errors:
            print(f"claude-code canonical event violates event schema: {errors}", file=sys.stderr)
            return 1
    roundtrip = TokenomicsEvent.from_dict(canonical).to_dict()
    if roundtrip["usage"] != canonical["usage"]:
        print("claude-code canonical event does not round-trip", file=sys.stderr)
        return 1
    legacy = _coerce_event(fixture["legacy_row"])
    if legacy is None:
        print("legacy claude-code.provider_usage.v0 row is not recognized", file=sys.stderr)
        return 1
    got = {k: getattr(legacy.usage, k) for k in fixture["expected_legacy_usage"]}
    if got != fixture["expected_legacy_usage"]:
        print(f"legacy claude-code usage mismatch: {got}", file=sys.stderr)
        return 1
    print("ok: claude-code turn event (canonical + legacy) conforms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
