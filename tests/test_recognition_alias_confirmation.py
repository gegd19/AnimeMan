"""Explicit, source-scoped alias confirmation; all media and TMDB are synthetic."""
import base64
import pytest


def auth():
    return {'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}


def setup_source(tmp_path, config_file):
    from core import config_manager
    root=tmp_path/'source';scope=root/'Show';scope.mkdir(parents=True)
    source=scope/'Sora no Tabi S01E01.mkv';source.write_bytes(b'synthetic')
    config_manager.update_config(lambda c:dict(c,source_folders=[str(root)]),config_file)
    return root,scope,source


def test_alias_preview_requires_auth_and_writes_nothing(client,config_file,tmp_path,monkeypatch):
    from core import recognition_aliases as aliases,tmdb_client
    root,scope,source=setup_source(tmp_path,config_file)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'空の旅','original_name':'空の旅','first_air_date':'2020-01-01'})
    payload={'scope':str(scope),'name':'Sora no Tabi','media_type':'tv','tmdb_id':42}
    assert client.post('/api/recognition_aliases/preview',json=payload).status_code==401
    response=client.post('/api/recognition_aliases/preview',json=payload,headers=auth())
    assert response.status_code==200
    data=response.get_json();assert data['preview']['title']=='空の旅' and data['preview']['scope']==str(scope)
    assert aliases.find_aliases('Sora no Tabi',src=source)==[] and source.read_bytes()==b'synthetic'
    assert not (tmp_path/'recognition_aliases_v1.json').exists()


def test_explicit_confirmation_saves_scoped_evidence_atomically_and_enables_matching(client,config_file,tmp_path,monkeypatch):
    from core import config_manager,recognition_aliases as aliases,processor_search,tmdb_client
    root,scope,source=setup_source(tmp_path,config_file)
    detail={'id':42,'name':'空の旅','original_name':'空の旅','first_air_date':'2020-01-01'}
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:detail)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[])
    payload={'scope':str(scope),'name':'Sora no Tabi','media_type':'tv','tmdb_id':42}
    preview=client.post('/api/recognition_aliases/preview',json=payload,headers=auth()).get_json()
    payload['preview_token']=preview['preview_token']
    result=client.post('/api/recognition_aliases',json=payload,headers=auth())
    assert result.status_code==200
    records=aliases.all_aliases(src=source)
    assert {(r['name'],r['source']) for r in records}=={('Sora no Tabi','manual'),('空の旅','tmdb')}
    cfg=config_manager.load_config(config_file);cfg['recognition_aliases']={'enabled':True}
    selected,kind,_=processor_search.search_tmdb_with_fallback('tv','Sora no Tabi','2020',[],cfg,src=source)
    assert selected['id']==42 and kind=='tv'
    outside=root/'Other';outside.mkdir();other=outside/'Sora no Tabi S01E01.mkv';other.write_bytes(b'synthetic')
    assert not aliases.find_aliases('Sora no Tabi',src=other)
    assert source.read_bytes()==b'synthetic' and other.read_bytes()==b'synthetic'


def test_changed_preview_scope_and_unavailable_tmdb_never_write(client,config_file,tmp_path,monkeypatch):
    from core import recognition_aliases as aliases,tmdb_client
    root,scope,source=setup_source(tmp_path,config_file)
    detail={'id':42,'name':'空の旅','first_air_date':'2020-01-01'}
    state=[detail];monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:state[0])
    payload={'scope':str(scope),'name':'Sora no Tabi','media_type':'tv','tmdb_id':42}
    token=client.post('/api/recognition_aliases/preview',json=payload,headers=auth()).get_json()['preview_token']
    state[0]={'id':42,'name':'別の作品','first_air_date':'2020-01-01'}
    assert client.post('/api/recognition_aliases',json={**payload,'preview_token':token},headers=auth()).status_code==409
    state[0]=None
    assert client.post('/api/recognition_aliases/preview',json=payload,headers=auth()).status_code==503
    assert not aliases.find_aliases('Sora no Tabi',src=source)
    outside=tmp_path/'outside';outside.mkdir()
    assert client.post('/api/recognition_aliases/preview',json={**payload,'scope':str(outside)},headers=auth()).status_code==400
    assert source.read_bytes()==b'synthetic'


