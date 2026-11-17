"""E05: bounded, explicit mappings; all inputs and storage are temporary."""
import pytest


def source(tmp_path):
    root=tmp_path/'source'; folder=root/'Show'/'Part 2';folder.mkdir(parents=True)
    src=folder/'Show EP01.mkv';src.write_bytes(b'synthetic')
    return {'source_folders':[str(root)]},folder,src


def test_exact_mapping_keeps_decimal_literal_and_targets_special(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_exact(cfg, str(folder), 42, '12.5', 0, 3)
    rule=maps.match(cfg,src,42,'12.5')
    assert (rule['season'],rule['episode'],rule['source_label'])==(0,3,'12.5')
    assert maps.match(cfg,src,42,'12') is None
    assert src.read_bytes()==b'synthetic'


def test_different_source_and_target_conflicts_are_rejected(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_exact(cfg,str(folder),42,'1',1,13)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'1',1,14)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'2',1,13)
    with pytest.raises(maps.MappingConflict):maps.match(cfg,src,43,'1')


def test_range_is_bounded_and_rejects_overlap_and_duplicate_target(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_range(cfg,str(folder),42,1,3,1,13)
    assert maps.match(cfg,src,42,'2')['episode']==14
    assert maps.match(cfg,src,42,'4') is None
    with pytest.raises(maps.MappingConflict):maps.add_range(cfg,str(folder),42,3,5,2,1)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'9',1,14)
    with pytest.raises(ValueError):maps.add_range(cfg,str(folder),42,2,1,1,1)
    with pytest.raises(ValueError):maps.add_range(cfg,str(folder),42,1,1001,1,1)


def test_scopes_are_bounded_and_disabling_invalidates_revision(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    external=tmp_path/'outside';external.mkdir()
    with pytest.raises(ValueError):maps.add_exact(cfg,str(external),42,'1',1,1)
    link=folder/'link';link.symlink_to(external,target_is_directory=True)
    with pytest.raises(ValueError):maps.add_exact(cfg,str(link),42,'1',1,1)
    rule=maps.add_exact(cfg,str(folder),42,'1',1,13)
    before=maps.revision();maps.set_enabled(rule['id'],False)
    assert maps.revision()!=before and maps.match(cfg,src,42,'1') is None


def test_unsupported_store_is_never_overwritten(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    path=tmp_path/'recognition_numbering_maps_v1.json';path.write_text('{"schema":99,"rules":[]}')
    before=path.read_bytes()
    with pytest.raises(ValueError):maps.add_exact(cfg,str(folder),42,'1',1,13)
    assert path.read_bytes()==before


def test_conflicting_manually_edited_store_is_rejected(tmp_path):
    import json
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    maps.add_exact(cfg,str(folder),42,'1',1,13)
    path=tmp_path/'recognition_numbering_maps_v1.json';state=json.loads(path.read_text())
    other=dict(state['rules'][0],id='other',source_label='2')
    state['rules'].append(other);path.write_text(json.dumps(state));before=path.read_bytes()
    with pytest.raises(maps.MappingConflict):maps.match(cfg,src,42,'1')
    assert path.read_bytes()==before


@pytest.mark.parametrize('filename,expected',[
    ('Show EP12.5.mkv','12.5'),('Show - 12.5.mkv','12.5'),('Show S02E01.mkv','01'),
    ('第01集.mkv','01'),('01.mkv','01'),('Show OVA03.mkv','03')])
def test_identifier_preserves_source_number(filename,expected):
    from core.numbering_maps import extract_source_label
    assert extract_source_label(filename)==expected


@pytest.mark.parametrize('filename', ['Show S01E01-02.mkv','Show E01E02.mkv','Show - 01~02.mkv','Show E01 E02.mkv'])
def test_multiple_episode_identifiers_are_never_interpreted_as_one(filename):
    from core.numbering_maps import extract_source_label,MappingConflict
    with pytest.raises(MappingConflict):extract_source_label(filename)


def make_cfg(config_file, root):
    from core import config_manager
    cfg=config_manager.load_config(config_file)
    cfg.update(source_folders=[str(root)],dry_run=True,numbering_maps={'enabled':True})
    return cfg


def test_tv_mapping_previews_target_and_checks_tmdb(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_tv,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);maps.add_exact(cfg,str(folder),42,'01',1,13)
    calls=[];targets=[]
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda ident,season,*a,**k:(calls.append(season) or [{'episode_number':13,'name':'Part 2'}]))
    monkeypatch.setattr(processor_tv,'preview_target',lambda src,target,*a:(targets.append(target) or target))
    info={'season':2,'episode':1,'explicit_season':2,'numbering_source':'season_relative'}
    assert processor_tv.process_tv_branch(src,cfg,{},None,'Show','2020',42,{'id':42,'name':'Show','seasons':[{'season_number':1},{'season_number':2}]},info,80)
    assert calls==[1] and 'S01E13' in str(targets[0])
    assert src.read_bytes()==b'synthetic'


def test_nonexistent_mapped_episode_never_uses_ai_or_writes(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_tv,tmdb_client,ai_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);cfg['ai_parser']['enabled']=True
    maps.add_exact(cfg,str(folder),42,'01',1,13)
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':1,'name':'Wrong'}])
    monkeypatch.setattr(ai_client,'call_ai_api',lambda *a,**k:pytest.fail('invalid explicit mapping must not use AI fallback'))
    info={'season':2,'episode':1,'explicit_season':2,'numbering_source':'season_relative','_parser':'anitopy'}
    assert not processor_tv.process_tv_branch(src,cfg,{},None,'Show','2020',42,{'id':42,'name':'Show','seasons':[{'season_number':1}]},info,80)
    assert src.read_bytes()==b'synthetic' and not list((tmp_path/'tv').rglob('*.mkv'))


def test_mapping_conflicting_with_file_rule_stops_before_episode_request(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_tv,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);maps.add_exact(cfg,str(folder),42,'01',1,13)
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:pytest.fail('conflict must stop'))
    info={'season':2,'episode':1,'explicit_season':2,'_user_rule_id':'confirmed'}
    assert not processor_tv.process_tv_branch(src,cfg,{},None,'Show','2020',42,{'id':42,'name':'Show','seasons':[{'season_number':1}]},info,80)
    assert src.read_bytes()==b'synthetic'


