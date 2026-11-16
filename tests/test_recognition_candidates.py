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
