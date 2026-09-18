from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import from_kerdoios_observation, from_z0int_receipt
from .aggregate import summarize_traces, tokens_per_verified_task
from .jsonl import JsonlSink, iter_jsonl
from .models import TokenomicsEvent
from .otel import to_otel_attributes
from .report import (
    format_savings_text,
    load_events_from_paths,
    savings_report_from_sources,
)


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cmd_validate(args: argparse.Namespace) -> int:
    bad = 0
    for idx, event in enumerate(iter_jsonl(args.path, strict=False), 1):
        try:
            TokenomicsEvent.from_dict(event.to_dict())
        except ValueError as exc:
            bad += 1
            print(f"{idx}: {exc}", file=sys.stderr)
    if bad:
        return 1
    print("ok")
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    events = list(iter_jsonl(args.path))
    payload = {
        "traces": [s.__dict__ for s in summarize_traces(events)],
        "verified_economics": tokens_per_verified_task(events),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    raw = _read_json(args.input)
    event = from_z0int_receipt(raw) if args.from_format == "z0int" else from_kerdoios_observation(raw)
    if args.output:
        JsonlSink(args.output).emit(event)
    else:
        print(json.dumps(event.to_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_otel(args: argparse.Namespace) -> int:
    event = TokenomicsEvent.from_dict(_read_json(args.input))
    print(json.dumps(to_otel_attributes(event), indent=2, sort_keys=True))
    return 0


def _cmd_savings(args: argparse.Namespace) -> int:
    paths = [Path(p) for p in (args.path or [])] or None
    report = savings_report_from_sources(range_spec=args.range, paths=paths)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        sys.stdout.write(format_savings_text(report))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Alias for savings with JSON default — the product contract surface."""
    paths = [Path(p) for p in (args.path or [])] or None
    report = savings_report_from_sources(range_spec=args.range, paths=paths)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tokenomics")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="validate/read a tokenomics JSONL file")
    p.add_argument("path")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("summary", help="summarize traces and verified-task economics")
    p.add_argument("path")
    p.set_defaults(func=_cmd_summary)

    p = sub.add_parser("convert", help="convert a legacy z0int or Kerdoios JSON object")
    p.add_argument("--from", dest="from_format", choices=("z0int", "kerdoios"), required=True)
    p.add_argument("input")
    p.add_argument("--output")
    p.set_defaults(func=_cmd_convert)

    p = sub.add_parser("otel-attrs", help="print OTel attributes for one canonical event JSON")
    p.add_argument("input")
    p.set_defaults(func=_cmd_otel)

    p = sub.add_parser(
        "savings",
        help="tokenomics.report.v1 savings (measured vs estimated never collapsed)",
    )
    p.add_argument("--range", default="7d", help="today|7d|30d|24h|all")
    p.add_argument("--path", action="append", default=[], help="JSONL source (repeatable); default ~/.z0int")
    p.add_argument("--json", action="store_true", help="emit tokenomics.report.v1 JSON")
    p.set_defaults(func=_cmd_savings)

    p = sub.add_parser("report", help="emit tokenomics.report.v1 JSON (same as savings --json)")
    p.add_argument("--range", default="7d", help="today|7d|30d|24h|all")
    p.add_argument("--path", action="append", default=[], help="JSONL source (repeatable)")
    p.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
