"""B00 evaluates real decisions offline without asserting current defects as correct."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/evaluate_recognition.py'
FIXTURES = ROOT / 'tests/fixtures/recognition_cases.json'


def run_tool(tmp_path, sentinel):
    env = os.environ.copy()
    env.update(CONFIG_PATH=str(sentinel), CACHE_PATH=str(sentinel.parent),
               LOG_PATH=str(sentinel.parent), TMDB_API_KEY='never-use-this',
               SOURCE_FOLDERS=str(sentinel.parent), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, str(TOOL)], cwd=tmp_path, env=env,
                            capture_output=True, text=True, check=True, timeout=45)
    assert 'never-use-this' not in result.stdout + result.stderr
    return json.loads(result.stdout)


def test_evaluation_reproducible_and_isolated(tmp_path):
    sentinel = tmp_path / 'user-config.json'
    sentinel.write_text('do not read or overwrite')
    before = sorted(p.name for p in tmp_path.iterdir())
    first = run_tool(tmp_path, sentinel)
    second = run_tool(tmp_path, sentinel)
    assert first == second
    assert sentinel.read_text() == 'do not read or overwrite'
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert len(first['cases']) >= 40
    assert len(first['fixture_sha256']) == 64
    assert first['metrics']['ai_calls'] == 0
    assert first['metrics']['tmdb_calls'] > 0
    assert first['metrics']['correct_auto'] > 0
    assert any(r['category'] == 'movie' and r['actual'] == r['expected'] for r in first['cases'])
    assert any(r['category'] == 'tv' and r['actual'] == r['expected'] for r in first['cases'])
    assert any(r['category'] == 'network' for r in first['cases'])
    assert first['splits']['heldout']['total'] > 0


def test_metrics_counts_rejection_and_wrong_acceptance():
    from tools.evaluate_recognition import metrics
    rows = [
        {'actual': {'id': 1}, 'expected': {'id': 1}, 'ai_calls': 0, 'tmdb_calls': 1},
        {'actual': {'id': 2}, 'expected': {'id': 1}, 'ai_calls': 1, 'tmdb_calls': 2},
        {'actual': {'id': 3}, 'expected': None, 'ai_calls': 0, 'tmdb_calls': 1},
        {'actual': None, 'expected': None, 'ai_calls': 0, 'tmdb_calls': 0},
    ]
    value = metrics(rows)
    assert (value['correct_auto'], value['incorrect_auto'], value['review_expected_but_auto'], value['review']) == (1, 2, 1, 1)
    assert value['auto_accuracy'] == 1 / 3
    assert value['correct_coverage'] == 1 / 4
    assert metrics([rows[-1]])['auto_accuracy'] is None


def test_fixture_scope_and_network_failure_are_present():
    data = json.loads(FIXTURES.read_text())
    cases = data['cases']
    assert len(cases) >= 40
    assert len({case['case_id'] for case in cases}) == len(cases)
    assert {'tv', 'movie', 'special', 'numeric', 'decimal', 'range', 'conflict',
            'network', 'absolute', 'multilingual', 'same-title', 'sequel'} <= {c['category'] for c in cases}
    assert all(c['basis'] and c['split'] in {'development', 'heldout'} for c in cases)
    assert any(c['network_error'] for c in cases)


def test_fixture_rejects_paths_outside_sandbox():
    import pytest
    from tools.evaluate_recognition import _component
    for value in ('../media', '/mnt/data', '.', '', 'foo/bar', 'foo\\bar'):
        with pytest.raises(ValueError):
            _component(value)
