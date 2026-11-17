"""E02: explicit, bounded user recognition rules."""
from pathlib import Path
import pytest


def source(tmp_path):
    root=tmp_path/'source';root.mkdir()
    folder=root/'Series';folder.mkdir()
    file=folder/'Show S01E01.mkv';file.write_bytes(b'synthetic')
    return root,folder,file


def test_file_rule_is_exact_and_retains_episode(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    rule=rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    selected=rules.match_rule(file,cfg,{'title':'Show','media_type':'tv','season':1,'episode':1})
    assert selected['id']==rule['id'] and (selected['season'],selected['episode'])==(1,1)
    other=folder/'Show S01E02.mkv';other.write_bytes(b'synthetic')
    assert rules.match_rule(other,cfg,{'title':'Show','media_type':'tv','season':1,'episode':2}) is None


def test_series_rule_does_not_force_episode_or_mix_titles(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    rule=rules.create_rule(cfg,str(file),'series',42,'tv',anchor_title='Show')
    selected=rules.match_rule(file,cfg,{'title':'Show','media_type':'tv','season':1,'episode':3})
    assert selected['id']==rule['id'] and selected.get('episode') is None
    other=folder/'Other S01E01.mkv';other.write_bytes(b'synthetic')
    assert rules.match_rule(other,cfg,{'title':'Other','media_type':'tv','season':1,'episode':1}) is None


def test_conflicting_same_scope_rules_rejected(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    rules.create_rule(cfg,str(file),'file',43,'tv',season=1,episode=1)
    with pytest.raises(rules.RuleConflict):rules.match_rule(file,cfg,{'title':'Show','media_type':'tv','season':1,'episode':1})


def test_file_rule_precedes_series_and_revision_changes(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    series=rules.create_rule(cfg,str(file),'series',42,'tv',anchor_title='Show')
    single=rules.create_rule(cfg,str(file),'file',43,'tv',season=1,episode=1)
    first=rules.revision(cfg)
    assert rules.match_rule(file,cfg,{'title':'Show','media_type':'tv'})['id']==single['id']
    rules.set_enabled(cfg,single['id'],False)
    assert rules.revision(cfg)!=first
    assert rules.match_rule(file,cfg,{'title':'Show','media_type':'tv'})['id']==series['id']
    rules.delete_rule(cfg,series['id'])
    assert rules.match_rule(file,cfg,{'title':'Show','media_type':'tv'}) is None


def test_rejects_outside_or_symlink_escaped_paths(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);outside=tmp_path/'outside';outside.mkdir()
    external=outside/'movie.mkv';external.write_bytes(b'synthetic')
    (folder/'escape.mkv').symlink_to(external)
    cfg={'source_folders':[str(root)]};monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    for path in [external,folder/'escape.mkv']:
        with pytest.raises(rules.RuleValidationError):rules.create_rule(cfg,str(path),'file',42,'movie')
    assert external.read_bytes()==b'synthetic' and file.read_bytes()==b'synthetic'


def test_unknown_rule_schema_is_never_overwritten(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    cache=tmp_path/'cache';cache.mkdir();monkeypatch.setenv('CACHE_PATH',str(cache))
    path=cache/'recognition_user_rules_v1.json';raw=b'{"schema":999,"revision":1,"rules":[]}'
    path.write_bytes(raw)
    with pytest.raises(rules.RuleValidationError):rules.create_rule(cfg,str(file),'file',42,'movie')
    assert path.read_bytes()==raw


def test_series_rule_never_matches_type_conflict(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    rules.create_rule(cfg,str(file),'series',42,'tv',anchor_title='Show')
    with pytest.raises(rules.RuleConflict):rules.match_rule(file,cfg,{'title':'Show','media_type':'movie'})


def test_invalid_rule_record_is_rejected_without_overwrite(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    cache=tmp_path/'cache';cache.mkdir();monkeypatch.setenv('CACHE_PATH',str(cache))
    path=cache/'recognition_user_rules_v1.json';raw=b'{"schema":true,"revision":0,"rules":[]}'
    path.write_bytes(raw)
    with pytest.raises(rules.RuleValidationError):rules.create_rule(cfg,str(file),'file',42,'movie')
    assert path.read_bytes()==raw


def test_existing_empty_rule_store_is_not_silently_replaced(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    cache=tmp_path/'cache';cache.mkdir();monkeypatch.setenv('CACHE_PATH',str(cache))
    path=cache/'recognition_user_rules_v1.json';path.write_text('{}')
    with pytest.raises(rules.RuleValidationError):rules.create_rule(cfg,str(file),'file',42,'movie')
    assert path.read_text()=='{}'


def test_rule_management_api_rejects_unauthorized_and_updates(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    cfg=config_manager.load_config(config_file)
    rule=rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    assert client.get('/api/recognition_rules').status_code==401
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    result=client.get('/api/recognition_rules',headers=auth)
    assert result.status_code==200 and result.get_json()['rules'][0]['id']==rule['id']
    assert client.post('/api/recognition_rules/state',json={'id':rule['id'],'enabled':'false'},headers=auth).status_code==400
    assert client.post('/api/recognition_rules/state',json={'id':rule['id'],'enabled':False},headers=auth).status_code==200
    assert not rules.list_rules(cfg)[0]['enabled']
    assert client.post('/api/recognition_rules/delete',json={'id':rule['id']},headers=auth).status_code==200
    assert rules.list_rules(cfg)[0]['deleted']
    assert file.read_bytes()==b'synthetic'


def test_invalid_save_scope_rejected_before_media_transaction(client,monkeypatch):
    import base64
    from web import routes_failed
    monkeypatch.setattr(routes_failed,'reprocess_safely',lambda *a:pytest.fail('invalid scope must not touch media'))
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data={'src_path':'/synthetic/file.mkv','tmdb_id':42,'media_type':'tv','season':1,'episode':1,'save_rule_scope':'global'}
    assert client.post('/api/failed_cache/correct',json=data,headers=auth).status_code==400


def test_successful_manual_correction_saves_rule_only_after_commit(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules
    from web import routes_failed
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    cfg=config_manager.load_config(config_file)
    calls=[]
    def reprocess(*args):
        calls.append('media')
        assert not rules.list_rules(cfg)
        return True,None
    monkeypatch.setattr(routes_failed,'reprocess_safely',reprocess)
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data={'src_path':str(file),'tmdb_id':42,'media_type':'tv','season':0,'episode':2,'save_rule_scope':'file'}
    response=client.post('/api/failed_cache/correct',json=data,headers=auth)
    assert response.status_code==200 and response.get_json()['rule_status']=='saved'
    stored=rules.list_rules(cfg)
    assert calls==['media'] and len(stored)==1 and stored[0]['season']==0 and stored[0]['episode']==2
    assert file.read_bytes()==b'synthetic'


def test_rule_save_failure_reports_media_success_without_retry(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules
    from web import routes_failed
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    calls=[]
    monkeypatch.setattr(routes_failed,'reprocess_safely',lambda *a:(calls.append('media') or (True,None)))
    monkeypatch.setattr(rules,'create_rule',lambda *a,**k:(_ for _ in ()).throw(OSError('synthetic failure')))
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data={'src_path':str(file),'tmdb_id':42,'media_type':'tv','season':1,'episode':1,'save_rule_scope':'file'}
    response=client.post('/api/failed_cache/correct',json=data,headers=auth)
    assert response.status_code==200 and response.get_json()['status']=='success'
    assert response.get_json()['rule_status']=='failed' and calls==['media']
    assert file.read_bytes()==b'synthetic'


def test_preview_never_saves_rule(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules
    from web import routes_failed
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)],dry_run=True),config_file)
    monkeypatch.setattr(routes_failed,'reprocess_safely',lambda *a:(True,None))
    monkeypatch.setattr(rules,'create_rule',lambda *a,**kw:pytest.fail('preview cannot save rule'))
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data={'src_path':str(file),'tmdb_id':42,'media_type':'tv','season':1,'episode':1,'save_rule_scope':'file'}
    response=client.post('/api/failed_cache/correct',json=data,headers=auth)
    assert response.status_code==200 and response.get_json()['rule_status']=='preview'


def test_rule_conflicting_with_old_special_mapping_stops(tmp_path,config_file,monkeypatch):
    from core import config_manager,user_recognition_rules as rules,processor_core
    root,folder,file=source(tmp_path)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    cfg['special_mappings']=[{'keyword':'Show','tmdb_id':43,'media_type':'tv','season':1,'episode':1,'enabled':True}]
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('conflict must stop before search'))
    cache={}
    assert not processor_core.process_video(file,cfg,cache)
    assert '冲突' in cache[str(file.resolve())]['failed_reason']
    assert file.read_bytes()==b'synthetic'


def test_file_rule_reuses_identity_and_manual_episode(tmp_path,config_file,monkeypatch):
    from core import config_manager,user_recognition_rules as rules,processor_core,tmdb_client,video_info
    root,folder,file=source(tmp_path)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(file),'file',42,'tv',season=0,episode=2)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':42,'name':'Show'})
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('rule should avoid search'))
    observed=[]
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:observed.append(a[-2]) or True)
    assert processor_core.process_video(file,cfg,{})
    assert (observed[0]['season'],observed[0]['episode'])==(0,2)


def test_rule_changes_invalidate_identity_without_changing_retry_limits(tmp_path,config_file):
    from core import config_manager,user_recognition_rules as rules,parse_identity,processor_runner
    root,folder,file=source(tmp_path)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    before=parse_identity.policy_key(cfg)
    rule=rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    assert parse_identity.policy_key(cfg)!=before
    changed=parse_identity.policy_key(cfg)
    rules.set_enabled(cfg,rule['id'],False)
    assert parse_identity.policy_key(cfg)!=changed


def test_series_rule_reuses_only_when_local_title_matches(tmp_path,config_file,monkeypatch):
    from core import config_manager,user_recognition_rules as rules,processor_core,tmdb_client,video_info
    root,folder,file=source(tmp_path)
    other=folder/'Other S01E01.mkv';other.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(file),'series',42,'tv',anchor_title='Show')
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':kw['tmdb_id'],'name':'Show'})
    calls=[]
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:(calls.append(a[1]) or (None,'tv',0)))
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:True)
    assert processor_core.process_video(file,cfg,{})
    assert not processor_core.process_video(other,cfg,{})
    assert calls and calls[-1].casefold()=='other'
    assert file.read_bytes()==b'synthetic' and other.read_bytes()==b'synthetic'


def test_directory_rule_conflicting_with_nfo_never_overrides(tmp_path,config_file,monkeypatch):
    from core import config_manager,user_recognition_rules as rules,processor_core
    root,folder,file=source(tmp_path)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True},identity_hints={'enabled':True})
    rules.create_rule(cfg,str(file),'series',42,'tv',anchor_title='Show')
    (folder/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">43</uniqueid></tvshow>')
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('conflict must stop'))
    cache={}
    assert not processor_core.process_video(file,cfg,cache)
    assert '冲突' in cache[str(file.resolve())]['failed_reason']


