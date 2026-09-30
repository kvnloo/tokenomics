from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tokenomics.cost_displacement import build_cost_displacement_report

FIXTURE = Path(__file__).resolve().parents[3] / 'fixtures/paired-cost-study.json'


def study():
    return json.loads(FIXTURE.read_text())


def test_savings_and_displacement_are_different_findings():
    report = build_cost_displacement_report(study())
    assert report['schema'] == 'tokenomics.cost_displacement.v1'
    assert [p['finding'] for p in report['pairs']] == ['vector_improvement', 'cost_displacement']
    assert report['pairs'][1]['increased_dimensions'] == ['local_compute_ms', 'wall_time_ms', 'retries', 'human_interventions']
    assert report['causal_claim'] is False


def test_missing_observation_is_not_zero_or_savings():
    data = study()
    del data['runs'][1]['cost_observations']['local_compute_ms']
    pair = build_cost_displacement_report(data)['pairs'][0]
    assert pair['deltas']['local_compute_ms'] is None
    assert pair['finding'] == 'inconclusive'
    assert 'local_compute_ms' in pair['incomplete_dimensions']


@pytest.mark.parametrize('state', ['partial', 'failed', 'unsupported', 'unknown'])
def test_incomplete_numbers_are_visible_but_not_authoritative(state):
    data = study()
    data['runs'][1]['cost_observations']['local_compute_ms']['measurement_state'] = state
    report = build_cost_displacement_report(data)
    metric = report['runs'][1]['costs']['local_compute_ms']
    assert metric['observed_value'] == 0
    assert metric['value'] is None
    assert metric['measurement_state'] == state
    assert report['pairs'][0]['finding'] == 'inconclusive'


def test_aggregate_and_incremental_tokens_are_not_added():
    report = build_cost_displacement_report(study())
    assert report['runs'][0]['costs']['total_model_tokens']['value'] == 1000
    assert report['runs'][0]['costs']['frontier_tokens']['value'] == 1000
    assert report['pairs'][0]['deltas']['frontier_tokens'] == -600


def test_aggregate_only_tokens_cannot_become_zero():
    data = study()
    run = data['runs'][1]
    run['events'] = [e for e in run['events'] if not e.get('usage') or e['usage']['attribution'] == 'aggregate']
    run['frontier_event_ids'] = []
    report = build_cost_displacement_report(data)
    assert report['runs'][1]['costs']['total_model_tokens']['value'] is None
    assert report['pairs'][0]['finding'] == 'inconclusive'


def test_unknown_scope_cannot_mint_measured_savings():
    data = study()
    del data['runs'][1]['token_measurement_state']
    assert build_cost_displacement_report(data)['pairs'][0]['finding'] == 'inconclusive'


def test_missing_frontier_classification_is_unknown_not_zero():
    data = study()
    del data['runs'][1]['frontier_event_ids']
    report = build_cost_displacement_report(data)
    assert report['runs'][1]['costs']['frontier_tokens']['value'] is None


def test_verified_denominator_includes_cost_of_unsuccessful_runs():
    data = study()
    outcome = data['runs'][3]['events'][-1]['outcome']
    outcome.pop('verified_success')
    outcome['execution_completed'] = True
    report = build_cost_displacement_report(data)
    arm = report['arms']['offload']
    assert arm['n_verified'] == 1
    assert arm['n_observed'] == 2
    assert arm['costs']['total_model_tokens']['total'] == 800
    assert arm['costs']['total_model_tokens']['per_verified_success'] == 800
    assert report['pairs'][1]['finding'] == 'inconclusive'


def test_no_verified_success_has_no_ratio():
    data = study()
    for run in data['runs']:
        run['events'][-1]['outcome'] = {'execution_completed': True}
    report = build_cost_displacement_report(data)
    assert report['arms']['baseline']['costs']['total_model_tokens']['per_verified_success'] is None


