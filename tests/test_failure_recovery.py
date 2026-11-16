"""T07 bounded retries, fingerprint invalidation and confidence provenance."""
from pathlib import Path
import json

import pytest

@pytest.mark.parametrize('category',['transient','no_match','invalid_input','conflict'])
def test_failure_policy_is_bounded_and_rechecks_changed_inputs(category,tmp_path):
    from core.failure_policy import make_failure,should_retry
    src=tmp_path/'input.mkv';src.write_bytes(b'one')
    config={'tmdb_api':{'language':'zh-CN'}}
    first=make_failure(src,'failure',config,category=category,now=100)
    assert first['failure_category']==category and first['attempt_count']==1
    assert first['last_error']=='failure'
    assert not should_retry(src,first,config,now=100)
    assert should_retry(src,first,config,now=10000)==(category=='transient')
    if category=='transient':
        second=make_failure(src,'again',config,previous=first,category=category,now=10000)
        third=make_failure(src,'again',config,previous=second,category=category,now=20000)
        assert third['attempt_count']==3
        assert not should_retry(src,third,config,now=100000)
    assert should_retry(src,first,{'tmdb_api':{'language':'ja-JP'}},now=100)
    src.write_bytes(b'changed content')
    assert should_retry(src,first,config,now=100)
    assert make_failure(src,'new input',config,previous=first,category=category,now=100)['attempt_count']==1
    first['no_retry']=True
    assert not should_retry(src,first,config,now=100000)


def test_legacy_failed_record_is_reevaluated_once_then_stops(config_file,tmp_path,monkeypatch):
    from core import cache_manager,config_manager,processor_runner as runner
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)])
    cache_manager.save_cache({str(src):{'media_type':'failed','fingerprint':cache_manager.get_file_fingerprint(src)}})
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    calls=[]
    monkeypatch.setattr(runner,'process_video',lambda *a:calls.append(1) or False)
    for _ in range(2):
        runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert len(calls)==1
    saved=cache_manager.load_cache()[str(src)]
    assert saved['failure_category']=='no_match' and saved['attempt_count']==1
    backups=list(tmp_path.glob(cache_manager.CACHE_FILE+'.t07-*.bak'))
    assert len(backups)==1
    assert 'failure_category' not in json.loads(backups[0].read_text())[str(src)]
    src.write_bytes(b'updated source')
    runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert len(calls)==2


def test_network_failure_is_not_cached_as_permanent_no_match(config_file,tmp_path,monkeypatch):
    import requests
    from core import cache_manager,config_manager,processor_runner as runner,tmdb_client
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)])
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    class Session:
        def get(self,*a,**k):
            raise requests.Timeout('mock timeout')
    monkeypatch.setattr(tmdb_client,'create_session',lambda *a:Session())
    def process(src,cfg,result,log):
        return bool(tmdb_client.get_tmdb_details('movie',1,'dummy-key'))
    monkeypatch.setattr(runner,'process_video',process)
    result=runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert result['failed']==1
    saved=cache_manager.load_cache()[str(src)]
    assert saved['failure_category']=='transient' and saved['retry_after']>saved['failed_time']
    assert 'timeout' in saved['last_error'].lower()


@pytest.mark.parametrize('endpoint',['/api/processed/retry','/api/processed_cache/retry'])
def test_automatic_retry_keeps_algorithm_confidence(endpoint,client,config_file,tmp_path,monkeypatch):
    from web import routes_failed
    from core import processor_core,cache_manager
    src=tmp_path/'source'/'input.mkv';src.parent.mkdir();src.write_bytes(b'original')
    cfg=json.loads(config_file.read_text());cfg['source_folders']=[str(src.parent)]
    config_file.write_text(json.dumps(cfg))
    def process(src,cfg,result,callback):
        target=Path(cfg['movie_target_folder'])/'new.mkv';target.parent.mkdir(parents=True,exist_ok=True);target.hardlink_to(src)
        result[str(src)]={'target':str(target),'media_type':'movie','confidence':67}
        return True
    monkeypatch.setattr(processor_core,'process_video',process)
    monkeypatch.setattr(routes_failed,'process_video',process)
    assert client.post(endpoint,json={'src_path':str(src)},auth=('test-user','test-pass')).status_code==200
    entry=cache_manager.load_cache()[str(src)]
    assert entry['confidence']==67 and not entry.get('confirmed_by_user')