def test_decimal_mapping_requires_confirmed_identity_and_keeps_exact_label(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_core,tmdb_client,video_info
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show - 12.5.mkv';src.write_bytes(b'synthetic')
    (folder/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">42</uniqueid></tvshow>')
    cfg=make_cfg(config_file,root);cfg['identity_hints']={'enabled':True}
    maps.add_exact(cfg,str(folder),42,'12.5',0,3)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':42,'name':'Show','seasons':[{'season_number':0}]})
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('explicit identity must not search'))
    seen=[];monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:seen.append(a[-2]) or True)
    assert processor_core.process_video(src,cfg,{})
    assert seen[0]['_numbering_source_label']=='12.5' and (seen[0]['season'],seen[0]['episode'])==(0,3)
    assert src.read_bytes()==b'synthetic'


def test_preview_create_disable_and_invalid_target_api(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,numbering_maps as maps,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show - 12.5.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'Show','seasons':[{'season_number':0}]})
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':3}])
    payload={'scope':str(folder),'src_path':str(src),'tmdb_id':42,'kind':'exact','source_label':'12.5','season':0,'episode':3}
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    assert client.get('/api/numbering_maps').status_code==401
    preview=client.post('/api/numbering_maps/preview',json=payload,headers=auth)
    assert preview.status_code==200 and preview.get_json()['preview']['source_label']=='12.5'
    assert not maps.list_maps() and src.read_bytes()==b'synthetic'
    result=client.post('/api/numbering_maps',json=payload,headers=auth)
    assert result.status_code==200 and len(maps.list_maps())==1
    rule=maps.list_maps()[0]
    assert client.post('/api/numbering_maps/state',json={'id':rule['id'],'enabled':False},headers=auth).status_code==200
    assert not maps.list_maps()[0]['enabled']
    payload['source_label']='12.5';payload['episode']=4
    result=client.post('/api/numbering_maps',json=payload,headers=auth)
    assert result.status_code==409 and len(maps.list_maps())==1
    assert src.read_bytes()==b'synthetic'


def test_network_unknown_and_preview_mode_never_save_map(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,numbering_maps as maps,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show EP01.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:None)
    payload={'scope':str(folder),'src_path':str(src),'tmdb_id':42,'kind':'exact','source_label':'01','season':1,'episode':13}
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    response=client.post('/api/numbering_maps',json=payload,headers=auth)
    assert response.status_code==503 and response.get_json()['code']=='target_unknown' and not maps.list_maps()
    config_manager.update_config(lambda c:dict(c,dry_run=True),config_file)
    assert client.post('/api/numbering_maps',json=payload,headers=auth).status_code==409
    assert not maps.list_maps() and src.read_bytes()==b'synthetic'


@pytest.mark.parametrize('filename',['Show - 01 & 02.mkv','Show - 01+02.mkv','Show - 01,02.mkv'])
def test_number_lists_are_not_treated_as_single_episode(filename):
    from core.numbering_maps import extract_source_label,MappingConflict
    with pytest.raises(MappingConflict):extract_source_label(filename)


