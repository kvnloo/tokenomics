from __future__ import annotations

import hashlib
import json
from typing import Any

TREATMENT_FIELDS = (
    "model_version",
    "reasoning_effort",
    "system_prompt_hash",
    "skills_hash",
    "context_policy",
    "tool_schema_hash",
    "temperature",
)


def treatment_hash(**fields: Any) -> str:
    """Stable 16-hex fingerprint for an experiment treatment.

    The canonical payload always contains every known treatment field, using null
    for omitted values. This deliberately matches the z0int receipt semantics.
    """
    payload = {key: fields.get(key) for key in TREATMENT_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