def test_duplicate_trusted_alias_with_unavailable_identity_requires_review(tmp_path,monkeypatch):
    from core import recognition_aliases as aliases,processor_search,tmdb_client
    scope=tmp_path/'source';scope.mkdir();source=scope/'Shared S01E01.mkv';source.write_bytes(b'synthetic')
    for ident in (42,43):
        aliases.add_alias('Shared','tv',ident,'manual',scope=str(scope))
        aliases.add_alias('Shared','tv',ident,'tmdb',scope=str(scope))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda kind,ident,*a,**k:{'id':42,'name':'Shared'} if ident==42 else None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[{'id':42,'name':'Shared'}])
    cfg={'tmdb_api':{'api_key':'synthetic'},'recognition_aliases':{'enabled':True},'ai_parser':{'enabled':False}}
    selected,_,_=processor_search.search_tmdb_with_fallback('tv','Shared',None,[],cfg,src=source)
    assert selected is None and source.read_bytes()==b'synthetic'


def test_batch_alias_write_is_atomic_when_one_record_is_invalid(tmp_path):
    from core import recognition_aliases as aliases
    original={'name':'Existing','media_type':'tv','tmdb_id':7,'source':'manual','year':None,'scope':None}
    aliases.add_alias(**original)
    path=tmp_path/'recognition_aliases_v1.json';before=path.read_bytes()
    valid={'name':'Sora','media_type':'tv','tmdb_id':42,'source':'manual','year':'2020','scope':None}
    invalid={**valid,'name':''}
    with pytest.raises(ValueError):aliases.add_aliases([valid,invalid])
    assert path.read_bytes()==before


def test_alias_removal_and_dry_run_are_explicit(client,config_file,tmp_path,monkeypatch):
    from core import config_manager,recognition_aliases as aliases,tmdb_client
    root,scope,source=setup_source(tmp_path,config_file)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'空の旅','first_air_date':'2020-01-01'})
    payload={'scope':str(scope),'name':'Sora no Tabi','media_type':'tv','tmdb_id':42}
    preview=client.post('/api/recognition_aliases/preview',json=payload,headers=auth()).get_json()
    payload['preview_token']=preview['preview_token']
    config_manager.update_config(lambda c:dict(c,dry_run=True),config_file)
    assert client.post('/api/recognition_aliases',json=payload,headers=auth()).status_code==409
    assert not aliases.find_aliases('Sora no Tabi',src=source)
    config_manager.update_config(lambda c:dict(c,dry_run=False),config_file)
    assert client.post('/api/recognition_aliases',json=payload,headers=auth()).status_code==200
    record=aliases.manual_aliases()[0]
    config_manager.update_config(lambda c:dict(c,dry_run=True),config_file)
    assert client.post('/api/recognition_aliases/delete',json={'record':record},headers=auth()).status_code==409
    assert aliases.find_aliases('Sora no Tabi',src=source)
    config_manager.update_config(lambda c:dict(c,dry_run=False),config_file)
    assert client.post('/api/recognition_aliases/delete',json={'record':record},headers=auth()).status_code==200
    assert not aliases.find_aliases('Sora no Tabi',src=source)
    assert source.read_bytes()==b'synthetic'


def test_preview_warns_of_same_alias_in_overlapping_child_scope(client,config_file,tmp_path,monkeypatch):
    from core import recognition_aliases as aliases,tmdb_client
    root,scope,source=setup_source(tmp_path,config_file)
    child=scope/'Season 02';child.mkdir()
    aliases.add_alias('Sora no Tabi','tv',43,'manual',scope=str(child))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'空の旅'})
    payload={'scope':str(scope),'name':'Sora no Tabi','media_type':'tv','tmdb_id':42}
    response=client.post('/api/recognition_aliases/preview',json=payload,headers=auth())
    assert response.status_code==200 and response.get_json()['preview']['conflicting_ids']==[43]
    assert source.read_bytes()==b'synthetic'