def test_decimal_mapping_conflict_with_partial_old_manual_episode_stops(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_core,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show - 12.5.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root)
    cfg['special_mappings']=[{'keyword':'12.5','tmdb_id':42,'media_type':'tv','enabled':True,'season':None,'episode':2}]
    maps.add_exact(cfg,str(folder),42,'12.5',0,3)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:pytest.fail('conflict must stop before TMDB'))
    assert not processor_core.process_video(src,cfg,{})
    assert src.read_bytes()==b'synthetic'


def test_series_identity_rule_does_not_freeze_source_season_episode(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_tv,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);maps.add_exact(cfg,str(folder),42,'01',1,13)
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':13,'name':'Part'}])
    monkeypatch.setattr(processor_tv,'preview_target',lambda src,target,*a:target)
    info={'season':2,'episode':1,'explicit_season':2,'_user_rule_id':'series','_user_rule_scope':'series'}
    assert processor_tv.process_tv_branch(src,cfg,{},None,'Show','2020',42,{'id':42,'name':'Show','seasons':[{'season_number':1}]},info,80)


def test_range_api_validates_every_target_and_previews_sample(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,numbering_maps as maps,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show EP02.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'Show','seasons':[{'season_number':1}]})
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':n} for n in (13,14,15)])
    payload={'scope':str(folder),'src_path':str(src),'tmdb_id':42,'kind':'range','start':1,'end':3,'season':1,'episode':13}
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    preview=client.post('/api/numbering_maps/preview',json=payload,headers=auth)
    assert preview.status_code==200 and preview.get_json()['preview']['episode']==14 and not maps.list_maps()
    assert client.post('/api/numbering_maps',json=payload,headers=auth).status_code==200
    assert maps.match({'source_folders':[str(root)]},src,42,'02')['episode']==14
    assert src.read_bytes()==b'synthetic'


def test_preview_conflict_with_confirmed_file_rule_stops_before_tmdb(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show EP01.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)],user_rules={'enabled':True}),config_file)
    cfg=config_manager.load_config(config_file);rules.create_rule(cfg,str(src),'file',42,'tv',season=1,episode=1)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:pytest.fail('conflict must stop before TMDB'))
    payload={'scope':str(folder),'src_path':str(src),'tmdb_id':42,'kind':'exact','source_label':'01','season':1,'episode':13}
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    response=client.post('/api/numbering_maps/preview',json=payload,headers=auth)
    assert response.status_code==409 and response.get_json()['code']=='mapping_conflict'
    assert src.read_bytes()==b'synthetic'


def test_mapping_preview_does_not_create_backup_for_corrupt_store(client,config_file,tmp_path):
    import base64
    from core import config_manager
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show EP01.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    store=tmp_path/'recognition_numbering_maps_v1.json';store.write_text('{bad')
    payload={'scope':str(folder),'src_path':str(src),'tmdb_id':42,'kind':'exact','source_label':'01','season':1,'episode':13}
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    assert client.post('/api/numbering_maps/preview',json=payload,headers=auth).status_code==503
    assert store.read_text()=='{bad' and not list(tmp_path.glob('recognition_numbering_maps_v1.json.*.bak'))


def test_decimal_can_use_confirmed_scoped_series_identity(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_core,user_recognition_rules as rules,tmdb_client,video_info
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    anchor=folder/'Show S01E01.mkv';anchor.write_bytes(b'synthetic')
    src=folder/'Show - 12.5.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);cfg['user_rules']={'enabled':True}
    rules.create_rule(cfg,str(anchor),'series',42,'tv',anchor_title='Show')
    maps.add_exact(cfg,str(folder),42,'12.5',0,3)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':42,'name':'Show','seasons':[{'season_number':0}]})
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('confirmed series must not search'))
    seen=[];monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:seen.append(a[-2]) or True)
    assert processor_core.process_video(src,cfg,{})
    assert seen[0]['_numbering_source_label']=='12.5' and (seen[0]['season'],seen[0]['episode'])==(0,3)
    assert src.read_bytes()==b'synthetic'


def test_decimal_preview_detects_different_confirmed_series(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,user_recognition_rules as rules,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    anchor=folder/'Show S01E01.mkv';anchor.write_bytes(b'synthetic')
    src=folder/'Show - 12.5.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)],user_rules={'enabled':True}),config_file)
    rules.create_rule(config_manager.load_config(config_file),str(anchor),'series',42,'tv',anchor_title='Show')
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:pytest.fail('conflict must stop before TMDB'))
    payload={'scope':str(folder),'src_path':str(src),'tmdb_id':43,'kind':'exact','source_label':'12.5','season':0,'episode':3}
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    response=client.post('/api/numbering_maps/preview',json=payload,headers=auth)
    assert response.status_code==409 and response.get_json()['code']=='mapping_conflict'


