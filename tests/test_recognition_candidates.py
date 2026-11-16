"""R05 candidate evidence and ambiguity checks."""
import pytest


def item(id, title, year=None):
    return {'id':id,'name':title,'first_air_date':None if year is None else f'{year}-01-01'}


def test_unrelated_title_rejected_even_when_year_matches():
    from core.candidate_evaluator import evaluate_candidates
    result = evaluate_candidates([item(1,'Unrelated',2020)],'tv',['Target'],'2020')
    assert result['selected'] is None
    assert result['candidates'][0]['reason'] == 'title_mismatch'


def test_same_title_year_and_null_date():
    from core.candidate_evaluator import evaluate_candidates
    result = evaluate_candidates([item(1,'Target',1990),item(2,'Target',2020),item(3,'Target')],'tv',['Target'],'2020')
    assert result['selected']['id'] == 2
    assert result['candidates'][0]['media_type'] == 'tv'


def test_sequel_is_not_original_and_ambiguous_tie_rejected():
    from core.candidate_evaluator import evaluate_candidates
    result=evaluate_candidates([item(1,'Target II'),item(2,'Target')],'tv',['Target'])
    assert result['selected']['id']==2
    assert evaluate_candidates([item(1,'Target'),item(2,'Target')],'tv',['Target'])['selected'] is None


def test_entire_results_page_and_aliases_are_considered():
    from core.candidate_evaluator import evaluate_candidates
    results=[item(n,f'Unrelated {n}') for n in range(1,6)]+[item(6,'星空')]
    result=evaluate_candidates(results,'tv',['Starry Sky','星空'])
    assert result['selected']['id']==6
    assert 'exact_title' in result['candidates'][-1]['evidence']


def test_invalid_id_and_type_rejected():
    from core.candidate_evaluator import evaluate_candidates
    assert evaluate_candidates([item(True,'Target')],'tv',['Target'])['selected'] is None
    assert evaluate_candidates([item(1,'Target')],'unknown',['Target'])['selected'] is None


def test_unrelated_single_result_rejected(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[item(1,'Unrelated',2020)])
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,_,_=processor_search.search_tmdb_with_fallback('tv','Target','2020',[],cfg)
    assert result is None


def test_search_continues_after_unreliable_first_result_and_considers_sixth(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    calls=[]
    def search(kind, query, *args, **kwargs):
        calls.append((kind,query))
        if kind!='tv':return []
        if query=='Target':return [item(20,'Wrong')]
        return [item(i,f'Wrong {i}') for i in range(1,6)]+[item(6,'Alternative')]
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',search)
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,kind,_=processor_search.search_tmdb_with_fallback('tv','Target',None,['Alternative'],cfg)
    assert result['id']==6 and kind=='tv'
    assert ('tv','Alternative') in calls


def test_type_conflict_never_silently_switches(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    def search(kind, *args, **kwargs):
        return [] if kind=='tv' else [{'id':7,'title':'Target','release_date':'2020-01-01'}]
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',search)
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,_,_=processor_search.search_tmdb_with_fallback('tv','Target',None,[],cfg)
    assert result is None


def test_unknown_type_with_two_exact_candidates_is_ambiguous(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda kind,*a,**k:[{'id':7,'name':'Target','title':'Target'}])
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,_,_=processor_search.search_tmdb_with_fallback('unknown','Target',None,[],cfg)
    assert result is None


def test_unknown_type_with_one_reliable_candidate(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda kind,*a,**k:[{'id':7,'name':'Target'}] if kind=='tv' else [])
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,kind,_=processor_search.search_tmdb_with_fallback('unknown','Target',None,[],cfg)
    assert result['id']==7 and kind=='tv'


def test_folder_multiple_weak_candidates_do_not_select_first(tmp_path,monkeypatch):
    from core import processor_folder_ai as f
    folder=tmp_path/'Target';folder.mkdir()
    monkeypatch.setattr(f,'tmdb_scope',lambda *a:'folder-key')
    f._tmdb_search_cache.clear()
    monkeypatch.setattr(f,'_search_tmdb_for_folder',lambda *a,**k:[item(1,'Wrong'),item(2,'Wrong II')])
    monkeypatch.setattr(f,'_ai_select_tmdb_series',lambda *a,**k:None)
    monkeypatch.setattr(f,'_get_tmdb_structure',lambda *a,**k:'synthetic structure')
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    assert f._get_tmdb_info_for_folder(folder,cfg) == (None,None)
    assert 'folder-key' not in f._tmdb_search_cache


def test_unrelated_alias_does_not_bypass_evaluation(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:{'tmdb_id':1,'media_type':'tv'})
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:item(1,'Wrong'))
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[])
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,_,_=processor_search.search_tmdb_with_fallback('tv','Target',None,[],cfg)
    assert result is None