def test_manual_confirmation_is_separate_from_algorithm_confidence(config_file,tmp_path,monkeypatch):
    from core import config_manager,tmdb_client
    from core.processor_manual import process_video_with_manual_correction
    config=config_manager.load_config(config_file);config.update(download_images=False,subtitle={'enabled':False})
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'title':'Manual'})
    result={}
    assert process_video_with_manual_correction(src,config,result,1,'movie',1,1)
    assert result[str(src)]['confirmed_by_user'] is True
    assert result[str(src)]['confidence'] is None


@pytest.mark.parametrize('incremental',[True,False])
def test_no_retry_is_preserved_even_on_full_runs(incremental,config_file,tmp_path,monkeypatch):
    from core import processor_runner as runner,cache_manager,config_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)],incremental=incremental)
    entry={'media_type':'failed','no_retry':True,'failed_reason':'user deferred'}
    cache_manager.save_cache({str(src):entry})
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    monkeypatch.setattr(runner,'process_video',lambda *a:pytest.fail('manual no_retry ignored'))
    runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert cache_manager.load_cache()[str(src)]==entry


@pytest.mark.parametrize('existing_success',[False,True])
def test_runner_transient_retry_budget_and_backoff(existing_success,config_file,tmp_path,monkeypatch):
    import requests
    from core import processor_runner as runner,cache_manager,config_manager,failure_policy
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)])
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    if existing_success:
        cache_manager.save_cache({str(src):{'media_type':'movie','target':str(tmp_path/'missing-target.mkv')}})
    calls=[];clock=[100]
    monkeypatch.setattr(failure_policy.time,'time',lambda:clock[0])
    def process(*a):
        calls.append(1)
        raise requests.Timeout('mock timeout')
    monkeypatch.setattr(runner,'process_video',process)
    for now in [100,100,160,160,280,10000]:
        clock[0]=now
        runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert len(calls)==3
    entry=cache_manager.load_cache()[str(src)]
    if existing_success:
        assert entry['media_type']=='movie'
        entry=entry['last_failure']
    assert entry['attempt_count']==3 and entry['failure_category']=='transient' and entry['retry_after'] is None


@pytest.mark.parametrize('code,category',[(401,'invalid_input'),(429,'transient'),(503,'transient')])
def test_http_failure_category_does_not_leak_api_key(code,category,tmp_path):
    import requests
    from core.failure_policy import failure_scope,note_error,make_failure
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    response=requests.Response();response.status_code=code
    error=requests.HTTPError('https://example.invalid?api_key=private-value',response=response)
    with failure_scope({}):
        note_error(error)
        entry=make_failure(src,str(error))
    assert entry['failure_category']==category
    assert 'private-value' not in json.dumps(entry)


def test_fresh_no_match_replaces_prior_transient_diagnostics(config_file,tmp_path,monkeypatch):
    from core import processor_runner as runner,cache_manager,config_manager,failure_policy
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)])
    old=failure_policy.make_failure(src,'old timeout',config,category='transient',now=100)
    cache_manager.save_cache({str(src):old})
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    monkeypatch.setattr(runner,'process_video',lambda *a:False)
    runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    entry=cache_manager.load_cache()[str(src)]
    assert entry['failure_category']=='no_match' and entry['retry_after'] is None
    assert 'old timeout' not in entry['last_error']


def test_full_run_failure_keeps_valid_record_and_persists_diagnostic(config_file,tmp_path,monkeypatch):
    from core import processor_runner as runner,cache_manager,config_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    target=tmp_path/'old.mkv';target.hardlink_to(src)
    old={'media_type':'movie','title':'Old','target':str(target),'confidence':72}
    cache_manager.save_cache({str(src):old})
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)],incremental=False)
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    monkeypatch.setattr(runner,'process_video',lambda *a:False)
    runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    entry=cache_manager.load_cache()[str(src)]
    assert all(entry[key]==value for key,value in old.items())
    assert entry['last_failure']['failure_category']=='no_match'
    assert target.read_bytes()==src.read_bytes()==b'original'


@pytest.mark.parametrize('order',['asc','desc'])
def test_confidence_sort_accepts_unknown_manual_score(order,client,tmp_path):
    from core import cache_manager
    cache_manager.save_cache({'manual':{'media_type':'movie','confidence':None,'confirmed_by_user':True},
                              'automatic':{'media_type':'movie','confidence':67}})
    response=client.get('/api/processed_cache?sort=confidence&order='+order,auth=('test-user','test-pass'))
    assert response.status_code==200
    assert [entry['src'] for entry in response.json['items']]==['automatic','manual']
