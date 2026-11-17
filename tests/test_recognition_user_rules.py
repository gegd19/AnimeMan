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
