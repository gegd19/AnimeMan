"""E03: bounded, source-scoped folder evidence from synthetic scanned files."""
from pathlib import Path


def make_files(tmp_path, names):
    root = tmp_path / 'source'
    folder = root / 'Show'
    folder.mkdir(parents=True)
    files = []
    for name in names:
        path = folder / name
        path.write_bytes(b'synthetic')
        files.append(path)
    return root, folder, files


def test_mixed_titles_are_grouped_without_majority_override(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, ['Show S01E01.mkv', 'Show S01E02.mkv', 'Other S01E01.mkv'])
    result = collect_folder_evidence(folder, files, {'source_folders':[str(root)]})
    assert result['complete'] and result['identity_status'] == 'conflict'
    assert sorted(group['title'] for group in result['groups']) == ['Other', 'Show']


def test_release_groups_do_not_create_independent_identity_evidence(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, ['[A] Show S01E01.mkv', '[B] Show S01E02.mkv'])
    result = collect_folder_evidence(folder, files, {'source_folders':[str(root)]})
    assert len(result['groups']) == 1 and result['identity_status'] == 'unconfirmed'
    assert 'confidence' not in result


def test_sampling_is_bounded_stable_and_no_file_content_read(tmp_path, monkeypatch):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, [f'Show S01E{i:02}.mkv' for i in range(1, 70)])
    monkeypatch.setattr(Path, 'open', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not open media')))
    first = collect_folder_evidence(folder, files, {'source_folders':[str(root)]}, limit=5)
    second = collect_folder_evidence(folder, list(reversed(files)), {'source_folders':[str(root)]}, limit=5)
    assert first == second and first['sampled'] == 5 and not first['complete']
    assert first['identity_status'] == 'unconfirmed'


def test_fingerprint_changes_after_file_replacement_or_addition(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files = make_files(tmp_path, ['Show S01E01.mkv'])
    cfg={'source_folders':[str(root)]}
    before=collect_folder_evidence(folder, files, cfg)['fingerprint']
    files[0].unlink(); files[0].write_bytes(b'replacement')
    replaced=collect_folder_evidence(folder, files, cfg)['fingerprint']
    more=folder/'Show S01E02.mkv';more.write_bytes(b'synthetic')
    added=collect_folder_evidence(folder, files+[more], cfg)['fingerprint']
    assert len({before,replaced,added}) == 3


def test_outside_source_and_symlink_are_not_evidence(tmp_path):
    from core.folder_evidence import collect_folder_evidence
    root, folder, files=make_files(tmp_path, ['Show S01E01.mkv'])
    other=tmp_path/'Other S01E01.mkv';other.write_bytes(b'synthetic')
    link=folder/'Other S01E01.mkv';link.symlink_to(other)
    result=collect_folder_evidence(folder, files+[other,link], {'source_folders':[str(root)]})
    assert result['sampled']==1 and len(result['groups'])==1


def test_mixed_folder_disables_shared_ai_evidence(tmp_path,config_file,monkeypatch):
    from core import ai_client,config_manager,parser_manager
    root,folder,files=make_files(tmp_path,['Show S01E01.mkv','Other S01E01.mkv'])
    cfg=config_manager.load_config(config_file)
    cfg.update(source_folders=[str(root)], ai_parser={'enabled':True,'batch_folder_enabled':True},
               _folder_evidence={'identity_status':'conflict','fingerprint':'mixed'})
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',lambda *a,**k: (_ for _ in ()).throw(AssertionError('shared AI must not run in mixed folder')))
    monkeypatch.setattr(parser_manager.folder_ai_cache,'get_cached_folder_parse',lambda *a,**k: (_ for _ in ()).throw(AssertionError('shared cache must not run in mixed folder')))
    result=parser_manager.parse_filename(files[0],cfg)
    assert result.get('title')=='Show' and result.get('episode')==1


def test_evidence_fingerprint_changes_parser_policy(tmp_path,config_file):
    from core import config_manager,parse_identity
    cfg=config_manager.load_config(config_file)
    a=dict(cfg,_folder_evidence={'identity_status':'unconfirmed','fingerprint':'first'})
    b=dict(cfg,_folder_evidence={'identity_status':'unconfirmed','fingerprint':'second'})
    assert parse_identity.policy_key(a)!=parse_identity.policy_key(b)


def test_confirmed_file_identity_with_ambiguous_episode_is_preserved(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,user_recognition_rules as rules
    root,folder,files=make_files(tmp_path,['Show OVA.mkv'])
    src=files[0];cfg=config_manager.load_config(config_file)
    cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(src),'file',42,'tv',season=1,episode=1)
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a: (_ for _ in ()).throw(AssertionError('unknown numbering must not write')))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    pending=cache[str(src.resolve())]['recognition_pending']
    assert pending['identity_status']=='confirmed' and pending['numbering_status']=='unknown'
    assert pending['tmdb_id']==42 and pending['media_type']=='tv'
    assert pending.get('season') is None and pending.get('episode') is None
    assert src.read_bytes()==b'synthetic'


def test_pending_identity_is_invalid_after_rule_disabled(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,user_recognition_rules as rules
    from core.folder_evidence import current_pending_identity
    root,folder,files=make_files(tmp_path,['Show OVA.mkv'])
    src=files[0];cfg=config_manager.load_config(config_file)
    cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rule=rules.create_rule(cfg,str(src),'file',42,'tv',season=1,episode=1)
    cache={};assert not processor_core.process_video(src,cfg,cache)
    pending=cache[str(src.resolve())]['recognition_pending']
    assert current_pending_identity(src,cfg,pending)['tmdb_id']==42
    rules.set_enabled(cfg,rule['id'],False)
    assert current_pending_identity(src,cfg,pending) is None


def test_failed_api_shows_current_pending_identity_and_rejects_stale_reuse(client,config_file,tmp_path,monkeypatch):
    import base64
    from core import cache_manager,config_manager,processor_core,user_recognition_rules as rules
    from web import routes_failed
    root,folder,files=make_files(tmp_path,['Show OVA.mkv']);src=files[0]
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)],user_rules={'enabled':True}),config_file)
    cfg=config_manager.load_config(config_file)
    rule=rules.create_rule(cfg,str(src),'file',42,'tv',season=0,episode=1)
    cache={};assert not processor_core.process_video(src,cfg,cache)
    cache_manager.save_cache(cache)
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    data=client.get('/api/failed_cache/clusters',headers=auth).get_json()
    assert data['clusters'][0]['files'][0]['recognition_pending']['tmdb_id']==42
    rules.set_enabled(cfg,rule['id'],False)
    assert client.get('/api/failed_cache/clusters',headers=auth).get_json()['clusters'][0]['files'][0].get('recognition_pending') is None
    monkeypatch.setattr(routes_failed,'reprocess_safely',lambda *a: (_ for _ in ()).throw(AssertionError('stale identity cannot touch media')))
    payload={'src_path':str(src),'tmdb_id':42,'media_type':'tv','season':0,'episode':3,'use_pending_identity':True}
    assert client.post('/api/failed_cache/correct',json=payload,headers=auth).status_code==409
    assert src.read_bytes()==b'synthetic'


