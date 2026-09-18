"""Canonical tokenomics.report.v1 — savings without collapsing tiers."""

from __future__ import annotations

import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from .adapters import from_kerdoios_observation, from_z0int_receipt
from .aggregate import tokens_per_verified_task
from .models import TokenomicsEvent

REPORT_SCHEMA = "tokenomics.report.v1"
SavingsTier = Literal["measured", "estimated", "unknown"]


def parse_range(spec: str, *, now: float | None = None) -> tuple[float, float]:
    """Parse range like today|7d|30d|all|24h into (start_ts, end_ts) local-aware UTC."""
    end = now if now is not None else time.time()
    s = (spec or "7d").strip().lower()
    if s in {"all", "*"}:
        return 0.0, end
    if s == "today":
        # local midnight
        local = datetime.now().astimezone()
        start_dt = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_dt.timestamp(), end
    if s.endswith("d") and s[:-1].isdigit():
        days = int(s[:-1])
        return end - days * 86400.0, end
    if s.endswith("h") and s[:-1].isdigit():
        hours = int(s[:-1])
        return end - hours * 3600.0, end
    if s.endswith("m") and s[:-1].isdigit():
        mins = int(s[:-1])
        return end - mins * 60.0, end
    raise ValueError(f"unsupported range {spec!r}; use today|7d|30d|24h|all")


def _baseline_tokens(ev: TokenomicsEvent) -> int | None:
    extra = ev.extra or {}
    if extra.get("baseline_total_tokens") is not None:
        try:
            return int(extra["baseline_total_tokens"])
        except (TypeError, ValueError):
            return None
    return None


def _measured_frontier(ev: TokenomicsEvent) -> int | None:
    extra = ev.extra or {}
    if extra.get("measured_frontier_tokens") is not None:
        try:
            return int(extra["measured_frontier_tokens"])
        except (TypeError, ValueError):
            pass
    if ev.usage and ev.usage.reported_total_tokens is not None:
        try:
            return int(ev.usage.reported_total_tokens)
        except (TypeError, ValueError):
            return None
    # actual frontier usage if provider-attributed
    if ev.usage and ev.usage.source == "provider":
        tot = ev.usage.total()
        if tot:
            return int(tot)
    return None


def _actual_tokens(ev: TokenomicsEvent) -> int:
    """Tokens actually spent on frontier (0 if fully offloaded/local)."""
    m = _measured_frontier(ev)
    if m is not None:
        return max(0, m)
    if ev.usage and ev.usage.source == "provider":
        return int(ev.usage.total() or 0)
    # local/router offload with no measured spend
    route = str((ev.extra or {}).get("route") or "")
    if route in {"local", "local_model", "routine", "specialist", "log_only"}:
        return 0
    if ev.usage:
        return int(ev.usage.total() or 0)
    return 0


def classify_savings(ev: TokenomicsEvent) -> tuple[SavingsTier, int, int, int]:
    """Return (tier, baseline, actual, avoided) for one event.

    MEASURED: paired baseline + measured frontier.
    ESTIMATED: estimate field present (and not already counted as measured).
    UNKNOWN: no trustworthy baseline/estimate.
    """
    base = _baseline_tokens(ev)
    measured = _measured_frontier(ev)
    econ = ev.economics
    est = int(econ.estimated_tokens_avoided) if econ and econ.estimated_tokens_avoided is not None else None
    meas_av = int(econ.measured_tokens_avoided) if econ and econ.measured_tokens_avoided is not None else None

    if base is not None and measured is not None:
        avoided = max(0, base - measured)
        if meas_av is not None:
            avoided = max(0, meas_av)
        return "measured", base, measured, avoided

    if est is not None and est > 0:
        # estimated path: baseline may still be known
        b = base if base is not None else est  # weak baseline proxy only for display totals
        actual = _actual_tokens(ev)
        return "estimated", b if base is not None else 0, actual, est

    if base is not None:
        actual = _actual_tokens(ev)
        return "unknown", base, actual, 0

    actual = _actual_tokens(ev)
    return "unknown", 0, actual, 0


