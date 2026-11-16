"""T13: reject bad input before effects; all paths/configs are temporary."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading

import pytest

from core import config_manager as configs

AUTH = ('test-user', 'test-pass')


def test_loaded_defaults_are_independent(config_file, monkeypatch):
    defaults = deepcopy(configs.DEFAULT_CONFIG)
    monkeypatch.setattr(configs, 'DEFAULT_CONFIG', deepcopy(defaults))
    config_file.write_text('{}')
    one = configs.load_config(config_file)
    one['source_folders'].append('/changed')
    one['special_mappings'][0]['keyword'] = 'changed'
    one['scan_policy']['exclude_patterns'].append('changed')
    two = configs.load_config(config_file)
    assert configs.DEFAULT_CONFIG == defaults
    assert two['source_folders'] == defaults['source_folders']
    assert two['special_mappings'] == defaults['special_mappings']
    assert two['scan_policy'] == defaults['scan_policy']


@pytest.mark.parametrize('raw', [
    '{not json', 'null', '[]', '{"auth":null}', '{"auth":{"enabled":true}}',
    '{"max_workers":0}', '{"max_workers":NaN}',
    '{"auth":{"enabled":true,"username":"u","password":"p"},"auth":{"enabled":false}}',
])
def test_corrupt_config_never_falls_back_or_changes_original(config_file, raw):
    config_file.write_text(raw)
    with pytest.raises((ValueError, OSError)):
        configs.load_config(config_file)
    assert config_file.read_text() == raw


@pytest.mark.parametrize('raw', ['{broken', '[]', '{"max_workers":0}'])
def test_saving_does_not_overwrite_corrupt_existing_config(config_file, raw):
    config_file.write_text(raw)
    with pytest.raises((ValueError, OSError)):
        configs.save_config({'max_workers': 4}, config_file)
    assert config_file.read_text() == raw


BAD_CONFIGS = [
    {'max_workers': 0}, {'max_workers': True}, {'max_workers': '3'}, {'max_workers': 33},
    {'source_folders': 'source'}, {'source_folders': ['bad\0path']},
    {'dry_run': 'false'}, {'incremental': 1}, {'link_type': 'invalid'},
    {'subtitle': []}, {'subtitle': {'sync_timeout': 0}},
    {'subtitle': {'auto_sync': 'false'}}, {'subtitle_center': {'auto_match_threshold': 101}},
    {'ai_parser': {'temperature': float('nan')}}, {'ai_parser': {'max_tokens': True}},
    {'ai_parser': {'timeout': -1}}, {'ai_parser': {'provider': 'invalid'}},
    {'auth': {'enabled': 'false'}}, {'min_file_size_mb': -1}, {'tmdb_rate_limit': -1},
    {'scan_policy': {'exclude_patterns': [1]}},
    {'special_mappings': [{'keyword':'SP','tmdb_id':1,'media_type':'tv','season':-1,'episode':0}]},
]


@pytest.mark.parametrize('patch', BAD_CONFIGS)
def test_config_save_validates_before_replacing(config_file, patch):
    current = configs.load_config(config_file)
    before = config_file.read_bytes()
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            current[key].update(value)
        else:
            current[key] = value
    with pytest.raises(ValueError):
        configs.save_config(current, config_file)
    assert config_file.read_bytes() == before
    assert not list(config_file.parent.glob(config_file.name+'*.tmp'))


@pytest.mark.parametrize('patch', BAD_CONFIGS)
def test_invalid_config_patch_is_json_error_and_keeps_file(client, config_file, patch):
    before = config_file.read_bytes()
    response = client.post('/api/config', auth=AUTH, json=patch)
    assert response.status_code in (400, 422)
    assert isinstance(response.json, dict) and response.json.get('message')
    assert config_file.read_bytes() == before


BODY_ENDPOINTS = [
    '/api/config', '/api/media/delete', '/api/media/batch_delete',
    '/api/processed_cache/delete', '/api/processed_cache/batch_delete', '/api/processed_cache/retry',
    '/api/processed/retry', '/api/failed_cache/correct', '/api/failed_cache/batch_correct',
    '/api/subtitle/match', '/api/subtitle/scan', '/api/subtitle/execute',
    '/api/subtitle/batch_rename', '/api/subtitle/ai_parse', '/api/subtitle/ai_match',
    '/api/subtitle/match_single', '/api/special_mappings', '/api/ai/stream_enhance', '/api/run',
]


@pytest.mark.parametrize('endpoint', BODY_ENDPOINTS)
@pytest.mark.parametrize('raw', ['null', '[]', '"text"', 'true'])
def test_non_object_json_is_rejected_consistently(client, endpoint, raw, monkeypatch):
    from web import task_state
    monkeypatch.setattr(task_state, 'launch_task', lambda *a, **k: None)
    response = client.post(endpoint, auth=AUTH, data=raw, content_type='application/json')
    assert response.status_code in (400, 422)
    assert isinstance(response.json, dict)
    assert response.json.get('message')


@pytest.mark.parametrize('content_type,raw', [('application/json','{bad'), ('text/plain','{}')])
def test_invalid_json_is_not_an_html_error_page(client, content_type, raw):
    response = client.post('/api/subtitle/match', auth=AUTH, data=raw, content_type=content_type)
    assert response.status_code == 400
    assert response.json['code'] == 'invalid_request'


@pytest.mark.parametrize('query', ['page=x', 'page=-1', 'page=0', 'page=true', 'per_page=0',
    'per_page=-1','per_page=201','per_page=1.5','page=1&page=2','sort=invalid','order=invalid'])
def test_pagination_rejected_before_cache_read(client, monkeypatch, query):
    from core import cache_manager
    monkeypatch.setattr(cache_manager, 'load_cache', lambda: pytest.fail('invalid request reached cache'))
    response = client.get('/api/processed_cache?'+query, auth=AUTH)
    assert response.status_code in (400, 422)
    assert response.json['code'] == 'invalid_request'


@pytest.fixture
def allowed_media(tmp_path, config_file):
    source = tmp_path / 'source'
    source.mkdir()
    video = source / 'input.mkv'
    video.write_bytes(b'test video')
    subtitle = source / 'input.chs.ass'
    subtitle.write_text('test subtitle')
    cfg = configs.load_config(config_file)
    cfg['source_folders'] = [str(source)]
    configs.save_config(cfg, config_file)
    return video, subtitle, cfg


@pytest.mark.parametrize('field,value', [('tmdb_id',True),('tmdb_id','1'),('tmdb_id',-1),
    ('media_type','invalid'),('season',True),('season',-1),('episode',0),('episode','1')])
def test_correction_rejects_invalid_numbers_before_processing(client, allowed_media, monkeypatch, field, value):
    from web import routes_failed
    calls = []
    monkeypatch.setattr(routes_failed, 'reprocess_safely', lambda *a, **k: (calls.append(a) or (True, None)))
    video, subtitle, cfg = allowed_media
    payload = {'src_path': str(video), 'tmdb_id': 1, 'media_type': 'tv', 'season': 0, 'episode': 1}
    payload[field] = value
    response = client.post('/api/failed_cache/correct', auth=AUTH, json=payload)
    assert response.status_code in (400,422)
    assert not calls


@pytest.mark.parametrize('endpoint,field', [('/api/media/batch_delete','src_paths'),
    ('/api/processed_cache/batch_delete','src_paths'),('/api/failed_cache/batch_correct','src_paths'),
    ('/api/subtitle/ai_parse','files'),('/api/subtitle/execute','items'),('/api/subtitle/batch_rename','renames')])
def test_batch_limits_before_effects(client, endpoint, field, allowed_media, monkeypatch):
    from web import task_state
    monkeypatch.setattr(task_state, 'launch_task', lambda *a, **k: pytest.fail('started invalid batch'))
    video, subtitle, cfg = allowed_media
    entry = {'path':str(subtitle),'name':subtitle.name}
    if field == 'items': entry = {'subtitle_path':str(subtitle),'target_media':{'target_path':cfg['tv_target_folder']+'/ep.mkv','target_dir':cfg['tv_target_folder']}}
    elif field == 'renames': entry = {'old_path':str(subtitle),'new_path':str(subtitle.with_name('new.ass'))}
    elif field == 'src_paths': entry = str(video)
    response = client.post(endpoint, auth=AUTH, json={field:[entry]*1001,'tmdb_id':1})
    assert response.status_code in (400,422)


def test_subtitle_batch_validates_every_item_before_first_write(client, allowed_media, monkeypatch):
    from core import subtitle_handler
    calls=[]
    monkeypatch.setattr(subtitle_handler,'execute_subtitle_organization',lambda *a,**k: calls.append(a) or True)
    video, subtitle, cfg = allowed_media
    media={'target_path':cfg['tv_target_folder']+'/ep.mkv','target_dir':cfg['tv_target_folder']}
    response=client.post('/api/subtitle/execute',auth=AUTH,json={'items':[
        {'subtitle_path':str(subtitle),'target_media':media,'auto_sync':False},
        {'subtitle_path':str(subtitle),'target_media':media,'auto_sync':'false'}]})
    assert response.status_code in (400,422)
    assert not calls


@pytest.mark.parametrize('value', ['false',0,1,None])
def test_delete_source_is_a_real_boolean(client, allowed_media, value):
    video,subtitle,cfg=allowed_media
    response=client.post('/api/media/delete',auth=AUTH,json={'src_path':str(video),'delete_source':value})
    assert response.status_code in (400,422)
    assert video.read_bytes()==b'test video'


def test_corrupt_auth_document_fails_closed_without_secret_leak(client, config_file):
    raw='{"auth":{"enabled":true,"username":"u","password":"DUMMY-SECRET"},"auth":{"enabled":false}}'
    config_file.write_text(raw)
    response=client.get('/api/config')
    assert response.status_code==503
    assert 'DUMMY-SECRET' not in response.get_data(as_text=True)
    assert config_file.read_text()==raw
    assert client.get('/healthz').status_code==200


def test_mapping_indices_and_duplicate_conflicts(client):
    assert client.delete('/api/special_mappings?index=999',auth=AUTH).status_code==404
    rule={'keyword':'Special','tmdb_id':1,'media_type':'tv','season':0,'episode':1,'enabled':True}
    assert client.post('/api/special_mappings',auth=AUTH,json={'rule':rule}).status_code==200
    assert client.post('/api/special_mappings',auth=AUTH,json={'rule':rule}).status_code==409


def test_concurrent_config_patches_do_not_lose_changes(app, config_file, monkeypatch):
    # Old routes reach save only after independent read/merge; hold both there.
    original=configs.save_config
    gate=threading.Barrier(2)
    def gated_save(*a,**k):
        gate.wait(timeout=3)
        return original(*a,**k)
    monkeypatch.setattr(configs,'save_config',gated_save)
    def patch(value):
        with app.test_client() as client:
            return client.post('/api/config',auth=AUTH,json=value).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(patch,[{'max_workers':4},{'download_images':False}]))
    assert statuses==[200,200]
    current=configs.load_config(config_file)
    assert current['max_workers']==4 and current['download_images'] is False


def test_atomic_config_failure_retains_original_and_cleans_temp(config_file, monkeypatch):
    from core import json_store
    cfg=configs.load_config(config_file)
    before=config_file.read_bytes()
    cfg['max_workers']=4
    def fail(*a,**k): raise OSError('simulated disk failure')
    monkeypatch.setattr(json_store.os,'replace',fail)
    with pytest.raises(OSError): configs.save_config(cfg,config_file)
    assert config_file.read_bytes()==before
    assert not list(config_file.parent.glob(config_file.name+'*.tmp'))


@pytest.mark.parametrize('raw', ['{"src_path":"a","src_path":"b"}', '{"delete_source":false,"delete_source":true}', '{"src_path":NaN}'])
def test_duplicate_and_nonfinite_request_json_is_rejected(client, raw):
    response=client.post('/api/media/delete',auth=AUTH,data=raw,content_type='application/json')
    assert response.status_code==400
    assert response.json['code']=='invalid_request'


@pytest.mark.parametrize('query', ['media_type=invalid','year=-1','year=true','year=2200'])
def test_search_query_validation_prevents_tmdb_calls(client, monkeypatch, query):
    from core import tmdb_cache
    monkeypatch.setattr(tmdb_cache,'get_cached_result',lambda *a,**k: pytest.fail('bad search reached TMDB cache'))
    response=client.get('/api/tmdb/search_proxy?query=test&'+query,auth=AUTH)
    assert response.status_code==400 and response.json['code']=='invalid_request'


@pytest.mark.parametrize('patch', [{'browse_roots':'folder'},{'browse_roots':['bad\0path']},
    {'ai_parser':{'folder_wait_timeout':0}},{'tv_target_folder':'bad\ud800path'}])
def test_optional_config_types_and_encoding_are_validated(client, config_file, patch):
    before=config_file.read_bytes()
    response=client.post('/api/config',auth=AUTH,json=patch)
    assert response.status_code==400
    assert config_file.read_bytes()==before


def test_config_cannot_save_a_document_its_loader_would_reject(config_file):
    cfg=configs.load_config(config_file)
    cfg['extension_data']='中'*(2*1024*1024)
    before=config_file.read_bytes()
    with pytest.raises(ValueError): configs.save_config(cfg,config_file)
    assert config_file.read_bytes()==before


def test_deep_config_is_rejected_before_default_merge(config_file):
    nested='{}'
    for _ in range(100):nested='{"x":'+nested+'}'
    config_file.write_text(nested)
    with pytest.raises((OSError,ValueError)): configs.load_config(config_file)
    assert config_file.read_text()==nested


def test_config_post_failure_is_json_and_preserves_original(client, config_file, monkeypatch):
    from core import json_store
    before=config_file.read_bytes()
    def fail(*a,**k):raise OSError('mock disk failure')
    monkeypatch.setattr(json_store.os,'replace',fail)
    response=client.post('/api/config',auth=AUTH,json={'max_workers':4})
    assert response.status_code==500
    assert response.json['code']=='config_write_failed'
    assert config_file.read_bytes()==before
    assert not list(config_file.parent.glob(config_file.name+'*.tmp'))


def test_config_backup_retains_bad_bytes_with_private_permissions(config_file):
    original=b'{invalid-DUMMY-SECRET'
    config_file.write_bytes(original)
    with pytest.raises((ValueError,OSError)):configs.load_config(config_file)
    backups=list(config_file.parent.glob(config_file.name+'.t13-invalid-*.bak'))
    assert len(backups)==1 and backups[0].read_bytes()==original
    assert backups[0].stat().st_mode & 0o777==0o600


def test_config_environment_and_mapping_updates_do_not_persist_overrides(client, config_file, monkeypatch):
    stored=json.loads(config_file.read_text())
    monkeypatch.setenv('TV_TARGET_FOLDER',str(config_file.parent/'environment-tv'))
    rule={'keyword':'ZeroSeason','tmdb_id':3,'media_type':'tv','season':0,'episode':1,'enabled':True}
    assert client.post('/api/special_mappings',auth=AUTH,json={'rule':rule}).status_code==200
    assert json.loads(config_file.read_text())['tv_target_folder']==stored['tv_target_folder']
    assert client.get('/api/config',auth=AUTH).json['tv_target_folder'].endswith('environment-tv')


@pytest.mark.parametrize('rule', [None,[],{'keyword':1},
    {'keyword':'SP','tmdb_id':True,'media_type':'movie'},
    {'keyword':'SP','tmdb_id':1,'media_type':'tv','season':0,'episode':0},
    {'keyword':'SP','tmdb_id':1,'media_type':'movie','enabled':'false'}])
def test_invalid_mapping_is_rejected_without_writing(client, config_file, rule):
    before=config_file.read_bytes()
    response=client.post('/api/special_mappings',auth=AUTH,json={'rule':rule})
    assert response.status_code==400
    assert config_file.read_bytes()==before


def test_per_page_and_batch_exact_limits_remain_usable(client, config_file):
    assert client.get('/api/processed_cache?page=1&per_page=200',auth=AUTH).status_code==200
    paths=[str(config_file.parent/f'unknown-{i}.mkv') for i in range(1000)]
    response=client.post('/api/processed_cache/batch_delete',auth=AUTH,json={'src_paths':paths})
    assert response.status_code==200 and response.json['deleted']==0


@pytest.mark.parametrize('enabled',[False,True])
def test_valid_config_boundary_and_auth_secret_round_trip(client, config_file, enabled):
    patch={'max_workers':32,'subtitle_center':{'auto_match_threshold':0},'ai_parser':{'temperature':0},'auth':{'enabled':enabled,'password':''}}
    assert client.post('/api/config',auth=AUTH,json=patch).status_code==200
    cfg=configs.load_config(config_file)
    assert cfg['max_workers']==32 and cfg['ai_parser']['temperature']==0
    assert cfg['auth']['password']=='test-pass' and cfg['auth']['enabled'] is enabled


def test_missing_config_no_create_mode_is_distinct_from_damage(tmp_path):
    path=tmp_path/'nonexistent.json'
    cfg=configs.load_config(path,create_if_missing=False)
    assert not path.exists() and cfg['max_workers']==3
    assert not list(tmp_path.glob('*.bak'))


@pytest.mark.parametrize('prompt',['{unknown}','{title','{title:20}','{title.__class__}'])
def test_bad_stream_prompt_is_rejected_before_streaming(client, config_file, prompt, monkeypatch):
    import requests
    def mock_post(*a, **k): raise requests.RequestException('mock-only failure')
    monkeypatch.setattr(requests.Session, 'post', mock_post)
    cfg=configs.load_config(config_file)
    cfg['ai_parser']['api_key']='dummy-test-key'
    configs.save_config(cfg,config_file)
    response=client.post('/api/ai/stream_enhance',auth=AUTH,json={
        'title':'Title','original_plot':'Plot','ai_config':{'prompt_template':prompt}}, buffered=True)
    assert response.status_code==400
    assert response.is_json


def test_broken_config_symlink_is_not_a_new_installation(client, config_file):
    config_file.unlink()
    destination=config_file.parent/'missing-config.json'
    config_file.symlink_to(destination)
    response=client.get('/api/config')
    assert response.status_code==503
    assert config_file.is_symlink() and not destination.exists()


@pytest.mark.parametrize('sort',['title','confidence'])
def test_history_rejects_sort_fields_not_implemented(client, sort):
    response=client.get('/api/processed_history?sort='+sort,auth=AUTH)
    assert response.status_code==400
    assert response.json['code']=='invalid_request'


@pytest.mark.parametrize('raw',['null','[]','true','"text"'])
def test_delete_with_a_json_body_rejects_non_objects(client, config_file, raw):
    cfg=configs.load_config(config_file)
    cfg['special_mappings']=[{'keyword':'Keep','tmdb_id':1,'media_type':'movie','enabled':True}]
    configs.save_config(cfg,config_file)
    before=config_file.read_bytes()
    response=client.delete('/api/special_mappings?index=0',auth=AUTH,data=raw,content_type='application/json')
    assert response.status_code==400
    assert config_file.read_bytes()==before


def test_movie_batch_keeps_nullable_tv_only_fields(client, allowed_media, monkeypatch):
    from types import SimpleNamespace
    from web import task_state, routes_failed
    video,subtitle,cfg=allowed_media
    launches=[]
    processed=[]
    monkeypatch.setattr(task_state, 'should_stop', lambda: False)
    monkeypatch.setattr(routes_failed, 'reprocess_safely', lambda src, config, run: (run(config, {}), 'success'))
    monkeypatch.setattr(routes_failed, 'process_video_with_manual_correction', lambda *args: processed.append(args) or True)
    def launch(*args,**kwargs):
        launches.append(args)
        return SimpleNamespace(task_id='mock-only')
    monkeypatch.setattr(task_state,'launch_task',launch)
    response=client.post('/api/failed_cache/batch_correct',auth=AUTH,json={
        'src_paths':[str(video)],'tmdb_id':1,'media_type':'movie',
        'season':None,'start_episode':None,'episode_increment':None})
    assert response.status_code==200 and response.json['status']=='started'
    assert len(launches)==1
    result=launches[0][2](launches[0][1], lambda *args: None)
    assert result['success']==1 and result['failed']==0
    assert processed[0][4:7]==('movie',None,None)
