"""R10 metrics and offline scenario contract."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def test_final_metrics_separate_automatic_and_review_denominators():
    from tools.evaluate_recognition_final import summarize
    rows=[
        {'expected':{'media_type':'tv','tmdb_id':1,'season':1,'episode':1},'actual':{'media_type':'tv','tmdb_id':1,'season':1,'episode':1},'pending':None,'ai_calls':0,'tmdb_calls':1,'tvmaze_calls':0},
        {'expected':{'media_type':'tv','tmdb_id':2,'season':1,'episode':1},'actual':None,'pending':{'identity_status':'confirmed','tmdb_id':2,'media_type':'tv','numbering_status':'unknown'},'ai_calls':1,'tmdb_calls':0,'tvmaze_calls':0},
        {'expected':None,'actual':{'media_type':'tv','tmdb_id':3},'pending':None,'ai_calls':0,'tmdb_calls':1,'tvmaze_calls':0},
        {'expected':None,'actual':None,'pending':None,'ai_calls':0,'tmdb_calls':0,'tvmaze_calls':0}]
    result=summarize(rows)
    assert result['auto_accuracy']==0.5 and result['correct_coverage']==0.25
    assert result['eligible_coverage']==0.5 and result['eligible_total']==2
    assert result['wrong_auto']==1 and result['unsafe_auto']==1 and result['review']==2
    assert result['identity_known_numbering_pending']==1
    assert summarize([rows[-1]])['auto_accuracy'] is None


def test_offline_final_scenarios_retain_b00_case_version_and_isolate_environment(tmp_path):
    path=tmp_path/'report.json';markdown=tmp_path/'report.md'; sentinel=tmp_path/'user-config.json';sentinel.write_text('untouched')
    import os
    env=os.environ.copy();env.update(CONFIG_PATH=str(sentinel),CACHE_PATH=str(tmp_path),LOG_PATH=str(tmp_path),
        TMDB_API_KEY='secret-sentinel',SOURCE_FOLDERS='/mnt/data',PYTHONDONTWRITEBYTECODE='1')
    command=[sys.executable,str(ROOT/'tools/evaluate_recognition_final.py'),'--output',str(path),'--markdown',str(markdown)]
    run=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=90,check=True)
    assert 'secret-sentinel' not in run.stdout+run.stderr+path.read_text()
    report=json.loads(path.read_text());baseline=json.loads((ROOT/'tests/fixtures/recognition_baseline.json').read_text())
    assert report['fixture_sha256']==baseline['fixture_sha256']
    assert len(report['cases'])==49 and len(report['scenarios'])==4
    assert all(len(row['scenarios'])==4 for row in report['cases'])
    assert report['scenarios']['ai_off_cold']['total']==49
    assert report['scenarios']['ai_off_cold']['correct_auto']>0
    assert report['method']['network_attempts']==0 and report['method']['external_process_attempts']==0
    base=subprocess.run([sys.executable,str(ROOT/'tools/evaluate_recognition.py')],cwd=tmp_path,env=env,
                        capture_output=True,text=True,timeout=45,check=True)
    original=json.loads(base.stdout)
    expected={row['case_id']:row for row in original['cases']}
    for row in report['cases']:
        measured=row['scenarios']['ai_off_cold']
        assert measured['actual']==expected[row['case_id']]['actual']
        assert measured['tmdb_calls']==expected[row['case_id']]['tmdb_calls']
    assert report['extension']['fixture_version']=='r10-extension-v1'
    assert len(report['extension']['cases'])==6
    assert report['extension']['scenarios']['ai_off_cold']['unsafe_auto']==0
    assert report['extension']['scenarios']['ai_off_cold']['correct_auto']==5
    assert report['extension']['acceptance']['ai_off_cold']['passed']
    assert report['extension']['cold_warm_decision_differences']=={'ai_off':[], 'ai_on':[]}
    assert all('candidate_ids' in row['scenarios']['ai_off_cold'] for row in report['cases'])
    assert sentinel.read_text()=='untouched'
    assert '/mnt/data' not in path.read_text() and str(tmp_path) not in path.read_text()
    assert '固定集' in markdown.read_text() and '独立扩展集' in markdown.read_text()
    assert str(tmp_path) not in markdown.read_text()


def test_report_refuses_to_overwrite_existing_file(tmp_path):
    sentinel=tmp_path/'protected.json';sentinel.write_text('keep')
    result=subprocess.run([sys.executable,str(ROOT/'tools/evaluate_recognition_final.py'),'--output',str(sentinel)],
                          cwd=tmp_path,capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and sentinel.read_text()=='keep'