def test_mapped_target_conflict_never_overwrites_existing_file(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_tv,tmdb_client
    from core.media_paths import episode_video_path
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);maps.add_exact(cfg,str(folder),42,'01',1,13)
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':13,'name':'Part 2'}])
    target=episode_video_path(src,cfg,'Show','2020',1,13,'Part 2');target.parent.mkdir(parents=True)
    target.write_bytes(b'protected')
    info={'season':2,'episode':1,'explicit_season':2,'numbering_source':'season_relative'}
    assert not processor_tv.process_tv_branch(src,cfg,{},None,'Show','2020',42,{'id':42,'name':'Show','seasons':[{'season_number':1}]},info,80)
    assert src.read_bytes()==b'synthetic' and target.read_bytes()==b'protected'


def test_mapping_changed_during_tmdb_validation_stops_before_target(tmp_path,config_file,monkeypatch):
    from core import numbering_maps as maps,processor_tv,tmdb_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    cfg=make_cfg(config_file,root);maps.add_exact(cfg,str(folder),42,'01',1,13)
    versions=iter(['before','after']);monkeypatch.setattr(maps,'revision',lambda:next(versions))
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':13,'name':'Part'}])
    monkeypatch.setattr(processor_tv,'preview_target',lambda *a:pytest.fail('changed mapping must stop before target'))
    info={'season':2,'episode':1,'explicit_season':2,'numbering_source':'season_relative'}
    assert not processor_tv.process_tv_branch(src,cfg,{},None,'Show','2020',42,{'id':42,'name':'Show','seasons':[{'season_number':1}]},info,80)
    assert src.read_bytes()==b'synthetic'


def test_deleted_mapping_stops_matching_and_frees_its_numbers(tmp_path):
    from core import numbering_maps as maps
    cfg,folder,src=source(tmp_path)
    rule=maps.add_exact(cfg,str(folder),42,'1',1,13)
    with pytest.raises(maps.MappingConflict):maps.add_exact(cfg,str(folder),42,'1',1,14)
    before=maps.revision()
    maps.delete_map(rule['id'])
    assert maps.revision()!=before
    stored=next(r for r in maps.list_maps() if r['id']==rule['id'])
    assert stored['deleted'] is True and stored['enabled'] is False
    assert maps.match(cfg,src,42,'1') is None
    replacement=maps.add_exact(cfg,str(folder),42,'1',1,14)
    assert maps.match(cfg,src,42,'1')['id']==replacement['id']
    with pytest.raises(ValueError):maps.delete_map(rule['id'])
    with pytest.raises(ValueError):maps.set_enabled(rule['id'],True)
    with pytest.raises(ValueError):maps.delete_map('missing')
    assert src.read_bytes()==b'synthetic'


def test_delete_api_requires_auth_id_and_live_mode(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import config_manager,numbering_maps as maps
    from web import task_state
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Show EP01.mkv';src.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)],dry_run=False),config_file)
    cfg=config_manager.load_config(config_file)
    rule=maps.add_exact(cfg,str(folder),42,'1',1,13)
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    assert client.post('/api/numbering_maps/delete',json={'id':rule['id']}).status_code==401
    assert client.post('/api/numbering_maps/delete',json={},headers=auth).status_code==400
    assert client.post('/api/numbering_maps/delete',json={'id':'x'*65},headers=auth).status_code==400
    assert client.post('/api/numbering_maps/delete',json={'id':'missing'},headers=auth).status_code==400
    monkeypatch.setattr(task_state,'is_task_running',lambda:True)
    assert client.post('/api/numbering_maps/delete',json={'id':rule['id']},headers=auth).status_code==409
    monkeypatch.setattr(task_state,'is_task_running',lambda:False)
    config_manager.update_config(lambda c:dict(c,dry_run=True),config_file)
    assert client.post('/api/numbering_maps/delete',json={'id':rule['id']},headers=auth).status_code==409
    assert not maps.list_maps()[0]['deleted']
    config_manager.update_config(lambda c:dict(c,dry_run=False),config_file)
    response=client.post('/api/numbering_maps/delete',json={'id':rule['id']},headers=auth)
    assert response.status_code==200 and response.get_json()['status']=='success'
    assert client.get('/api/numbering_maps',headers=auth).get_json()['rules']==[]
    assert maps.list_maps()[0]['deleted'] is True
    assert src.read_bytes()==b'synthetic'