def _mechanism(ev: TokenomicsEvent) -> str:
    extra = ev.extra or {}
    route = str(extra.get("route") or "").lower()
    cap = str(ev.capability_id or ev.name or "").lower()
    if route in {"routine"} or "routine" in cap:
        return "routine"
    if route in {"specialist", "local_model"} or "specialist" in cap:
        return "specialist"
    if route in {"local"} or "jev" in cap or "nanojev" in cap:
        return "jev"
    if "context" in cap or "compress" in cap:
        return "context_compression"
    if "cache" in cap:
        return "cache"
    if route in {"model", "frontier", "cloud"} or (ev.model and ev.model.provider):
        # offload residual still on frontier
        if classify_savings(ev)[0] == "measured" and classify_savings(ev)[3] > 0:
            return "model_routing"
        return "frontier"
    if route in {"log_only"}:
        return "log_only"
    return "other"


def z0int_home() -> Path:
    override = os.environ.get("Z0INT_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".z0int"


def load_events_from_paths(paths: Iterable[Path]) -> list[TokenomicsEvent]:
    events: list[TokenomicsEvent] = []
    for path in paths:
        if not path or not Path(path).is_file():
            continue
        path = Path(path)
        for raw in _iter_raw_jsonl(path):
            ev = _coerce_event(raw)
            if ev is not None:
                events.append(ev)
    return events


def _iter_raw_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _coerce_event(raw: dict[str, Any]) -> TokenomicsEvent | None:
    schema = str(raw.get("schema") or "")
    # Nested bridge envelope
    if isinstance(raw.get("receipt"), dict):
        rec = dict(raw["receipt"])
        if raw.get("outcome") and "outcome" not in rec:
            rec["outcome"] = raw["outcome"]
        if raw.get("outcome_tier") and "outcome_tier" not in rec:
            rec["outcome_tier"] = raw["outcome_tier"]
        raw = rec
        schema = str(raw.get("schema") or schema)

    if schema.startswith("tokenomics.event"):
        try:
            return TokenomicsEvent.from_dict(raw)
        except Exception:
            return None
    if schema.startswith("z0int.decision_receipt") or "capability_id" in raw or "baseline_input_tokens" in raw:
        try:
            return from_z0int_receipt(raw)
        except Exception:
            return None
    if schema.startswith("kerdoios") or "observed_execution" in schema or (
        "provider" in raw and "model" in raw and "input_tokens" in raw
    ):
        try:
            return from_kerdoios_observation(raw)
        except Exception:
            return None
    # Generic tokenomics-ish
    if "trace_id" in raw and ("usage" in raw or "economics" in raw):
        try:
            return TokenomicsEvent.from_dict(raw)
        except Exception:
            return None
    return None


def default_sources(*, root: Path | None = None) -> list[Path]:
    """Discover local measurement streams without requiring a UI."""
    home = root or z0int_home()
    paths = [
        home / "receipts" / "decisions.jsonl",
        home / "stream" / "bridge.jsonl",
        home / "tokenomics" / "events.jsonl",
        Path(os.environ.get("TOKENOMICS_JSONL", "")).expanduser() if os.environ.get("TOKENOMICS_JSONL") else None,
    ]
    return [p for p in paths if p is not None]


def build_savings_report(
    events: Iterable[TokenomicsEvent],
    *,
    range_spec: str = "7d",
    now: float | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate tokenomics.report.v1 savings. Never collapses measured∪estimated."""
    start, end = parse_range(range_spec, now=now)
    rows = [e for e in events if start <= float(e.ts or 0) <= end]
    n = len(rows)

    baseline_sum = 0
    actual_sum = 0
    measured_avoided = 0
    estimated_avoided = 0
    unknown_baseline_tokens = 0
    n_measured = 0
    n_estimated = 0
    n_unknown = 0

    by_mech_avoided: Counter[str] = Counter()
    by_mech_actual: Counter[str] = Counter()
    by_harness_avoided: Counter[str] = Counter()
    by_harness_actual: Counter[str] = Counter()
    by_harness_verified: Counter[str] = Counter()
    by_cap_actual: Counter[str] = Counter()
    by_provider_actual: Counter[str] = Counter()
    by_model_actual: Counter[str] = Counter()
    by_tier: Counter[str] = Counter()

    # daily buckets for timeseries (UTC date)
    ts_base: dict[str, int] = defaultdict(int)
    ts_actual: dict[str, int] = defaultdict(int)
    ts_meas: dict[str, int] = defaultdict(int)
    ts_est: dict[str, int] = defaultdict(int)

    for ev in rows:
        tier, base, actual, avoided = classify_savings(ev)
        by_tier[tier] += 1
        baseline_sum += base
        actual_sum += actual
        day = datetime.fromtimestamp(float(ev.ts or end), tz=timezone.utc).strftime("%Y-%m-%d")
        ts_base[day] += base
        ts_actual[day] += actual

        if tier == "measured":
            n_measured += 1
            measured_avoided += avoided
            ts_meas[day] += avoided
        elif tier == "estimated":
            n_estimated += 1
            estimated_avoided += avoided
            ts_est[day] += avoided
        else:
            n_unknown += 1
            if base <= 0 and actual > 0:
                unknown_baseline_tokens += actual

        mech = _mechanism(ev)
        by_mech_avoided[mech] += avoided
        by_mech_actual[mech] += actual
        harness = str(ev.harness or "unknown")
        by_harness_avoided[harness] += avoided
        by_harness_actual[harness] += actual
        cap = str(ev.capability_id or ev.name or "unknown")
        by_cap_actual[cap] += actual
        if ev.model:
            if ev.model.provider:
                by_provider_actual[str(ev.model.provider)] += actual
            if ev.model.name:
                by_model_actual[str(ev.model.name)] += actual
        if ev.outcome is not None and ev.outcome.tier() == "gold":
            by_harness_verified[harness] += 1

    verified_stats = tokens_per_verified_task(rows)
    # Baseline tokens / verified uses sum of baselines on gold traces when available
    gold_events = [e for e in rows if e.outcome is not None and e.outcome.tier() == "gold"]
    gold_base = sum(_baseline_tokens(e) or 0 for e in gold_events)
    gold_n = int(verified_stats.get("n_verified") or 0)
    baseline_per_verified = (gold_base / gold_n) if gold_n and gold_base else None
    actual_per_verified = verified_stats.get("tokens_per_verified_task")

    reduction = None
    if baseline_sum > 0:
        reduction = round(1.0 - (actual_sum / baseline_sum), 4)

    total_avoided_display = measured_avoided + estimated_avoided  # for UI split only — never single headline without tiers

    def _pct_map(counter: Counter[str], total: int) -> list[dict[str, Any]]:
        t = total if total > 0 else sum(counter.values()) or 1
        out = []
        for k, v in counter.most_common():
            out.append(
                {
                    "key": k,
                    "tokens": int(v),
                    "share": round(v / t, 4) if t else 0.0,
                }
            )
        return out

    mech_total = sum(by_mech_avoided.values()) or sum(by_mech_actual.values()) or 1
    # mechanism shares prefer avoided mass; include frontier residual actual
    mech_rows = []
    keys = set(by_mech_avoided) | set(by_mech_actual)
    for k in sorted(keys, key=lambda x: -(by_mech_avoided[x] + by_mech_actual[x])):
        av = by_mech_avoided[k]
        ac = by_mech_actual[k]
        mech_rows.append(
            {
                "mechanism": k,
                "tokens_avoided": int(av),
                "tokens_actual": int(ac),
                "share_of_avoided": round(av / mech_total, 4) if mech_total else 0.0,
            }
        )

    harness_rows = []
    for h in sorted(set(by_harness_actual) | set(by_harness_avoided), key=lambda x: -by_harness_avoided[x]):
        harness_rows.append(
            {
                "harness": h,
                "tokens_avoided": int(by_harness_avoided[h]),
                "tokens_actual": int(by_harness_actual[h]),
                "verified_tasks": int(by_harness_verified[h]),
            }
        )

    days = sorted(set(ts_base) | set(ts_actual) | set(ts_meas) | set(ts_est))
    timeseries = [
        {
            "day": d,
            "baseline_tokens": int(ts_base[d]),
            "actual_frontier_tokens": int(ts_actual[d]),
            "measured_tokens_avoided": int(ts_meas[d]),
            "estimated_tokens_avoided": int(ts_est[d]),
        }
        for d in days
    ]

    return {
        "schema": REPORT_SCHEMA,
        "range": range_spec,
        "period": {
            "start_ts": start,
            "end_ts": end,
            "start_iso": datetime.fromtimestamp(start, tz=timezone.utc).isoformat() if start > 0 else None,
            "end_iso": datetime.fromtimestamp(end, tz=timezone.utc).isoformat(),
        },
        "sources": sources or [],
        "n_events": n,
        "totals": {
            "baseline_tokens": int(baseline_sum),
            "actual_frontier_tokens": int(actual_sum),
            # Split is mandatory — never a single collapsed "saved" headline field.
            "measured_tokens_avoided": int(measured_avoided),
            "estimated_tokens_avoided": int(estimated_avoided),
            "unknown_or_no_baseline_tokens": int(unknown_baseline_tokens),
            "tokens_avoided_sum_for_display_only": int(total_avoided_display),
            "reduction_vs_baseline": reduction,
        },
        "savings": {
            "tiers": {
                "measured": {"events": n_measured, "tokens_avoided": int(measured_avoided)},
                "estimated": {"events": n_estimated, "tokens_avoided": int(estimated_avoided)},
                "unknown": {"events": n_unknown, "tokens_observed_without_baseline": int(unknown_baseline_tokens)},
            },
            "rule": "Never collapse measured and estimated into one savings number.",
        },
        "verified_outcomes": {
            "verified_tasks": gold_n,
            "tokens_per_verified_task": actual_per_verified,
            "baseline_tokens_per_verified_task": baseline_per_verified,
            "reduction_per_verified": (
                round(1.0 - (float(actual_per_verified) / float(baseline_per_verified)), 4)
                if actual_per_verified and baseline_per_verified
                else None
            ),
            "trace_stats": verified_stats,
        },
        "by_mechanism": mech_rows,
        "by_harness": harness_rows,
        "by_capability": _pct_map(by_cap_actual, actual_sum),
        "by_provider": _pct_map(by_provider_actual, actual_sum),
        "by_model": _pct_map(by_model_actual, actual_sum),
        "timeseries": timeseries,
        "data_quality": {
            "tier_event_counts": dict(by_tier),
            "events_with_baseline": sum(1 for e in rows if _baseline_tokens(e) is not None),
            "events_with_measured_frontier": sum(1 for e in rows if _measured_frontier(e) is not None),
            "events_with_estimate_only": n_estimated,
        },
        "economics": {
            # Costs optional — only when events carry prices/cost_usd.
            "observed_cost_usd": _sum_cost(rows, baseline=False),
            "baseline_cost_usd": _sum_cost(rows, baseline=True),
            "note": "Costs only sum when events include cost_usd / baseline_cost_usd; never invent prices.",
        },
    }


def _sum_cost(rows: list[TokenomicsEvent], *, baseline: bool) -> float | None:
    total = 0.0
    any_c = False
    for ev in rows:
        if not ev.economics:
            continue
        v = ev.economics.baseline_cost_usd if baseline else ev.economics.cost_usd
        if v is None:
            continue
        any_c = True
        total += float(v)
    return round(total, 6) if any_c else None


def format_savings_text(report: dict[str, Any]) -> str:
    """Human report — measured and estimated always on separate lines."""
    tot = report["totals"]
    sav = report["savings"]["tiers"]
    ver = report["verified_outcomes"]
    period = report["period"]
    lines = [
        f"Tokenomics · {report['range']}",
        "",
        "Frontier work",
        "────────────────────────────────────────",
        f"Baseline tokens              {_fmt_tok(tot['baseline_tokens'])}",
        f"Actual frontier tokens       {_fmt_tok(tot['actual_frontier_tokens'])}",
        f"Measured tokens avoided      {_fmt_tok(sav['measured']['tokens_avoided'])}",
        f"Estimated tokens avoided     {_fmt_tok(sav['estimated']['tokens_avoided'])}",
        f"Unknown / no baseline        {_fmt_tok(tot['unknown_or_no_baseline_tokens'])}",
        "",
        "Verified outcomes",
        "────────────────────────────────────────",
        f"Verified tasks               {ver['verified_tasks']}",
        f"Tokens / verified task       {_fmt_tok(ver['tokens_per_verified_task'])}",
        f"Baseline tokens / task       {_fmt_tok(ver['baseline_tokens_per_verified_task'])}",
        f"Reduction                    {_fmt_pct(ver.get('reduction_per_verified'))}",
        "",
        "Offload (by mechanism)",
        "────────────────────────────────────────",
    ]
    for row in report["by_mechanism"][:8]:
        lines.append(
            f"{row['mechanism']:<22} avoided {_fmt_tok(row['tokens_avoided']):>8}  "
            f"actual {_fmt_tok(row['tokens_actual']):>8}  "
            f"({row['share_of_avoided']*100:.1f}% avoided share)"
        )
    lines += [
        "",
        "By harness",
        "────────────────────────────────────────",
        f"{'harness':<16}{'avoided':>10}{'actual':>10}{'verified':>10}",
    ]
    for row in report["by_harness"][:10]:
        lines.append(
            f"{row['harness']:<16}{_fmt_tok(row['tokens_avoided']):>10}"
            f"{_fmt_tok(row['tokens_actual']):>10}{row['verified_tasks']:>10}"
        )
    red = tot.get("reduction_vs_baseline")
    lines += [
        "",
        f"Reduction vs baseline workload: {_fmt_pct(red)}",
        f"Events: {report['n_events']}  "
        f"(measured={sav['measured']['events']} estimated={sav['estimated']['events']} "
        f"unknown={sav['unknown']['events']})",
        "Rule: never collapse measured and estimated savings.",
    ]
    if report.get("economics", {}).get("observed_cost_usd") is not None:
        eco = report["economics"]
        lines += [
            "",
            "Economics (only where cost fields present)",
            "────────────────────────────────────────",
            f"Observed cost                ${_fmt_money(eco.get('observed_cost_usd'))}",
            f"Baseline cost                ${_fmt_money(eco.get('baseline_cost_usd'))}",
        ]
    lines.append(f"Period {period.get('start_iso')} → {period.get('end_iso')}")
    return "\n".join(lines) + "\n"


def _fmt_tok(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(int(n) if n == int(n) else round(n, 1))


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_money(v: Any) -> str:
    if v is None:
        return "—"
    return f"{float(v):.2f}"


def savings_report_from_sources(
    *,
    range_spec: str = "7d",
    paths: list[Path] | None = None,
    root: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    src = paths if paths is not None else default_sources(root=root)
    events = load_events_from_paths(src)
    return build_savings_report(
        events,
        range_spec=range_spec,
        now=now,
        sources=[str(p) for p in src if Path(p).is_file()],
    )
