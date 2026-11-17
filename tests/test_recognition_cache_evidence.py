"""R07: cache hits must retain validated evidence and not invent confidence."""
import pytest


def setup_movie(tmp_path, config_file, monkeypatch, *, details):
    from core import config_manager, processor_core as core, video_info, tmdb_client
    src=tmp_path/'source'/'Show.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],dry_run=False)
    monkeypatch.setattr(core,'parse_filename_info',lambda *a:{'media_type':'movie','title':'Show','search_title':'Show','year':'2020','alternative_titles':[]})
    monkeypatch.setattr(core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    calls=[];scores=[]
    monkeypatch.setattr(core,'search_tmdb_with_fallback',lambda *a,**k:(calls.append(1) or {'id':7,'title':'Show','release_date':'2020-01-01'},'movie',2))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **k:details())
    monkeypatch.setattr(core,'process_movie_branch',lambda *args:scores.append(args[-1]) or True)
    core._folder_tmdb_cache.clear()
    return core,src,cfg,calls,scores


def test_failed_details_never_cached_as_verified(tmp_path,config_file,monkeypatch):
    core,src,cfg,calls,scores=setup_movie(tmp_path,config_file,monkeypatch,details=lambda:None)
    try:
        assert not core.process_video(src,cfg,{})
        assert not core._folder_tmdb_cache
        assert not core.process_video(src,cfg,{})
        assert len(calls)==2
    finally:core._folder_tmdb_cache.clear()


def test_cold_and_warm_decisions_match_and_cache_has_evidence(tmp_path,config_file,monkeypatch):
    core,src,cfg,calls,scores=setup_movie(tmp_path,config_file,monkeypatch,details=lambda:{'id':7,'title':'Show','release_date':'2020-01-01'})
    try:
        assert core.process_video(src,cfg,{}) and core.process_video(src,cfg,{})
        assert len(calls)==1 and scores[0]==scores[1]
        entry=next(iter(core._folder_tmdb_cache.values()))
        assert entry['validation_stage']=='details_verified'
        assert entry['rule_version']
        assert entry['evidence'] and entry['ambiguity']=='resolved'
    finally:core._folder_tmdb_cache.clear()


def test_folder_context_does_not_reuse_other_title(tmp_path,monkeypatch):
    from core import processor_folder_ai as f
    folder=tmp_path/'Series A';folder.mkdir()
    monkeypatch.setattr(f,'tmdb_scope',lambda *a:'scope')
    searches=[]
    monkeypatch.setattr(f,'_search_tmdb_for_folder',lambda *a,**k: searches.append(1) or [{'id':1,'name':'Series A'}])
    monkeypatch.setattr(f,'_get_tmdb_structure',lambda *a,**k:'structure')
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    f._tmdb_search_cache.clear()
    try:
        assert f._get_tmdb_info_for_folder(folder,cfg,{'title':'Series A'})[0]==1
        assert f._get_tmdb_info_for_folder(folder,cfg,{'title':'Series B'})==(None,None)
        assert len(searches)==2
    finally:f._tmdb_search_cache.clear()


def test_missing_folder_structure_not_cached(tmp_path,monkeypatch):
    from core import processor_folder_ai as f
    folder=tmp_path/'Series';folder.mkdir()
    monkeypatch.setattr(f,'tmdb_scope',lambda *a:'scope')
    monkeypatch.setattr(f,'_search_tmdb_for_folder',lambda *a,**k:[{'id':1,'name':'Series'}])
    monkeypatch.setattr(f,'_get_tmdb_structure',lambda *a,**k:None)
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    f._tmdb_search_cache.clear()
    try:
        assert f._get_tmdb_info_for_folder(folder,cfg)==(None,None)
        assert not f._tmdb_search_cache
    finally:f._tmdb_search_cache.clear()


def test_file_config_and_rule_changes_invalidate_cache(tmp_path,config_file,monkeypatch):
    from core import parse_identity
    core,src,cfg,calls,_=setup_movie(tmp_path,config_file,monkeypatch,details=lambda:{'id':7,'title':'Show','release_date':'2020-01-01'})
    try:
        assert core.process_video(src,cfg,{}) and len(calls)==1
        assert core.process_video(src,cfg,{}) and len(calls)==1
        src.write_bytes(b'changed synthetic content')
        assert core.process_video(src,cfg,{}) and len(calls)==2
        cfg['tmdb_api']['language']='ja-JP'
        assert core.process_video(src,cfg,{}) and len(calls)==3
        monkeypatch.setattr(parse_identity,'RULE_VERSION','synthetic-new-rule')
        assert core.process_video(src,cfg,{}) and len(calls)==4
    finally:core._folder_tmdb_cache.clear()


def test_preview_never_creates_candidate_cache(tmp_path,config_file,monkeypatch):
    core,src,cfg,calls,_=setup_movie(tmp_path,config_file,monkeypatch,details=lambda:{'id':7,'title':'Show','release_date':'2020-01-01'})
    cfg['dry_run']=True
    try:
        assert core.process_video(src,cfg,{})
        assert not core._folder_tmdb_cache
    finally:core._folder_tmdb_cache.clear()


def test_folder_cache_preserves_original_title_evidence(tmp_path,monkeypatch):
    from core import processor_folder_ai as f
    folder=tmp_path/'Original';folder.mkdir()
    monkeypatch.setattr(f,'tmdb_scope',lambda *a:'scope')
    calls=[]
    monkeypatch.setattr(f,'_search_tmdb_for_folder',lambda *a,**k:calls.append(1) or [{'id':1,'name':'翻译标题','original_name':'Original'}])
    monkeypatch.setattr(f,'_get_tmdb_structure',lambda *a,**k:'structure')
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    f._tmdb_search_cache.clear()
    try:
        assert f._get_tmdb_info_for_folder(folder,cfg,{'title':'Original'})==(1,'structure')
        assert f._get_tmdb_info_for_folder(folder,cfg,{'title':'Original'})==(1,'structure')
        assert len(calls)==1
    finally:f._tmdb_search_cache.clear()


def test_mixed_folder_series_caches_are_separate(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core as core,video_info,tmdb_client
    folder=tmp_path/'mixed';folder.mkdir()
    files=[folder/'Alpha.mkv',folder/'Beta.mkv']
    for file in files:file.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(folder)],dry_run=False)
    monkeypatch.setattr(core,'parse_filename_info',lambda src,*a:{'media_type':'movie','title':src.stem,'search_title':src.stem,'year':'2020','alternative_titles':[]})
    monkeypatch.setattr(core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    calls=[];selected=[]
    def search(kind,title,*a,**k):
        calls.append(title);return {'id':1 if title=='Alpha' else 2,'title':title,'release_date':'2020-01-01'},'movie',1
    monkeypatch.setattr(core,'search_tmdb_with_fallback',search)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **k:{'id':k['tmdb_id'],'title':'Alpha' if k['tmdb_id']==1 else 'Beta'})
    monkeypatch.setattr(core,'process_movie_branch',lambda *a:selected.append(a[6]) or True)
    core._folder_tmdb_cache.clear()
    try:
        assert all(core.process_video(src,cfg,{}) for src in files+files)
        assert calls==['Alpha','Beta']
        assert selected==[1,2,1,2]
    finally:core._folder_tmdb_cache.clear()


def test_folder_structure_rejects_mismatched_details(monkeypatch):
    from core import processor_folder_ai as f, tmdb_client
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':2,'name':'Wrong','seasons':[{'season_number':1,'episode_count':12}]})
    cfg={'tmdb_api':{'api_key':'synthetic'}}
    assert f._get_tmdb_structure(1,cfg) is None
