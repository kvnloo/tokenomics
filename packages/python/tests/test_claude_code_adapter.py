import json
from pathlib import Path

from tokenomics.report import _coerce_event, build_savings_report, classify_savings

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "fixtures/claude_code_turn.json").read_text())


def test_legacy_claude_code_rows_are_no_longer_dropped():
    ev = _coerce_event(FIXTURE["legacy_row"])
    assert ev is not None and ev.harness == "claude-code" and ev.role == "subagent"
    assert ev.usage.input_tokens == 2414 and ev.usage.cached_input_tokens == 2200
    assert ev.usage.cache_write_input_tokens == 200 and ev.usage.source == "provider"
    assert ev.extra["anthropic_usage"]["input_tokens"] == 14
    # deterministic ids from the legacy 64-hex trace id
    assert ev.trace_id == FIXTURE["legacy_row"]["trace_id"][:32]
    assert _coerce_event(FIXTURE["legacy_row"]).span_id == ev.span_id
    ms = ev.measurement_source
    assert ms.physical_source_id is None and ms.identity_basis == "derived"
    assert ms.logical_source_id.endswith(":agent-a.jsonl") and ms.measurement_state == "complete"
    # no timestamp in legacy rows: never placed in "now"
    assert ev.ts == 0.0 and ev.extra["ts_missing"] is True
    assert build_savings_report([ev], range_spec="7d")["n_events"] == 0
    assert build_savings_report([ev], range_spec="all")["totals"]["actual_frontier_tokens"] == 2480


def test_canonical_claude_code_event_roundtrips():
    ev = _coerce_event(FIXTURE["canonical_event"])
    assert ev.to_dict()["usage"] == FIXTURE["canonical_event"]["usage"]
    assert classify_savings(ev)[0] == "unknown"  # observed usage alone claims no savings


def receipt(**extra):
    return {
        "schema": "z0int.decision_receipt.v1",
        "trace_id": "ef03423eeaa84d50bf8890a6dd8a3620",
        "capability_id": "codex.delegated_text",
        "provider": "groot",
        "model": "qwen3-8b-q4km",
        "route": "model",
        "input_tokens": 196,
        "output_tokens": 2,
        "baseline_input_tokens": 226,
        "baseline_output_tokens": 3,
        "estimated_frontier_tokens_avoided": 229,
        "measured_frontier_tokens": 0,
        "extra": extra,
    }


def test_estimated_worker_baseline_is_not_measured():
    ev = _coerce_event(receipt(baseline={"model": "codex-parent", "method": "ceil_utf8_bytes_div_4_v1"}))
    tier, _, _, avoided = classify_savings(ev)
    assert (tier, avoided) == ("estimated", 229)
    assert ev.extra["estimated_baseline_total_tokens"] == 229
    assert ev.extra["baseline_method"] == "ceil_utf8_bytes_div_4_v1"
    assert ev.economics.measured_tokens_avoided is None


def test_measured_or_unlabelled_baseline_keeps_measured_tier():
    assert classify_savings(_coerce_event(receipt()))[0] == "measured"
    paired = receipt(baseline={"method": "paired_ab_v1", "kind": "paired"})
    assert classify_savings(_coerce_event(paired))[0] == "measured"
