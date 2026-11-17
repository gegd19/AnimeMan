"""R09: matching scores and evidence remain honest and backward compatible."""
import base64
import pytest


def auth():
    return {'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}


@pytest.mark.parametrize('endpoint,key', [('/api/processed_cache','items'),('/api/processed_history','history')])
def test_score_metadata_and_unknown_value_reach_api(client,monkeypatch,tmp_path,endpoint,key):
    from core import cache_manager
    cache={str(tmp_path/'old.mkv'):{'media_type':'movie','title':'Old'},
           str(tmp_path/'new.mkv'):{'media_type':'movie','title':'New','confidence':0,
                                   'score_evidence':['TMDB 标题匹配'],'score_conflicts':['多个候选'],
                                   'score_origin':'automatic'},
           str(tmp_path/'manual.mkv'):{'media_type':'movie','title':'Manual','confirmed_by_user':True}}
    monkeypatch.setattr(cache_manager,'load_cache',lambda:cache)
    response=client.get(endpoint,headers=auth())
    assert response.status_code==200
    entries={item['title']:item for item in response.get_json()[key]}
    assert entries['Old']['confidence'] is None
    assert entries['New']['confidence']==0
    assert entries['New']['score_evidence']==['TMDB 标题匹配']
    assert entries['New']['score_conflicts']==['多个候选']
    assert entries['Manual']['confirmed_by_user']


def test_automatic_score_log_does_not_claim_accuracy(tmp_path,config_file,monkeypatch):
    from core import config_manager
    from core.processor_movie import process_movie_branch
    src=tmp_path/'src'/'Movie.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['subtitle']['enabled']=False
    cfg['_recognition_score']={'origin':'automatic','evidence':['TMDB 标题匹配'],'conflicts':[]}
    cache={};messages=[]
    assert process_movie_branch(src,cfg,cache,lambda *args:messages.append(str(args[-2])), 'Movie','2020',7,{},75)
    assert cache[str(src.resolve())]['score_evidence']==['TMDB 标题匹配']
    assert any('匹配评分' in m for m in messages)
    assert all('准确率' not in m for m in messages)


def test_manual_mapping_log_does_not_claim_hundred_percent(tmp_path,config_file):
    from core import config_manager
    from core.processor_movie import process_movie_branch
    src=tmp_path/'src'/'Movie.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['subtitle']['enabled']=False
    cfg['_recognition_score']={'origin':'manual_mapping','evidence':['人工映射指定 TMDB 身份'],'conflicts':[]}
    messages=[]
    assert process_movie_branch(src,cfg,{},lambda *args:messages.append(str(args[-2])),'Movie','2020',7,{},100)
    assert any('人工指定' in m for m in messages)
    assert all('匹配评分: 100' not in m and '准确率' not in m for m in messages)


def test_real_recognition_passes_evidence_and_candidate_conflict(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Movie.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a:{'media_type':'movie','title':'Movie','search_title':'Movie','alternative_titles':[],'_parser':'anitopy'})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:({'id':7,'title':'Movie'},'movie',2))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **k:{'id':7,'title':'Movie'})
    scores=[]
    monkeypatch.setattr(processor_core,'process_movie_branch',lambda *a:scores.append(a[1]['_recognition_score']) or True)
    assert processor_core.process_video(src,cfg,{})
    assert scores[0]['origin']=='automatic'
    assert '候选标题与输入一致' in scores[0]['evidence']
    assert '搜索存在多个候选，评分已降低' in scores[0]['conflicts']


@pytest.mark.parametrize('local,reference,status', [
    (None,90,'unknown'), (35,None,'unknown'), (35,35,'supported'),
    (100,100,'supported'), (125,100,'supported'), (126,100,'conflict'),
    (34,24,'supported'), (35,24,'conflict'), (float('nan'),24,'unknown'),
])
def test_duration_evidence_boundaries(local,reference,status):
    from core.duration_evidence import compare_duration
    assert compare_duration(local,reference)['status']==status


def test_short_movie_is_not_silently_retyped(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Movie.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a:{'media_type':'movie','title':'Movie','search_title':'Movie','alternative_titles':[],'_parser':'anitopy'})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:35)
    hints=[];branches=[]
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:(hints.append(k['duration_hint']) or {'id':7,'title':'Movie'},'movie',1))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':7,'title':'Movie','runtime':90})
    monkeypatch.setattr(processor_core,'process_movie_branch',lambda *a:branches.append(1) or True)
    assert not processor_core.process_video(src,cfg,{})
    assert hints==[None] and not branches
    assert src.read_bytes()==b'synthetic'


def test_short_movie_with_matching_specific_runtime_requires_review(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Movie.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a:{'media_type':'movie','title':'Movie','search_title':'Movie','alternative_titles':[],'_parser':'anitopy'})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:35)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:({'id':7,'title':'Movie'},'movie',1))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':7,'title':'Movie','runtime':35})
    scores=[]
    monkeypatch.setattr(processor_core,'process_movie_branch',lambda *a:scores.append(a[-1]) or True)
    assert not processor_core.process_video(src,cfg,{})
    assert scores==[]


@pytest.mark.parametrize('episode_runtime,expected',[(24,False),(120,False),(None,True)])
def test_special_uses_episode_runtime_not_series_average(tmp_path,config_file,monkeypatch,episode_runtime,expected):
    from core import config_manager,tmdb_client
    from core.processor_tv import process_tv_branch
    src=tmp_path/'src'/'Special.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False,_local_video_duration=120)
    cfg['subtitle']['enabled']=False
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':1,'name':'Special','runtime':episode_runtime}])
    cache={}
    result=process_tv_branch(src,cfg,cache,None,'Show','2020',42,
        {'seasons':[{'season_number':0}],'episode_run_time':[24]},
        {'season':0,'episode':1,'explicit_season':0},75)
    assert result is expected
    assert src.read_bytes()==b'synthetic'
    if not expected:
        assert cache[str(src.resolve())]['media_type']=='failed'
        assert not list((tmp_path/'tv').rglob('*.mkv'))
        assert not list((tmp_path/'tv').rglob('*.nfo'))


def test_unrelated_title_with_same_runtime_still_cannot_match(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,processor_search,search_enhancer,tmdb_client,video_info
    src=tmp_path/'src'/'Target.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a:{'media_type':'movie','title':'Target','search_title':'Target','alternative_titles':[],'_parser':'anitopy'})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:100)
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *a:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *a:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**kw:[{'id':7,'title':'Unrelated','runtime':100}])
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**kw:pytest.fail('unrelated result must not be accepted'))
    assert not processor_core.process_video(src,cfg,{})
    assert src.read_bytes()==b'synthetic'


def test_tv_duration_conflict_in_preview_writes_nothing(tmp_path,config_file,monkeypatch):
    from core import config_manager,tmdb_client
    from core.processor_tv import process_tv_branch
    src=tmp_path/'src'/'Special.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],dry_run=True,download_images=False,_local_video_duration=120)
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':1,'name':'Special','runtime':24}])
    cache={};messages=[]
    assert not process_tv_branch(src,cfg,cache,lambda *a:messages.append(str(a[-2])),'Show','2020',42,
        {'seasons':[{'season_number':0}]},{'season':0,'episode':1,'explicit_season':0},75)
    assert not cache and not (tmp_path/'tv').exists()
    assert any('人工确认' in m for m in messages)
    assert src.read_bytes()==b'synthetic'