def test_tvmaze_fallback_cannot_bypass_title_evidence(monkeypatch):
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'search_tvmaze',lambda *a,**k:7)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[])
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:item(7,'Wrong'))
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    result,_,_=processor_search.search_tmdb_with_fallback('tv','Target',None,[],cfg)
    assert result is None


def test_legacy_fallback_does_not_change_explicit_type(monkeypatch):
    from core import processor_search, tmdb_client
    calls=[]
    def search(kind,*a,**kw):
        calls.append(kind)
        return {'id':7,'title':'Target','release_date':'2020-01-01'}
    monkeypatch.setattr(tmdb_client,'search_tmdb',search)
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    result,kind,_=processor_search.original_search_tmdb('tv','Target',None,[],cfg,duration_hint='movie')
    assert kind == 'tv'
    assert all(call=='tv' for call in calls)


def test_tmdb_timeout_retains_transient_category(monkeypatch,tmp_path):
    import requests
    from core import processor_search, search_enhancer, tmdb_client
    from core.failure_policy import failure_scope, make_failure
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k: (_ for _ in ()).throw(requests.Timeout('synthetic')))
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}
    src=tmp_path/'synthetic.mkv';src.write_bytes(b'synthetic')
    with failure_scope(cfg):
        result,_,_=processor_search.search_tmdb_with_fallback('tv','Target',None,[],cfg)
        entry=make_failure(src,'no match',cfg)
    assert result is None
    assert entry['failure_category']=='transient' and entry['retry_after'] is not None


def test_legacy_folder_cache_cannot_bypass_candidate_evidence(tmp_path,config_file,monkeypatch):
    from core import processor_core,config_manager,video_info,tmdb_client
    src=tmp_path/'source'/'Target S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],dry_run=False)
    monkeypatch.setattr(processor_core,'tmdb_scope',lambda *a:'synthetic-scope')
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a:{'title':'Target','search_title':'Target','media_type':'tv','season':1,'episode':1,'alternative_titles':[]})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    calls=[]
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:(calls.append(True) or (None,'tv',0)))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:pytest.fail('legacy cache must not bypass search'))
    processor_core._folder_tmdb_cache.clear()
    processor_core._folder_tmdb_cache[('synthetic-scope','Target','tv',None,(),None)]={'id':7,'media_type':'tv'}
    try:
        assert not processor_core.process_video(src,cfg,{})
        assert calls
    finally:
        processor_core._folder_tmdb_cache.clear()


def test_ai_cannot_force_ambiguous_candidate(monkeypatch):
    from pathlib import Path
    from core import processor_search, search_enhancer, tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'search_tvmaze',lambda *a,**k:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[item(1,'Target'),item(2,'Target')])
    monkeypatch.setattr(processor_search,'ai_select_best_match',lambda *a,**k:item(1,'Target'))
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    result,_,_=processor_search.search_tmdb_with_fallback('tv','Target',None,[],cfg,src=Path('/synthetic/Target.mkv'))
    assert result is None


def test_movie_candidate_null_date_is_safe():
    from core.candidate_evaluator import evaluate_candidates
    result=evaluate_candidates([{'id':7,'title':'Target','release_date':None}],'movie',['Target'],'2020')
    assert result['selected']['id']==7
