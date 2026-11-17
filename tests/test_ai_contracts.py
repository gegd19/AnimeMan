"""T10 untrusted AI boundaries, request coalescing and cache identity."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from pathlib import Path
import threading

import pytest


def media_info(title='Show',**updates):
    return dict(media_type='tv',title=title,season=1,episode=1,year='2024',alternative_titles=[],**updates)


@pytest.mark.parametrize('payload',[
    [],None,'text',{'media_type':[],'title':'Show'},{'media_type':'movie','title':'..'},{'media_type':'tv','title':'Show','season':True,'episode':1},
    {'media_type':'tv','title':'Show','season':-1,'episode':1},
    {'media_type':'tv','title':'Show','season':1},
    {'media_type':'tv','title':' ','season':1,'episode':1},
    {'media_type':'tv','title':'Show','season':1,'episode':1,'alternative_titles':'alias'},
])
def test_bad_single_ai_result_is_controlled_unknown(payload,tmp_path,monkeypatch):
    from core import ai_client
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a:json.dumps(payload))
    result=ai_client.parse_filename_with_ai(src,{})
    assert result['media_type']=='unknown'
    assert result.get('episode') is None


def test_ai_numeric_strings_are_normalized_without_losing_zero(tmp_path,monkeypatch):
    from core import ai_client
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    payload={'media_type':'tv','title':'Show','season':'0','episode':'123','alternative_titles':[]}
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a:json.dumps(payload))
    result=ai_client.parse_filename_with_ai(src,{})
    assert (result['season'],result['episode'])==(0,123)


@pytest.mark.parametrize('name',['../foreign.mkv','/outside.mkv','not-in-batch.mkv'])
def test_folder_ai_cannot_return_a_foreign_file(name,tmp_path,monkeypatch):
    from core import ai_client
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    payload={'folder_title':'Show','media_type':'tv','files':{name:media_info()}}
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a:json.dumps(payload))
    assert ai_client.parse_folder_with_ai(tmp_path,[src],{})=={}


def test_large_folder_is_bounded_and_unreturned_files_are_explicit(tmp_path,monkeypatch):
    from core import ai_client
    files=[tmp_path/f'ep{i:03d}.mkv' for i in range(71)]
    for file in files:file.write_bytes(b'test')
    batches=[]
    def api(messages,*args):
        batch=json.loads(messages[-1]['content'])['files'];batches.append(batch)
        return json.dumps({'folder_title':'Show','media_type':'tv','files':{batch[0]:media_info()}})
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',api)
    result=ai_client.parse_folder_with_ai(tmp_path,files,{})
    assert list(map(len,batches))==[30,30,11]
    assert len(result['files'])==3 and len(result['unparsed_files'])==68
    assert set(result['files'])|set(result['unparsed_files'])=={f.name for f in files}


def test_mixed_folder_compression_preserves_per_file_values():
    from core.folder_ai_cache import _compress_folder_parse_result,_decompress_folder_parse_result
    raw={'folder_title':'Default','media_type':'tv','season':1,'year':'2024','files':{
        'show.mkv':media_info(),
        'film.mkv':{'media_type':'movie','title':'Different Film','year':'1999','season':None,'episode':None,'episode_title':'x'*100}}}
    restored=_decompress_folder_parse_result(_compress_folder_parse_result(raw))
    for name,info in raw['files'].items():
        assert all(restored['files'][name].get(key)==value for key,value in info.items())


def test_single_file_identity_changes_with_content_config_and_rules(tmp_path,monkeypatch):
    from core.parser_helpers import get_ai_parse_cache_key
    from core import parse_identity
    src=tmp_path/'input.mkv';src.write_bytes(b'one')
    config={'ai_parser':{'model':'first'}}
    first=get_ai_parse_cache_key(str(src),config)
    src.write_bytes(b'changed content')
    second=get_ai_parse_cache_key(str(src),config)
    assert second!=first
    third=get_ai_parse_cache_key(str(src),{'ai_parser':{'model':'second'}})
    assert third!=second
    monkeypatch.setattr(parse_identity,'RULE_VERSION','future-rules')
    assert get_ai_parse_cache_key(str(src),config)!=second


def test_folder_fingerprint_is_read_once_in_a_task(tmp_path,monkeypatch):
    from core import parse_identity,folder_ai_cache
    files=[tmp_path/f'{i}.mkv' for i in range(3)]
    for file in files:file.write_bytes(b'test')
    calls=[];actual=parse_identity.file_signature
    def signature(*a,**k):calls.append(1);return actual(*a,**k)
    monkeypatch.setattr(parse_identity,'file_signature',signature)
    with parse_identity.identity_scope():
        for _ in range(10):folder_ai_cache.get_cached_folder_parse(tmp_path,{'video_extensions':['.mkv']})
    assert len(calls)==3


@pytest.mark.parametrize('failure',[False,True])
def test_ten_waiters_share_result_or_exception(failure,tmp_path,monkeypatch):
    from core import parser_manager,ai_client
    from core.parse_identity import identity_scope
    files=[tmp_path/f'{i}.mkv' for i in range(2)]
    for file in files:file.write_bytes(b'test')
    started=threading.Event();release=threading.Event();gate=threading.Barrier(10)
    calls=[]
    def parse(*a,**k):
        calls.append(1);started.set();assert release.wait(5)
        if failure:raise RuntimeError('mock parse failure')
        return {'folder_title':'Show','media_type':'tv','files':{f.name:media_info() for f in files}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    def invoke():
        gate.wait(timeout=5)
        try:return parser_manager._get_or_wait_folder_parse(tmp_path,{'video_extensions':['.mkv']},None)
        except RuntimeError as exc:return str(exc)
    with identity_scope():
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures=[pool.submit(copy_context().run,invoke) for _ in range(10)]
            try:assert started.wait(5)
            finally:release.set()
            results=[f.result(timeout=5) for f in futures]
    assert len(calls)==1
    if failure:assert results==['mock parse failure']*10
    else:assert all(r and len(r['files'])==2 for r in results)


def test_offline_cache_invalidates_changed_and_added_files(tmp_path,monkeypatch):
    from core import offline_ai_preparser as offline,ai_client
    src=tmp_path/'input.mkv';src.write_bytes(b'one')
    calls=[]
    def parse(folder,files,*a,**k):
        calls.append(1)
        return {'folder_title':'Show','media_type':'tv','files':{f.name:media_info() for f in files}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    cfg={'video_extensions':['.mkv'],'ignore_patterns':[]}
    assert offline.parse_folder_on_demand(tmp_path,cfg)
    assert offline.parse_folder_on_demand(tmp_path,cfg) and len(calls)==1
    src.write_bytes(b'changed')
    assert offline.parse_folder_on_demand(tmp_path,cfg) and len(calls)==2
    (tmp_path/'new.mkv').write_bytes(b'new')
    assert len(offline.parse_folder_on_demand(tmp_path,cfg)['files'])==2 and len(calls)==3
    cfg['parse_rules_version']='changed'
    assert offline.parse_folder_on_demand(tmp_path,cfg) and len(calls)==4


def test_legacy_folder_cache_is_ignored_then_backed_up_before_replacement(tmp_path):
    from core import folder_ai_cache
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    old={str(tmp_path):{'fingerprint':'old','parse_result':{'folder_title':'old','files':{}},'updated':1}}
    folder_ai_cache.save_folder_cache(old)
    assert folder_ai_cache.get_cached_folder_parse(tmp_path,{'video_extensions':['.mkv']}) is None
    folder_ai_cache.save_folder_parse_result(tmp_path,{'folder_title':'Show','files':{src.name:media_info()}},{'video_extensions':['.mkv']})
    backups=list(tmp_path.glob(folder_ai_cache.CACHE_FILE+'.t10-*.bak'))
    assert backups and json.loads(backups[0].read_text())==old


def test_tmdb_cache_keeps_validated_media_type(config_file,tmp_path,monkeypatch):
    from core import processor_core as core,config_manager
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(tmp_path)]
    files=[tmp_path/f'{i}.mkv' for i in range(2)]
    for file in files:file.write_bytes(b'test')
    monkeypatch.setattr(core,'parse_filename_info',lambda *a:dict(media_info(),media_type='movie'))
    monkeypatch.setattr(core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(core.video_info,'get_video_duration',lambda *a:None)
    searches=[];types=[]
    monkeypatch.setattr(core,'search_tmdb_with_fallback',lambda *a,**k:(searches.append(1) or {'id':7,'title':'Show','release_date':'2024-01-01'},'movie',1))
    monkeypatch.setattr(core.tmdb_client,'get_tmdb_details',lambda **k:types.append(k['media_type']) or {'id':7,'title':'Film'})
    monkeypatch.setattr(core,'process_movie_branch',lambda *a:True)
    for src in files:assert core.process_video(src,cfg,{})
    assert searches==[1] and types==['movie','movie']


def test_invalid_ai_results_are_not_saved_by_parser_manager(tmp_path,monkeypatch):
    from core import ai_client,parser_manager
    src=tmp_path/'Unknown.mkv';src.write_bytes(b'test')
    cfg={'video_extensions':['.mkv'],'ignore_patterns':[],
         'anime_parser':{'enabled':False},'ai_parser':{'enabled':True,'batch_folder_enabled':False}}
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a:'{"media_type":"tv","title":"Show"}')
    result=parser_manager.parse_filename(src,cfg)
    assert result['media_type']=='unknown' and result['episode'] is None
    assert not list(tmp_path.glob('*cache*.json'))
    assert not parser_manager._save_parse_result('bad',{'media_type':'tv','title':'Show','episode':True})
    assert not list(tmp_path.glob('*cache*.json'))


def test_real_single_cache_rechecks_file_neighbors_and_config(tmp_path,monkeypatch):
    from core import ai_client,parser_manager
    src=tmp_path/'Unknown.mkv';src.write_bytes(b'test')
    cfg={'video_extensions':['.mkv'],'ignore_patterns':[],
         'anime_parser':{'enabled':False},'ai_parser':{'enabled':True,'batch_folder_enabled':False}}
    calls=[]
    def api(*a):calls.append(1);return json.dumps({'media_type':'movie','title':f'Result {len(calls)}'})
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',api)
    assert parser_manager.parse_filename(src,cfg)['title']=='Result 1'
    assert parser_manager.parse_filename(src,cfg)['title']=='Result 1' and len(calls)==1
    src.write_bytes(b'changed')
    assert parser_manager.parse_filename(src,cfg)['title']=='Result 2'
    (tmp_path/'second.mkv').write_bytes(b'added')
    assert parser_manager.parse_filename(src,cfg)['title']=='Result 3'
    cfg['ai_parser']['model']='different'
    assert parser_manager.parse_filename(src,cfg)['title']=='Result 4'


def test_wait_timeout_does_not_release_owner_or_start_duplicate(tmp_path,monkeypatch):
    from core import ai_client,parser_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    started=threading.Event();release=threading.Event();calls=[]
    def parse(*a,**k):
        calls.append(1);started.set();assert release.wait(5)
        return {'files':{src.name:media_info()}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    cfg={'video_extensions':['.mkv']}
    with ThreadPoolExecutor(max_workers=1) as pool:
        owner=pool.submit(parser_manager._get_or_wait_folder_parse,tmp_path,cfg,None)
        try:
            assert started.wait(5)
            monkeypatch.setattr(parser_manager,'wait_for',lambda *a:False)
            assert parser_manager._get_or_wait_folder_parse(tmp_path,cfg,None) is None
            assert not owner.done() and calls==[1]
        finally:release.set()
        assert owner.result(timeout=5)
    assert not parser_manager._ongoing_folder_parses


def test_partial_offline_result_is_not_a_complete_folder(tmp_path,monkeypatch):
    from core import ai_client,offline_ai_preparser as offline
    files=[tmp_path/f'{i:03}.mkv' for i in range(35)]
    for file in files:file.write_bytes(b'test')
    offline.save_raw_cache({str(tmp_path):[{'path':str(f),'name':f.name} for f in files]})
    def api(messages,*a):
        name=json.loads(messages[-1]['content'])['files'][0]
        return json.dumps({'files':{name:media_info()}})
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',api)
    cfg={'video_extensions':['.mkv']}
    offline.run_ai_preparse(cfg)
    summary=offline.preparse_summary(cfg)
    assert summary['success']==0 and summary['partial']==1
    assert summary['files_parsed']==2 and summary['files_unparsed']==33


def test_changed_inputs_during_ai_are_rejected_before_cache_write(tmp_path,monkeypatch):
    from core import ai_client,parser_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    def parse(*a,**k):
        src.write_bytes(b'changed while parsing')
        return {'files':{src.name:media_info()}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    with pytest.raises(OSError,match='变化'):
        parser_manager._get_or_wait_folder_parse(tmp_path,{'video_extensions':['.mkv']})
    assert not list(tmp_path.glob('*cache*.json'))


def test_ai_network_exception_retains_transient_provenance(tmp_path,monkeypatch):
    import requests
    from core import ai_client,failure_policy
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    class Session:
        def post(self,*a,**k):raise requests.Timeout('mock timeout')
    monkeypatch.setattr(ai_client,'create_session',lambda:Session())
    with failure_policy.failure_scope({}):
        assert ai_client.call_ai_api_with_messages([],{'api_key':'dummy-key'}) is None
        entry=failure_policy.make_failure(src,'AI unavailable')
    assert entry['failure_category']=='transient'


def test_single_cache_migration_backup_failure_cannot_poison_memory(tmp_path,monkeypatch):
    from core import parser_manager,cache_manager,parse_cache
    old={'legacy':{'title':'legacy value'}}
    cache_manager.save_ai_parse_cache(old)
    original=(tmp_path/cache_manager.AI_PARSE_CACHE_FILE).read_bytes()
    def fail(*a,**k):raise PermissionError('backup denied')
    monkeypatch.setattr(parse_cache,'backup_json',fail)
    with pytest.raises(PermissionError,match='backup denied'):
        parser_manager._save_parse_result('new',media_info())
    assert 'new' not in parser_manager.AI_CACHE
    assert (tmp_path/cache_manager.AI_PARSE_CACHE_FILE).read_bytes()==original


def test_corrupt_persistent_file_is_not_hidden_by_ai_memory(tmp_path,monkeypatch):
    from core import parser_manager,ai_client,cache_manager
    from core.json_store import CacheCorruptionError
    src=tmp_path/'Unknown.mkv';src.write_bytes(b'test')
    cfg={'video_extensions':['.mkv'],'ai_parser':{'enabled':True,'batch_folder_enabled':False}}
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a:'{"media_type":"movie","title":"Film"}')
    assert parser_manager.parse_filename(src,cfg)['title']=='Film'
    path=tmp_path/cache_manager.AI_PARSE_CACHE_FILE;path.write_bytes(b'{broken')
    with pytest.raises(CacheCorruptionError):parser_manager.parse_filename(src,cfg)
    assert path.read_bytes()==b'{broken'
    assert list(tmp_path.glob(path.name+'.corrupt-*.bak'))


def test_folder_header_cache_rechecks_inputs(tmp_path,monkeypatch):
    from core import folder_parser
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    calls=[]
    def parse(*a):calls.append(1);return {'media_type':'movie','title':f'Header {len(calls)}'}
    monkeypatch.setattr(folder_parser,'parse_folder_with_ai',parse)
    cfg={'video_extensions':['.mkv'],'ai_parser':{'enabled':True}}
    assert folder_parser.get_folder_meta(tmp_path,cfg)['title']=='Header 1'
    assert folder_parser.get_folder_meta(tmp_path,cfg)['title']=='Header 1' and len(calls)==1
    src.write_bytes(b'changed')
    assert folder_parser.get_folder_meta(tmp_path,cfg)['title']=='Header 2'


def test_nested_duplicate_basenames_keep_distinct_input_ids(tmp_path,monkeypatch):
    from core import ai_client
    files=[]
    for directory in ['first','second']:
        file=tmp_path/directory/'same.mkv';file.parent.mkdir();file.write_bytes(b'test');files.append(file)
    def api(messages,*a):
        names=json.loads(messages[-1]['content'])['files']
        return json.dumps({'files':{name:{'media_type':'movie','title':name} for name in names}})
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',api)
    result=ai_client.parse_folder_with_ai(tmp_path,files,{})
    assert set(result['files'])=={'first/same.mkv','second/same.mkv'}
    assert result['unparsed_files']==[]


def test_offline_stale_raw_paths_outside_sources_are_not_read(tmp_path,monkeypatch):
    from core import offline_ai_preparser as offline,ai_client,parse_identity
    allowed=tmp_path/'allowed';allowed.mkdir()
    private=tmp_path/'private';private.mkdir();(private/'input.mkv').write_bytes(b'private')
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',lambda *a,**k:pytest.fail('sent an excluded folder to AI'))
    monkeypatch.setattr(parse_identity,'file_signature',lambda *a:pytest.fail('read excluded file content'))
    assert offline.parse_folder_on_demand(private,{'source_folders':[str(allowed)],'video_extensions':['.mkv']}) is None


def test_tmdb_cache_keys_include_language_and_year(config_file,tmp_path,monkeypatch):
    from core import processor_core as core,config_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(tmp_path)]
    year=['2024'];calls=[]
    monkeypatch.setattr(core,'parse_filename_info',lambda *a:dict(media_info(),media_type='movie',year=year[0]))
    monkeypatch.setattr(core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(core.video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(core,'search_tmdb_with_fallback',lambda *a,**k:(calls.append(1) or {'id':7,'title':'Show','release_date':year[0]+'-01-01'},'movie',1))
    monkeypatch.setattr(core.tmdb_client,'get_tmdb_details',lambda **k:{'id':7,'title':'Film'})
    monkeypatch.setattr(core,'process_movie_branch',lambda *a:True)
    assert core.process_video(src,cfg,{}) and core.process_video(src,cfg,{}) and len(calls)==1
    cfg['tmdb_api']['language']='ja-JP'
    assert core.process_video(src,cfg,{}) and len(calls)==2
    year[0]='1999'
    assert core.process_video(src,cfg,{}) and len(calls)==3


def test_tmdb_structure_context_does_not_reuse_another_prompt_result(tmp_path,monkeypatch):
    from core import ai_client,parser_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    calls=[]
    def parse(*a,**k):
        title=k['tmdb_structure'];calls.append(title)
        return {'files':{src.name:media_info(title)}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    cfg={'video_extensions':['.mkv']}
    first=parser_manager._get_or_wait_folder_parse(tmp_path,cfg,None,'structure A')
    second=parser_manager._get_or_wait_folder_parse(tmp_path,cfg,None,'structure B')
    assert calls==['structure A','structure B']
    assert first['files'][src.name]['title']=='structure A'
    assert second['files'][src.name]['title']=='structure B'


def test_single_ai_rejects_file_change_before_cache_publication(tmp_path,monkeypatch):
    from core import ai_client,parser_manager
    src=tmp_path/'Unknown.mkv';src.write_bytes(b'test')
    cfg={'video_extensions':['.mkv'],'ai_parser':{'enabled':True,'batch_folder_enabled':False}}
    def api(*a):
        src.write_bytes(b'changed during AI request')
        return '{"media_type":"movie","title":"Film"}'
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',api)
    with pytest.raises(OSError,match='变化'):parser_manager.parse_filename(src,cfg)
    assert not list(tmp_path.glob('*cache*.json'))


def test_rule_upgrade_rechecks_previously_permanent_media_failure(tmp_path,monkeypatch):
    from core import failure_policy,parse_identity
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    entry=failure_policy.make_failure(src,'no match',{},category='no_match')
    assert not failure_policy.should_retry(src,entry,{})
    monkeypatch.setattr(parse_identity,'RULE_VERSION','future-version')
    assert failure_policy.should_retry(src,entry,{})
    entry['no_retry']=True
    assert not failure_policy.should_retry(src,entry,{})


def test_duplicate_ai_json_fields_are_rejected_as_ambiguous(tmp_path,monkeypatch):
    from core import ai_client
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a:
        '{"media_type":"tv","media_type":"movie","title":"Film"}')
    assert ai_client.parse_filename_with_ai(src,{})['media_type']=='unknown'
