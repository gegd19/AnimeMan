"""The fixed baseline remains unchanged; new evidence is a separate suite."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def test_new_no_evidence_cases_preserve_fixed_observable_inputs():
    base={c['case_id']:c for c in json.loads((ROOT/'tests/fixtures/recognition_cases.json').read_text())['cases']}
    cases=json.loads((ROOT/'tests/fixtures/recognition_identity_evidence_cases.json').read_text())['cases']
    for case in cases:
        original=base['C'+case['case_id'][1:3]]
        assert case['ground_truth']==original['expected']
        if case['evidence_kind']=='none':
            for key in ('folder','filename','search_results','details','seasons','network_error','other_files'):
                assert case[key]==original[key]
            assert case['expected'] is None


def test_separate_evidence_suite_is_offline_and_preserves_historical_acceptance(tmp_path):
    output=tmp_path/'evidence.json';sentinel=tmp_path/'config.json';sentinel.write_text('untouched')
    env=os.environ.copy();env.update(CONFIG_PATH=str(sentinel),CACHE_PATH=str(tmp_path),LOG_PATH=str(tmp_path),
                                     TMDB_API_KEY='secret-sentinel',SOURCE_FOLDERS='/mnt/data',PYTHONDONTWRITEBYTECODE='1')
    command=[sys.executable,str(ROOT/'tools/evaluate_recognition_identity.py'),'--output',str(output)]
    result=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,check=True,timeout=60)
    report=json.loads(output.read_text())
    assert sentinel.read_text()=='untouched'
    assert 'secret-sentinel' not in result.stdout+result.stderr+output.read_text()
    assert str(tmp_path) not in output.read_text() and '/mnt/data' not in output.read_text()
    assert report['fixed_acceptance']['ai_off_cold']['passed'] is False
    assert report['fixed_acceptance']['ai_off_cold']['regressions']==['C46','C49']
    evidence=report['evidence_suite']
    assert evidence['fixture_version']=='identity-evidence-v1' and len(evidence['cases'])==6
    for scenario,metrics in evidence['scenarios'].items():
        assert metrics['correct_auto']==4 and metrics['eligible_total']==4
        assert metrics['unsafe_auto']==0 and metrics['wrong_auto']==0 and metrics['review']==2
        assert evidence['acceptance'][scenario]['passed']
    assert evidence['cold_warm_decision_differences']=={'ai_off':[], 'ai_on':[]}
