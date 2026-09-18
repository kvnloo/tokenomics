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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
