from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tokenomics.jsonl import iter_jsonl
from tokenomics.models import TokenomicsEvent


def event():
    return TokenomicsEvent(
        kind='task', name='validation-fixture', event_id='fixture-event',
        trace_id='a' * 32, span_id='b' * 16, ts=1,
    ).to_dict()


def validate(path: Path):
    return subprocess.run([sys.executable, '-m', 'tokenomics.cli', 'validate', str(path)],
                          text=True, capture_output=True)


@pytest.mark.parametrize('contents', ['', '\n  \n\t\n', 'one', 'multiple'])
def test_validate_accepts_empty_blank_and_valid_files(tmp_path, contents):
    valid = json.dumps(event())
    if contents == 'one':
        contents = valid + '\n'
    elif contents == 'multiple':
        contents = '\n' + valid + '\n\n' + valid + '\n'
    path = tmp_path / 'valid.jsonl'
    path.write_text(contents)
    result = validate(path)
    assert result.returncode == 0
    assert result.stdout == 'ok\n'
    assert result.stderr == ''


@pytest.mark.parametrize('bad_row', ['{', 'not JSON', 'null', '[]', '42', '"text"', '{}'])
def test_validate_rejects_malformed_rows_at_the_physical_line(tmp_path, bad_row):
    path = tmp_path / 'malformed.jsonl'
    path.write_text('\n' + json.dumps(event()) + '\n' + bad_row + '\n')
    result = validate(path)
    assert result.returncode == 1
    assert result.stdout == ''
    assert f'{path}:3:' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('change', ['schema', 'trace_id', 'outcome'])
def test_validate_rejects_invalid_events_without_a_traceback(tmp_path, change):
    invalid = event()
    invalid[change] = {'schema': 'tokenomics.event.future', 'trace_id': 'short',
                       'outcome': 'not-an-outcome-object'}[change]
    path = tmp_path / 'invalid-event.jsonl'
    path.write_text(json.dumps(invalid) + '\n')
    result = validate(path)
    assert result.returncode == 1
    assert result.stdout == ''
    assert f'{path}:1:' in result.stderr
    assert 'Traceback' not in result.stderr
    if change == 'schema':
        assert 'unsupported schema' in result.stderr


@pytest.mark.parametrize('kind', ['missing', 'directory'])
def test_validate_rejects_nonfiles(tmp_path, kind):
    path = tmp_path / kind
    if kind == 'directory':
        path.mkdir()
    result = validate(path)
    assert result.returncode == 1
    assert result.stdout == ''
    assert str(path) in result.stderr
    assert 'regular JSONL file' in result.stderr
    assert 'Traceback' not in result.stderr


def test_validate_reports_each_invalid_row_and_never_prints_ok(tmp_path):
    path = tmp_path / 'multiple-errors.jsonl'
    path.write_text('{\n\n' + json.dumps(event()) + '\nnot JSON\n')
    result = validate(path)
    assert result.returncode == 1
    assert result.stdout == ''
    assert f'{path}:1:' in result.stderr
    assert f'{path}:4:' in result.stderr


def test_validate_reports_non_utf8_without_a_traceback(tmp_path):
    path = tmp_path / 'non-utf8.jsonl'
    path.write_bytes(b'\xff\n')
    result = validate(path)
    assert result.returncode == 1
    assert result.stdout == ''
    assert str(path) in result.stderr
    assert 'Traceback' not in result.stderr


def test_tolerant_ingestion_keeps_its_existing_skip_behavior(tmp_path):
    unsupported = event()
    unsupported['schema'] = 'tokenomics.event.future'
    path = tmp_path / 'mixed.jsonl'
    path.write_text(json.dumps(event()) + '\nnot JSON\n' + json.dumps(unsupported) + '\n')
    rows = list(iter_jsonl(path))
    assert len(rows) == 1
    assert rows[0].event_id == 'fixture-event'
    assert list(iter_jsonl(tmp_path / 'missing.jsonl')) == []


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity'])
def test_validate_rejects_non_json_numbers_inside_an_event(tmp_path, constant):
    path = tmp_path / 'non-json-number.jsonl'
    contents = json.dumps(event()).replace('"ts": 1', f'"ts": {constant}')
    path.write_text(contents + '\n')
    result = validate(path)
    assert result.returncode == 1
    assert result.stdout == ''
    assert f'{path}:1:' in result.stderr
    assert 'non-JSON numeric constant' in result.stderr
    assert 'Traceback' not in result.stderr