def test_rule_management_dry_run_does_not_report_change_as_saved(client,config_file,tmp_path):
    import base64
    from core import config_manager,user_recognition_rules as rules
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    cfg=config_manager.load_config(config_file)
    rule=rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    config_manager.update_config(lambda c:dict(c,dry_run=True),config_file)
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    response=client.post('/api/recognition_rules/state',json={'id':rule['id'],'enabled':False},headers=auth)
    assert response.status_code == 409
    assert rules.list_rules(cfg)[0]['enabled']


def test_missing_unrelated_rule_file_does_not_block_other_media(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    other=folder/'Other S01E01.mkv';other.write_bytes(b'synthetic')
    file.unlink()
    assert rules.match_rule(other,cfg,{'title':'Other','media_type':'tv'}) is None


def test_series_rule_is_saved_with_local_title_only_after_success(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules
    from web import routes_failed
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    monkeypatch.setattr(routes_failed,'reprocess_safely',lambda *a:(True,None))
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data={'src_path':str(file),'tmdb_id':42,'media_type':'tv','season':1,'episode':1,'save_rule_scope':'series'}
    response=client.post('/api/failed_cache/correct',json=data,headers=auth)
    assert response.status_code==200 and response.get_json()['rule_status']=='saved'
    saved=rules.list_rules({})[0]
    assert saved['anchor_title']=='Show' and saved['season'] is None and saved['episode'] is None


def test_failed_media_transaction_never_saves_rule(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules
    from web import routes_failed
    root,folder,file=source(tmp_path)
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    monkeypatch.setattr(routes_failed,'reprocess_safely',lambda *a:(False,'target_conflict'))
    monkeypatch.setattr(rules,'create_rule',lambda *a,**kw:pytest.fail('failed transaction must not save rule'))
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data={'src_path':str(file),'tmdb_id':42,'media_type':'tv','season':1,'episode':1,'save_rule_scope':'file'}
    assert client.post('/api/failed_cache/correct',json=data,headers=auth).status_code==409
    assert file.read_bytes()==b'synthetic'


def test_file_rule_reports_conflicting_lower_priority_series(tmp_path,monkeypatch):
    from core import user_recognition_rules as rules
    root,folder,file=source(tmp_path);cfg={'source_folders':[str(root)]}
    monkeypatch.setenv('CACHE_PATH',str(tmp_path/'cache'))
    rules.create_rule(cfg,str(file),'file',42,'tv',season=1,episode=1)
    rules.create_rule(cfg,str(file),'series',43,'tv',anchor_title='Show')
    selected=rules.match_rule(file,cfg,{'title':'Show','media_type':'tv'})
    assert selected['tmdb_id']==42 and selected['_lower_priority_conflict']
