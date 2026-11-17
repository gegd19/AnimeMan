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
    assert report['acceptance_policy']=='identity-evidence-approved-v1'
    assert all(result['passed'] for result in report['approved_acceptance'].values())
    evidence=report['evidence_suite']
    assert evidence['fixture_version']=='identity-evidence-v1' and len(evidence['cases'])==6
    for scenario,metrics in evidence['scenarios'].items():
        assert metrics['correct_auto']==4 and metrics['eligible_total']==4
        assert metrics['unsafe_auto']==0 and metrics['wrong_auto']==0 and metrics['review']==2
        assert evidence['acceptance'][scenario]['passed']
    assert evidence['cold_warm_decision_differences']=={'ai_off':[], 'ai_on':[]}


def test_approved_gate_requires_review_and_all_other_normal_cases():
    from tools.evaluate_recognition_identity import adjudicate
    expected=lambda ident:{'media_type':'tv','tmdb_id':ident,'season':1,'episode':1}
    scenario='ai_off_cold'
    fixed=[{'case_id':'C46','expected':expected(46),'scenarios':{scenario:{'actual':None}}},
           {'case_id':'C49','expected':expected(49),'scenarios':{scenario:{'actual':None}}},
           {'case_id':'C01','expected':expected(1),'scenarios':{scenario:{'actual':expected(1)}}}]
    evidence=[]
    for number in (46,49):
        for suffix,kind in (('N','none'),('T','tmdb'),('M','manual')):
            target=None if suffix=='N' else expected(number)
            evidence.append({'case_id':f'I{number}{suffix}','ground_truth':expected(number),
                             'evidence_kind':kind,'expected':target,'scenarios':{scenario:{'actual':target}}})
    full={'cases':fixed,'scenarios':{scenario:{'unsafe_auto':0,'runtime_errors':0}},
          'extension':{'fixture_version':'identity-evidence-v1',
                       'fixture_sha256':'c37d135ba24dc5213e655373009401c44303888538e54411c772a1315b3c5e9f',
                       'cases':evidence,'acceptance':{scenario:{'passed':True}}}}
    result=adjudicate(full)[scenario]
    assert result['passed'] and result['evidence_required_review']==['C46','C49']
    fixed[0]['scenarios'][scenario]['actual']=expected(46)
    assert not adjudicate(full)[scenario]['passed']
    fixed[0]['scenarios'][scenario]['actual']=None
    fixed[2]['scenarios'][scenario]['actual']=None
    assert not adjudicate(full)[scenario]['passed']
    fixed[2]['scenarios'][scenario]['actual']=expected(1)
    full['extension']['acceptance'][scenario]['passed']=False
    assert not adjudicate(full)[scenario]['passed']
    full['extension']['acceptance'][scenario]['passed']=True
    full['scenarios'][scenario]['unsafe_auto']=1
    assert not adjudicate(full)[scenario]['passed']
    full['scenarios'][scenario]['unsafe_auto']=0
    full['extension']['fixture_sha256']='tampered'
    assert not adjudicate(full)[scenario]['passed']
    full['extension']['fixture_sha256']='c37d135ba24dc5213e655373009401c44303888538e54411c772a1315b3c5e9f'
    evidence[1]['scenarios'][scenario]['actual']=None
    assert not adjudicate(full)[scenario]['passed']