def test_numeric_episode_inherits_confirmed_series_without_fabricating_number(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,user_recognition_rules as rules,tmdb_client,video_info
    root=tmp_path/'source';folder=root/'Show'/'Season 02';folder.mkdir(parents=True)
    numeric=folder/'01.mkv';numeric.write_bytes(b'synthetic')
    anchor=folder/'Show S02E02.mkv';anchor.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(anchor),'series',42,'tv',anchor_title='Show')
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':42,'name':'Show'})
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k: (_ for _ in ()).throw(AssertionError('confirmed identity should not search')))
    selected=[]
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a: selected.append(a[-2]) or True)
    assert processor_core.process_video(numeric,cfg,{})
    assert (selected[0]['season'],selected[0]['episode'])==(2,1)
    assert numeric.read_bytes()==b'synthetic'


def test_confirmed_series_identity_keeps_unknown_special_for_manual_numbering(tmp_path,config_file):
    from core import config_manager,processor_core,user_recognition_rules as rules
    from core.folder_evidence import current_pending_identity
    root,folder,files=make_files(tmp_path,['Show S01E01.mkv','Show OVA.mkv'])
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(files[0]),'series',42,'tv',anchor_title='Show')
    cache={};assert not processor_core.process_video(files[1],cfg,cache)
    pending=cache[str(files[1].resolve())]['recognition_pending']
    assert pending['identity_status']=='confirmed' and pending['numbering_status']=='unknown'
    assert current_pending_identity(files[1],cfg,pending)['tmdb_id']==42
    assert pending.get('episode') is None


def test_folder_evidence_version_is_part_of_fingerprint(tmp_path,monkeypatch):
    from core import folder_evidence
    root,folder,files=make_files(tmp_path,['Show S01E01.mkv'])
    config={'source_folders':[str(root)]}
    old=folder_evidence.collect_folder_evidence(folder,files,config)['fingerprint']
    monkeypatch.setattr(folder_evidence,'EVIDENCE_VERSION','future-test-version')
    assert folder_evidence.collect_folder_evidence(folder,files,config)['fingerprint'] != old