def test_missing_arm_remains_in_expected_denominator():
    data = study()
    data['runs'].pop()
    report = build_cost_displacement_report(data)
    assert report['arms']['offload']['n_expected'] == 2
    assert report['arms']['offload']['n_observed'] == 1
    assert report['arms']['offload']['costs']['total_model_tokens']['total'] is None
    assert report['pairs'][1]['finding'] == 'inconclusive'


@pytest.mark.parametrize('change', ['duplicate_run', 'snapshot', 'unknown_group', 'duplicate_event', 'unknown_frontier_id'])
def test_ambiguous_pairing_or_duplicate_usage_is_rejected(change):
    data = study()
    if change == 'duplicate_run':
        data['runs'].append(deepcopy(data['runs'][0]))
    elif change == 'snapshot':
        data['runs'][1]['task_snapshot_id'] = 'different-task'
    elif change == 'unknown_group':
        data['runs'][1]['work_item_id'] = 'unregistered'
    elif change == 'duplicate_event':
        data['runs'][1]['events'].append(deepcopy(data['runs'][1]['events'][0]))
    else:
        data['runs'][1]['frontier_event_ids'] = ['not-recorded']
    with pytest.raises(ValueError):
        build_cost_displacement_report(data)


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '12'])
def test_invalid_costs_are_rejected(value):
    data = study()
    data['runs'][0]['cost_observations']['local_compute_ms']['value'] = value
    with pytest.raises(ValueError):
        build_cost_displacement_report(data)


def test_supplement_is_one_trace_total_not_incremental_plus_aggregate():
    data = study()
    data['runs'][0]['cost_observations']['retries']['attribution'] = 'incremental'
    with pytest.raises(ValueError, match='trace total'):
        build_cost_displacement_report(data)


def test_observation_needs_source_and_complete_value():
    for key in ('evidence_ref', 'value'):
        data = study()
        del data['runs'][0]['cost_observations']['retries'][key]
        with pytest.raises(ValueError):
            build_cost_displacement_report(data)


def test_tail_latency_reports_method_and_sample_size():
    arm = build_cost_displacement_report(study())['arms']['offload']
    assert arm['wall_latency'] == {'method': 'nearest_rank', 'n': 2, 'p95_ms': 1800, 'p99_ms': 1800}


def test_report_does_not_mutate_input_and_preserves_revision_sources():
    data = study()
    original = deepcopy(data)
    report = build_cost_displacement_report(data)
    assert data == original
    assert report['runs'][0]['revision'] == data['runs'][0]['revision']
    assert report['runs'][0]['verification_sources'] == ['fixture-verifier-v1']


