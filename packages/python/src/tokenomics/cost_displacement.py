"""Read-only paired cost vectors over canonical events and explicit trace totals.

This reports observed tradeoffs, never routing policy or causal attribution.
"""
from __future__ import annotations

import math
import re
from typing import Any

from .aggregate import aggregate_measurement_state
from .models import TokenomicsEvent
from .trace_accounting import aggregate_reported_tokens, incremental_provider_tokens, trace_outcome_class

STUDY_SCHEMA = 'tokenomics.paired_cost_study.v1'
REPORT_SCHEMA = 'tokenomics.cost_displacement.v1'
STATES = {'complete', 'partial', 'unsupported', 'failed', 'unknown'}
SUPPLEMENTAL = ('frontier_calls', 'local_compute_ms', 'wall_time_ms', 'tool_calls',
                'network_calls', 'retries', 'replans', 'human_interventions')
METRICS = ('frontier_tokens', 'total_model_tokens') + SUPPLEMENTAL


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError('study, work-item, and snapshot identities must be nonempty strings')
    return value


def _number(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a nonnegative finite number')
    if value < 0 or not math.isfinite(value):
        raise ValueError(f'{name} must be a nonnegative finite number')
    if not name.endswith('_ms') and int(value) != value:
        raise ValueError(f'{name} must be an integer count')
    return value


def _state(value: Any) -> str:
    if value not in STATES:
        raise ValueError('invalid measurement_state')
    return value


def _cost(observed: int | float | None, state: str, **source: Any) -> dict:
    return {'value': observed if state == 'complete' else None,
            'observed_value': observed, 'measurement_state': state, **source}


def _tokens(events: list[TokenomicsEvent], scope: str) -> dict:
    usage = [e for e in events if e.usage]
    inc = [e for e in usage if e.usage.attribution == 'incremental']
    observed = sum(incremental_provider_tokens(e) for e in inc)
    aggregate = [e for e in usage if e.usage.attribution == 'aggregate']
    latest = max((e.ts for e in aggregate), default=None)
    totals = {aggregate_reported_tokens(e) for e in aggregate if e.ts == latest}
    conflict = len(totals) > 1
    reported = next(iter(totals)) if len(totals) == 1 else None
    reconciliation = reported - observed if reported is not None else None
    state = aggregate_measurement_state(inc) if inc else scope
    incomplete = any(
        e.usage.attribution not in {'incremental', 'aggregate'}
        or e.usage.source not in {'provider', 'derived'}
        or e.usage.total() is None
        or (e.usage.reported_total_tokens is None
            and (e.usage.input_tokens is None or e.usage.output_tokens is None))
        for e in usage
    )
    if (scope != 'complete' or incomplete or (usage and not inc)
            or conflict or reconciliation not in (None, 0)
            or any(e.kind == 'llm' and e.usage is None for e in events)):
        state = scope if scope != 'complete' else 'unknown'
    return _cost(observed, state, event_ids=[e.event_id for e in inc],
                 aggregate_reported=reported, reconciliation_delta=reconciliation,
                 aggregate_conflict=conflict)


def _run(raw: dict, snapshots: dict[str, str], arms: tuple[str, str], study_id: str) -> dict:
    item, arm = raw['work_item_id'], raw['arm_id']
    if item not in snapshots or arm not in arms:
        raise ValueError('run has an unknown work item or arm')
    if raw['task_snapshot_id'] != snapshots[item]:
        raise ValueError('paired runs must use the frozen task snapshot')
    if not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', raw['revision']):
        raise ValueError('revision must be a full immutable hex revision')
    for event in raw['events']:
        for key in ('event_id', 'trace_id', 'span_id'):
            _identity(event.get(key))
        _number(event.get('ts'), 'timestamp_ms')
    events = [TokenomicsEvent.from_dict(e) for e in raw['events']]
    if not events or len({e.trace_id for e in events}) != 1:
        raise ValueError('one nonempty canonical trace is required per run')
    by_id = {e.event_id: e for e in events}
    if len(by_id) != len(events):
        raise ValueError('duplicate event_id would count usage twice')
    for event in events:
        if event.experiment:
            for field, expected in (('experiment_id', study_id), ('arm_id', arm),
                                    ('task_snapshot_id', snapshots[item])):
                actual = getattr(event.experiment, field)
                if actual is not None and actual != expected:
                    raise ValueError(f'canonical experiment identity conflicts: {field}')
        if event.usage:
            for name in ('input_tokens', 'output_tokens', 'reported_total_tokens'):
                value = getattr(event.usage, name)
                if value is not None:
                    _number(value, name)
    scope = _state(raw.get('token_measurement_state', 'unknown'))
    costs = {'total_model_tokens': _tokens(events, scope)}
    frontier_ids = raw.get('frontier_event_ids')
    if frontier_ids is None:
        costs['frontier_tokens'] = _cost(None, 'unknown', event_ids=[])
    else:
        if not isinstance(frontier_ids, list) or len(set(frontier_ids)) != len(frontier_ids):
            raise ValueError('frontier_event_ids must be a unique explicit list')
        if any(i not in by_id or not by_id[i].usage
               or by_id[i].usage.attribution != 'incremental' for i in frontier_ids):
            raise ValueError('frontier_event_ids must reference incremental usage events')
        costs['frontier_tokens'] = _tokens([by_id[i] for i in frontier_ids], scope)
        if (costs['total_model_tokens']['aggregate_conflict']
                or costs['total_model_tokens']['reconciliation_delta'] not in (None, 0)):
            costs['frontier_tokens']['value'] = None
            costs['frontier_tokens']['measurement_state'] = 'unknown'
    observations = raw.get('cost_observations', {})
    if set(observations) - set(SUPPLEMENTAL):
        raise ValueError('unknown supplemental cost dimension')
    for metric in SUPPLEMENTAL:
        observation = observations.get(metric)
        if observation is None:
            costs[metric] = _cost(None, 'unknown', evidence_ref=None)
            continue
        if observation.get('attribution') != 'trace_total':
            raise ValueError(f'{metric} requires one trace total, never additive counters')
        state = _state(observation.get('measurement_state', 'unknown'))
        value = observation.get('value')
        if value is not None:
            _number(value, metric)
        if state == 'complete' and value is None:
            raise ValueError(f'{metric}: complete measurement needs an explicit value')
        reference = observation.get('evidence_ref')
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError(f'{metric}: evidence_ref is required')
        costs[metric] = _cost(value, state, evidence_ref=reference)
    sources = sorted({_identity(e.outcome.verification_source) for e in events
                      if e.outcome and e.outcome.tier() == 'gold' and e.outcome.verification_source})
    outcome = trace_outcome_class(events)
    lineage = [{'event_id': e.event_id, **e.to_dict()['experiment']}
               for e in events if e.experiment]
    reused = any((e.extra or {}).get('reuse_kind') in {'cache', 'offline', 'offline_replay'}
                 or (e.experiment and (e.experiment.reuse_kind in {'cache', 'offline_replay'}
                                      or e.experiment.production_credit_eligible is False)) for e in events)
    return {'work_item_id': item, 'arm_id': arm, 'task_snapshot_id': snapshots[item],
            'trace_id': events[0].trace_id, 'revision': raw['revision'],
            'outcome': outcome, 'verified': outcome == 'verified' and bool(sources),
            'verification_sources': sources, 'costs': costs, 'event_ids': list(by_id),
            'experiment_lineage': lineage, 'reused_or_ineligible_evidence': bool(reused)}


def _arm(rows: list[dict], expected: int) -> dict:
    verified = sum(r['verified'] for r in rows)
    metrics = {}
    for metric in METRICS:
        values = [r['costs'][metric]['value'] for r in rows]
        observed = [r['costs'][metric]['observed_value'] for r in rows]
        complete = len(values) == expected and all(v is not None for v in values)
        total = sum(values) if complete else None
        metrics[metric] = {
            'total': total,
            'observed_total': sum(v for v in observed if v is not None) if any(v is not None for v in observed) else None,
            'n_complete': sum(v is not None for v in values),
            'coverage': sum(v is not None for v in values) / expected,
            'per_verified_success': total / verified if total is not None and verified else None,
        }
    wall = sorted(r['costs']['wall_time_ms']['value'] for r in rows
                  if r['costs']['wall_time_ms']['value'] is not None)
    tails = {'method': 'nearest_rank', 'n': len(wall), 'p95_ms': None, 'p99_ms': None}
    if len(wall) == expected:
        tails.update({f'p{p}_ms': wall[math.ceil(len(wall) * p / 100) - 1] for p in (95, 99)})
    return {'n_expected': expected, 'n_observed': len(rows), 'n_verified': verified,
            'verification_rate': verified / expected, 'costs': metrics, 'wall_latency': tails}


def build_cost_displacement_report(study: dict) -> dict:
    """Compare matched frozen work items; missing observations never become zero."""
    if not isinstance(study, dict) or study.get('schema') != STUDY_SCHEMA:
        raise ValueError('unsupported paired cost study schema')
    study_id = _identity(study['study_id'])
    origin = study.get('evidence_origin', 'unknown')
    if origin not in {'synthetic', 'observed', 'replay', 'unknown'}:
        raise ValueError('invalid evidence_origin')
    arms = (study['baseline_arm'], study['treatment_arm'])
    if any(not isinstance(a, str) or not a.strip() for a in arms) or arms[0] == arms[1]:
        raise ValueError('two distinct named arms are required')
    items = study['work_items']
    snapshots = {_identity(i['work_item_id']): _identity(i['task_snapshot_id']) for i in items}
    if not snapshots or len(snapshots) != len(items) or any(not k or not v for k, v in snapshots.items()):
        raise ValueError('work_items must identify unique nonempty frozen snapshots')
    rows = [_run(r, snapshots, arms, study_id) for r in study['runs']]
    event_ids = [event_id for row in rows for event_id in row['event_ids']]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError('event_id must not be reused across study runs')
    indexed = {(r['work_item_id'], r['arm_id']): r for r in rows}
    if len(indexed) != len(rows) or len({r['trace_id'] for r in rows}) != len(rows):
        raise ValueError('duplicate run or reused trace in the study')
    pairs = []
    for item in snapshots:
        baseline, treatment = (indexed.get((item, arm)) for arm in arms)
        deltas = {}
        for metric in METRICS:
            a = baseline['costs'][metric]['value'] if baseline else None
            b = treatment['costs'][metric]['value'] if treatment else None
            deltas[metric] = b - a if a is not None and b is not None else None
        unknown = [m for m, v in deltas.items() if v is None]
        increased = [m for m, v in deltas.items() if v is not None and v > 0]
        verified = bool(baseline and treatment and baseline['verified'] and treatment['verified'])
        limitations = []
        if origin in {'replay', 'unknown'} or any(r and r['reused_or_ineligible_evidence'] for r in (baseline, treatment)):
            limitations.append('reused_or_ineligible_evidence')
        frontier = deltas['frontier_tokens']
        if not verified or frontier is None or limitations:
            finding = 'inconclusive'
        elif frontier < 0 and increased:
            finding = 'cost_displacement'
        elif unknown:
            finding = 'inconclusive'
        elif frontier < 0:
            finding = 'vector_improvement'
        else:
            finding = 'no_frontier_reduction'
        pairs.append({'work_item_id': item, 'task_snapshot_id': snapshots[item],
                      'both_verified': verified, 'deltas': deltas,
                      'incomplete_dimensions': unknown, 'increased_dimensions': increased,
                      'comparison_limitations': limitations,
                      'finding': finding})
    return {'schema': REPORT_SCHEMA, 'study_id': study_id,
            'evidence_origin': origin,
            'evidence_level': 'synthetic_example' if origin == 'synthetic' else 'paired_observational',
            'causal_claim': False,
            'delta_direction': 'treatment_minus_baseline',
            'unit_of_analysis': 'one frozen work item per arm, including recovery costs',
            'runs': rows, 'pairs': pairs,
            'arms': {a: _arm([r for r in rows if r['arm_id'] == a], len(snapshots)) for a in arms}}
