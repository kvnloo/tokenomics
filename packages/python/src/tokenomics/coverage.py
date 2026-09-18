"""tokenomics.coverage.v1 — whole-system measurement coverage (not savings)."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .gap_priority import capability_by_trace_from_events, gaps_for_autoresearch, rank_measurement_gaps
from .models import TokenomicsEvent
from .report import build_savings_report, default_sources, load_events_from_paths, parse_range
from .trace_accounting import TraceFrontierRollup, is_prepare_event, rollup_traces

COVERAGE_SCHEMA = "tokenomics.coverage.v1"


def _pct(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den, 4)


def _trace_rows(rollups: list[TraceFrontierRollup]) -> list[dict[str, Any]]:
    rows = []
    for r in rollups:
        rows.append(
            {
                "trace_id": r.trace_id,
                "measurement_level": r.measurement_level,
                "actual_usage": r.actual_usage,
                "baseline": r.baseline,
                "outcome": r.outcome,
                "attribution": list(r.attribution),
                "harness": r.harness,
                "actual_frontier_tokens": r.actual_frontier_tokens,
                "baseline_frontier_tokens": r.baseline_frontier_tokens,
                "tokens_avoided": r.tokens_avoided,
                "savings_tier": r.savings_tier,
                "verified": r.verified,
            }
        )
    return rows


def _by_mechanism(rollups: list[TraceFrontierRollup]) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rollups:
        for m in r.attribution:
            counts[m]["traces"] += 1
            if r.verified:
                counts[m]["verified"] += 1
            if r.baseline == "paired_measured":
                counts[m]["paired_baseline"] += 1
            elif r.baseline == "estimated":
                counts[m]["estimated_baseline"] += 1
            if r.actual_usage in {"incremental", "zero_local"}:
                counts[m]["metered"] += 1
    out = []
    for mech, c in sorted(counts.items(), key=lambda kv: -kv[1]["traces"]):
        n = c["traces"]
        out.append(
            {
                "mechanism": mech,
                "traces": n,
                "verified_traces": c["verified"],
                "metered_traces": c["metered"],
                "paired_baseline_traces": c["paired_baseline"],
                "estimated_baseline_traces": c["estimated_baseline"],
                "baseline_coverage": _pct(c["paired_baseline"] + c["estimated_baseline"], n),
            }
        )
    return out


def build_coverage_report(
    events: Iterable[TokenomicsEvent],
    *,
    range_spec: str = "7d",
    now: float | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    start, end = parse_range(range_spec, now=now)
    rows = [e for e in events if start <= float(e.ts or 0) <= end]
    rollups = rollup_traces(rows)
    n_traces = len(rollups)

    physical = Counter({k: 0 for k in ("incremental", "aggregate_only", "unmetered", "zero_local")})
    baseline = Counter({k: 0 for k in ("paired_measured", "estimated", "missing")})
    outcome = Counter({k: 0 for k in ("verified", "negative", "execution_only", "unknown")})
    levels = Counter({k: 0 for k in ("M0", "M1", "M2", "M3")})

    for r in rollups:
        physical[r.actual_usage] += 1
        baseline[r.baseline] += 1
        outcome[r.outcome] += 1
        levels[r.measurement_level] += 1

    cap_map = capability_by_trace_from_events(rows)
    gaps = gaps_for_autoresearch(rollups, capability_by_trace=cap_map, limit=24)

    # Flow lane — separate economic lane, never token savings
    prepare_events = [e for e in rows if is_prepare_event(e)]
    savings = build_savings_report(rows, range_spec=range_spec, now=now, sources=sources or [])
    pf = savings.get("prepare_funnel") or {}

    accounting = {
        "rule": (
            "actual_frontier_tokens = SUM(incremental provider usage); "
            "tokens_avoided = baseline - actual per trace; "
            "mechanisms are attribution labels only."
        ),
        "incremental_only_for_physical_totals": True,
        "aggregate_reconciliation_only": True,
    }

    return {
        "schema": COVERAGE_SCHEMA,
        "range": range_spec,
        "period": {
            "start_ts": start,
            "end_ts": end,
            "start_iso": datetime.fromtimestamp(start, tz=timezone.utc).isoformat() if start > 0 else None,
            "end_iso": datetime.fromtimestamp(end, tz=timezone.utc).isoformat(),
        },
        "sources": sources or [],
        "n_events": len(rows),
        "n_traces": n_traces,
        "traces": _trace_rows(rollups),
        "measurement_levels": dict(levels),
        "physical_usage": {
            "incremental_provider_metered": physical["incremental"],
            "zero_local": physical["zero_local"],
            "aggregate_only": physical["aggregate_only"],
            "unmetered": physical["unmetered"],
            "coverage_pct": _pct(
                physical["incremental"] + physical["zero_local"], n_traces
            ),
        },
        "counterfactuals": {
            "paired_measured": baseline["paired_measured"],
            "estimated": baseline["estimated"],
            "missing": baseline["missing"],
            "coverage_pct": _pct(
                baseline["paired_measured"] + baseline["estimated"], n_traces
            ),
        },
        "outcomes": {
            "verified": outcome["verified"],
            "negative": outcome["negative"],
            "execution_only": outcome["execution_only"],
            "unknown": outcome["unknown"],
            "verified_pct": _pct(outcome["verified"], n_traces),
        },
        "by_mechanism": _by_mechanism(rollups),
        "measurement_gaps": gaps,
        "flow_lane": {
            "prepare_events": len(prepare_events),
            "net_prepare_value_ms": pf.get("net_prepare_value_ms"),
            "speculation_overhead_ms": pf.get("speculation_overhead_ms"),
            "latency_hidden_ms": pf.get("latency_hidden_ms"),
            "note": "Flow ms economics are a separate lane — not added to token savings.",
        },
        "frontier_lane": {
            "actual_frontier_tokens": sum(r.actual_frontier_tokens for r in rollups),
            "measured_avoided": sum(
                r.tokens_avoided for r in rollups if r.savings_tier == "measured"
            ),
            "estimated_avoided": sum(
                r.tokens_avoided for r in rollups if r.savings_tier == "estimated"
            ),
            "unknown_baseline_traces": sum(
                1 for r in rollups if r.savings_tier == "unknown" and r.baseline == "missing"
            ),
        },
        "accounting_invariant": accounting,
        "savings_report_schema": savings.get("schema"),
    }


def format_coverage_text(report: dict[str, Any]) -> str:
    pu = report["physical_usage"]
    cf = report["counterfactuals"]
    oc = report["outcomes"]
    fl = report.get("flow_lane") or {}
    fr = report.get("frontier_lane") or {}
    lines = [
        f"SYSTEM TOKENOMICS COVERAGE · {report['range']}",
        "",
        "Traces",
        "────────────────────────────────────────",
        f"Traces                       {report['n_traces']}",
        f"Events                       {report['n_events']}",
        "",
        "Physical usage",
        "────────────────────────────────────────",
        f"Incremental provider-metered {pu['incremental_provider_metered']}",
        f"Zero local (metered)         {pu.get('zero_local', 0)}",
        f"Aggregate-only               {pu['aggregate_only']}",
        f"Unmetered                    {pu['unmetered']}",
        f"Physical coverage            {_fmt_pct(pu.get('coverage_pct'))}",
        "",
        "Counterfactuals",
        "────────────────────────────────────────",
        f"Paired measured              {cf['paired_measured']}",
        f"Estimated                    {cf['estimated']}",
        f"Missing                      {cf['missing']}",
        f"Counterfactual coverage      {_fmt_pct(cf.get('coverage_pct'))}",
        "",
        "Outcomes",
        "────────────────────────────────────────",
        f"Verified/gold                {oc['verified']}",
        f"Negative                     {oc['negative']}",
        f"Execution-only               {oc['execution_only']}",
        f"Unknown                      {oc['unknown']}",
        f"Verified coverage            {_fmt_pct(oc.get('verified_pct'))}",
        "",
        "Measurement levels",
        "────────────────────────────────────────",
    ]
    for lvl in ("M3", "M2", "M1", "M0"):
        lines.append(f"{lvl:<4}                         {report['measurement_levels'].get(lvl, 0)}")
    lines += ["", "By mechanism", "────────────────────────────────────────"]
    for row in report.get("by_mechanism", [])[:12]:
        lines.append(
            f"{row['mechanism']:<16} traces {row['traces']:>4}  "
            f"metered {row['metered_traces']:>4}  "
            f"baseline_cov {_fmt_pct(row.get('baseline_coverage'))}"
        )
    lines += [
        "",
        "FRONTIER COMPUTE (trace rollup — not mechanism sum)",
        "────────────────────────────────────────",
        f"Actual frontier tokens       {fr.get('actual_frontier_tokens', 0)}",
        f"Measured avoided             {fr.get('measured_avoided', 0)}",
        f"Estimated avoided            {fr.get('estimated_avoided', 0)}",
        f"Unknown baseline traces      {fr.get('unknown_baseline_traces', 0)}",
        "",
        "FLOW (separate lane)",
        "────────────────────────────────────────",
        f"Prepare events               {fl.get('prepare_events', 0)}",
        f"Net prepare value            {_fmt_ms(fl.get('net_prepare_value_ms'))}",
        f"Speculation overhead         {_fmt_ms(fl.get('speculation_overhead_ms'))}",
        "",
        "Highest-value measurement gaps",
        "────────────────────────────────────────",
    ]
    for g in report.get("measurement_gaps", [])[:8]:
        lines.append(
            f"{g['mechanism']:<12} {g['capability_id']:<22} n={g['n_traces']:<4} "
            f"baseline_cov={g['baseline_coverage']*100:.0f}%  EIV={g['expected_information_value']}"
        )
    period = report.get("period") or {}
    lines.append("")
    lines.append(f"Period {period.get('start_iso')} → {period.get('end_iso')}")
    lines.append("Coverage does not alter savings totals.")
    return "\n".join(lines) + "\n"


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_ms(v) -> str:
    if v is None:
        return "—"
    try:
        ms = float(v)
    except (TypeError, ValueError):
        return "—"
    if ms >= 60_000:
        return f"{ms/60000:.1f} min"
    if ms >= 1000:
        return f"{ms/1000:.2f} s"
    return f"{ms:.1f} ms"


def coverage_report_from_sources(
    *,
    range_spec: str = "7d",
    paths=None,
    root=None,
    now: float | None = None,
) -> dict[str, Any]:
    src = paths if paths is not None else default_sources(root=root)
    events = load_events_from_paths(src)
    return build_coverage_report(
        events,
        range_spec=range_spec,
        now=now,
        sources=[str(p) for p in src if Path(p).is_file()],
    )