def test_cli_is_explicit_file_only_and_emits_consumer_json():
    result = subprocess.run([sys.executable, '-m', 'tokenomics.cli', 'compare-costs', str(FIXTURE)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['pairs'][1]['finding'] == 'cost_displacement'


def test_verification_source_must_belong_to_positive_evidence():
    data = study()
    positive = data['runs'][1]['events'][-1]['outcome']
    positive.pop('verification_source')
    data['runs'][1]['events'][0]['outcome'] = {'execution_completed': True, 'verification_source': 'not-a-quality-check'}
    assert build_cost_displacement_report(data)['pairs'][0]['finding'] == 'inconclusive'


def test_frontier_measurement_cannot_use_unmetered_remainder_as_zero():
    data = study()
    data['runs'][1]['events'][0]['usage']['output_tokens'] = None
    report = build_cost_displacement_report(data)
    assert report['runs'][1]['costs']['frontier_tokens']['value'] is None


def test_unknown_state_and_dimension_are_rejected():
    for key, value in [('measurement_state', 'probably-complete'), ('dimension', 'gpu-watts')]:
        data = study()
        observation = data['runs'][0]['cost_observations']['local_compute_ms']
        if key == 'dimension':
            data['runs'][0]['cost_observations'][value] = observation
        else:
            observation[key] = value
        with pytest.raises(ValueError):
            build_cost_displacement_report(data)


def test_duplicate_json_keys_fail_in_cli(tmp_path):
    source = FIXTURE.read_text().replace('"value": 2,', '"value": 999, "value": 2,', 1)
    path = tmp_path / 'ambiguous.json'
    path.write_text(source)
    result = subprocess.run([sys.executable, '-m', 'tokenomics.cli', 'compare-costs', str(path)],
                            text=True, capture_output=True)
    assert result.returncode == 1
    assert 'duplicate' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('key', ['study_id', 'task_snapshot_id', 'work_item_id'])
def test_study_identities_are_explicit_nonempty_strings(key):
    data = study()
    if key == 'study_id':
        data[key] = 42
    else:
        data['work_items'][0][key] = 42
        for run in data['runs'][:2]:
            run[key] = 42
    with pytest.raises(ValueError):
        build_cost_displacement_report(data)


def test_conflicting_aggregate_suppresses_savings_and_reports_reconciliation():
    data = study()
    data['runs'][1]['events'][1]['usage']['input_tokens'] = 1400
    report = build_cost_displacement_report(data)
    assert report['runs'][1]['costs']['total_model_tokens']['reconciliation_delta'] == 1000
    assert report['runs'][1]['costs']['total_model_tokens']['value'] is None
    assert report['pairs'][0]['finding'] == 'inconclusive'


@pytest.mark.parametrize('field,value', [('task_snapshot_id', 'other-task'), ('arm_id', 'baseline'), ('experiment_id', 'other-study')])
def test_canonical_experiment_identity_cannot_disagree_with_wrapper(field, value):
    data = study()
    data['runs'][1]['events'][0]['experiment'] = {field: value}
    with pytest.raises(ValueError, match='experiment identity'):
        build_cost_displacement_report(data)


def test_event_ids_are_explicit_and_study_wide_unique():
    data = study()
    del data['runs'][0]['events'][0]['event_id']
    with pytest.raises(ValueError):
        build_cost_displacement_report(data)
    data = study()
    data['runs'][1]['events'][0]['event_id'] = data['runs'][0]['events'][0]['event_id']
    data['runs'][1]['frontier_event_ids'] = [data['runs'][0]['events'][0]['event_id']]
    with pytest.raises(ValueError, match='event_id'):
        build_cost_displacement_report(data)


def test_synthetic_origin_is_machine_readable():
    report = build_cost_displacement_report(study())
    assert report['evidence_origin'] == 'synthetic'
    assert report['evidence_level'] == 'synthetic_example'


def test_replay_and_credit_lineage_is_preserved_and_qualified():
    data = study()
    data['runs'][1]['events'][0]['experiment'] = {'reuse_kind': 'offline_replay', 'production_credit_eligible': False, 'original_event_ref': 'original:run'}
    report = build_cost_displacement_report(data)
    assert report['runs'][1]['experiment_lineage'][0]['reuse_kind'] == 'offline_replay'
    assert report['pairs'][0]['finding'] == 'inconclusive'
    assert report['pairs'][0]['comparison_limitations'] == ['reused_or_ineligible_evidence']


def test_tied_latest_aggregate_conflicts_are_order_independent():
    data = study()
    events = data['runs'][1]['events']
    conflict = deepcopy(events[1])
    conflict.update(event_id='conflicting-aggregate', span_id='abcdefabcdef1234')
    conflict['usage']['input_tokens'] = 1400
    events.append(conflict)
    for ordered in (events, list(reversed(events))):
        data['runs'][1]['events'] = ordered
        report = build_cost_displacement_report(data)
        assert report['pairs'][0]['finding'] == 'inconclusive'
        metric = report['runs'][1]['costs']['total_model_tokens']
        assert metric['aggregate_conflict'] is True
        assert metric['aggregate_reported'] is None
        assert metric['value'] is None
