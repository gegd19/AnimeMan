"""E04: typed alias provenance and semantic search variants."""
import pytest


def test_alias_records_allow_ambiguous_names_and_keep_identity_types(tmp_path):
    from core import recognition_aliases as aliases
    aliases.add_alias('同名', 'tv', 42, 'manual', year='2001')
    aliases.add_alias('同名', 'movie', 43, 'tmdb', year='2002')
    aliases.add_alias('同名', 'tv', 44, 'nfo', year='2003')
    result = aliases.find_aliases(' 同名 ')
    assert {(r['media_type'],r['tmdb_id'],r['year']) for r in result} == {('tv',42,'2001'),('movie',43,'2002'),('tv',44,'2003')}


def test_alias_normalization_preserves_roman_numerals_and_multilingual_names(tmp_path):
    from core import recognition_aliases as aliases
    for title in ['作品', '作品 II', 'Title III', 'タイトル', 'Sakuhin']:
        aliases.add_alias(title,'tv',42,'manual')
    assert aliases.find_aliases('作品 ii')[0]['name']=='作品 II'
    assert aliases.find_aliases('作品 i') == []
    assert aliases.find_aliases('タイトル')[0]['tmdb_id']==42
    assert aliases.find_aliases('ＳＡＫＵＨＩＮ')[0]['tmdb_id']==42


def test_ai_alias_is_search_hint_only_and_empty_values_rejected(tmp_path):
    from core import recognition_aliases as aliases
    aliases.add_alias('hint','tv',42,'ai')
    assert aliases.find_aliases('hint')[0]['trusted'] is False
    with pytest.raises(ValueError): aliases.add_alias('  ','tv',42,'manual')
    with pytest.raises(ValueError): aliases.add_alias('title','tv',True,'manual')
    with pytest.raises(ValueError): aliases.add_alias('title','tv',42,'invented')


def test_alias_hot_updates_and_legacy_file_is_untouched(tmp_path):
    import json
    from core import recognition_aliases as aliases
    old=tmp_path/'tmdb_aliases.json'; old.write_text(json.dumps({'Old':{'tmdb_id':9,'media_type':'tv'}}))
    raw=old.read_bytes();before=aliases.revision()
    aliases.add_alias('New','tv',42,'manual')
    assert aliases.revision()!=before and aliases.find_aliases('new')[0]['tmdb_id']==42
    assert old.read_bytes()==raw
    legacy=aliases.find_aliases('old')[0]
    assert legacy['source']=='legacy' and legacy['trusted'] is False
    old.write_text(json.dumps({'Other':{'tmdb_id':8,'media_type':'movie'}}))
    assert aliases.find_aliases('old')==[] and aliases.find_aliases('other')[0]['tmdb_id']==8


def test_bad_alias_schema_is_rejected_without_replacing_data(tmp_path):
    from core import recognition_aliases as aliases
    path=tmp_path/'recognition_aliases_v1.json';path.write_text('{"schema":99,"records":[]}')
    raw=path.read_bytes()
    with pytest.raises(ValueError): aliases.add_alias('Show','tv',42,'manual')
    assert path.read_bytes()==raw


def test_scoped_alias_is_never_applied_outside_scope(tmp_path):
    from core import recognition_aliases as aliases
    root=tmp_path/'source'; scoped=root/'show'; outside=root/'other'
    scoped.mkdir(parents=True); outside.mkdir()
    aliases.add_alias('Show','tv',42,'manual',scope=str(scoped))
    assert aliases.find_aliases('show',src=scoped/'file.mkv')[0]['tmdb_id']==42
    assert aliases.find_aliases('show',src=outside/'file.mkv')==[]
    assert aliases.find_aliases('show')==[]


def test_duplicate_records_are_idempotent(tmp_path):
    from core import recognition_aliases as aliases
    aliases.add_alias('Show','tv',42,'manual')
    before=aliases.revision()
    aliases.add_alias('Show','tv',42,'manual')
    assert aliases.revision()==before and len(aliases.find_aliases('Show'))==1


def test_search_variants_keep_original_and_sequel_chapter_tokens():
    from core.processor_helpers import prepare_search_query
    from core.search_enhancer import generate_search_candidates
    title='Example II: 终章 1080p'
    original,query,year,alternatives=prepare_search_query({'title':title,'search_title':title}, {'1080p'})
    assert original==title and query==title
    assert any('Example II: 终章' == item for item in alternatives)
    assert all('II' in item and '终章' in item for item in generate_search_candidates(title))


def test_variants_are_deduplicated_and_bounded():
    from core.processor_helpers import prepare_search_query
    values=['ＡＢＣ','abc','Other',' Other ','Third','Fourth','Fifth','Sixth']
    _,query,_,alternatives=prepare_search_query({'title':'ABC','alternative_titles':values}, set())
    normalized=[item.casefold().strip() for item in [query,*alternatives]]
    assert len(alternatives)<=8 and len(normalized)==len(set(normalized))


def search_cfg():
    return {'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':False}}


def test_trusted_multilingual_aliases_are_bound_to_the_verified_identity(monkeypatch):
    from core import recognition_aliases as aliases,processor_search,tmdb_client
    aliases.add_alias('Sakuhin','tv',42,'manual')
    aliases.add_alias('作品','tv',42,'tmdb')
    calls=[]
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda kind,ident,*a,**k:(calls.append((kind,ident)) or {'id':ident,'name':'作品','first_air_date':'2020-01-01'}))
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[])
    result,kind,_=processor_search.search_tmdb_with_fallback('tv','Sakuhin','2020',[],search_cfg())
    assert result['id']==42 and kind=='tv' and calls==[('tv',42)]


def test_same_alias_multiple_works_cannot_choose_first(monkeypatch):
    from core import recognition_aliases as aliases,processor_search,tmdb_client
    aliases.add_alias('Shared','tv',42,'manual',year='2001')
    aliases.add_alias('Shared','tv',43,'manual',year='2002')
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda kind,ident,*a,**k:{'id':ident,'name':'Shared','first_air_date':f'{2001 if ident==42 else 2002}-01-01'})
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[])
    ambiguous,_,_=processor_search.search_tmdb_with_fallback('tv','Shared',None,[],search_cfg())
    exact,_,_=processor_search.search_tmdb_with_fallback('tv','Shared','2002',[],search_cfg())
    assert ambiguous is None and exact['id']==43


def test_ai_generated_alias_cannot_establish_identity(monkeypatch):
    from core import recognition_aliases as aliases,processor_search,tmdb_client
    aliases.add_alias('Suggestion','tv',42,'ai')
    aliases.add_alias('Original','tv',42,'manual')
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:pytest.fail('AI alias cannot authorize fetching ID as confirmed'))
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[])
    assert processor_search.search_tmdb_with_fallback('tv','Suggestion',None,[],search_cfg())[0] is None


def test_alias_revision_invalidates_parser_policy_and_legacy_readers_refresh(tmp_path):
    import json
    from core import recognition_aliases as aliases,parse_identity,processor_search,search_enhancer
    cfg={};before=parse_identity.policy_key(cfg)
    aliases.add_alias('Show','tv',42,'manual')
    assert parse_identity.policy_key(cfg)!=before
    path=tmp_path/'tmdb_aliases.json'
    path.write_text(json.dumps({'old':{'tmdb_id':1,'media_type':'tv'}}))
    assert processor_search._lookup_local_alias('old')['tmdb_id']==1
    assert search_enhancer.lookup_local_alias('old')['tmdb_id']==1
    path.write_text(json.dumps({'new':{'tmdb_id':2,'media_type':'tv'}}))
    assert processor_search._lookup_local_alias('new')['tmdb_id']==2
    assert search_enhancer.lookup_local_alias('new')['tmdb_id']==2


def test_ai_alias_expands_search_but_not_candidate_identity(monkeypatch):
    from core import recognition_aliases as aliases,processor_search,tmdb_client
    aliases.add_alias('Suggestion','tv',42,'ai')
    aliases.add_alias('Original','tv',42,'manual')
    queries=[]
    def search(kind,query,*args,**kwargs):
        queries.append(query)
        return [{'id':42,'name':'Original'}] if query=='Original' else []
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',search)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:pytest.fail('untrusted hint must not directly fetch'))
    assert processor_search.search_tmdb_with_fallback('tv','Suggestion',None,[],search_cfg())[0] is None
    assert 'Original' in queries and len(queries)<=8


def test_legacy_alias_year_conflict_cannot_override_matching_result(tmp_path,monkeypatch):
    import json
    from core import processor_search,tmdb_client
    (tmp_path/'tmdb_aliases.json').write_text(json.dumps({'Show':{'tmdb_id':42,'media_type':'tv'}}))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'Show','first_air_date':'1990-01-01'})
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[{'id':43,'name':'Show','first_air_date':'2020-01-01'}])
    result,_,_=processor_search.search_tmdb_with_fallback('tv','Show','2020',[],search_cfg())
    assert result['id']==43


def test_tmdb_alternative_titles_from_both_supported_shapes_are_evidence():
    from core.candidate_evaluator import evaluate_candidates
    from core.processor_helpers import extract_all_alternative_titles
    item={'id':42,'name':'作品','alternative_titles':{'results':[{'title':'Sakuhin'}], 'titles':[{'title':'The Work'}]}}
    assert evaluate_candidates([item],'tv',['Sakuhin'])['selected']['id']==42
    assert set(extract_all_alternative_titles(item,'作品')) >= {'作品','Sakuhin','The Work'}
    assert evaluate_candidates([item],'tv',['Other'])['selected'] is None


def test_tmdb_generic_alias_does_not_override_explicit_sequel_title():
    from core.candidate_evaluator import evaluate_candidates
    item={'id':42,'name':'Show II','alternative_titles':{'results':[{'title':'Show'}]}}
    assert evaluate_candidates([item],'tv',['Show'])['selected'] is None
    assert evaluate_candidates([item],'tv',['Show II'])['selected']['id']==42


def test_scoped_alias_rejects_parent_traversal_and_symlink(tmp_path):
    from core import recognition_aliases as aliases
    root=tmp_path/'root';root.mkdir();other=tmp_path/'other';other.mkdir()
    link=root/'link';link.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError): aliases.add_alias('Show','tv',42,'manual',scope=str(root/'..'/'other'))
    with pytest.raises(ValueError): aliases.add_alias('Show','tv',42,'manual',scope=str(link))


def test_alias_record_year_must_agree_with_tmdb_details(monkeypatch):
    from core import recognition_aliases as aliases,processor_search,tmdb_client
    aliases.add_alias('Alias','tv',42,'manual',year='2001')
    aliases.add_alias('Original','tv',42,'tmdb',year='2001')
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'id':42,'name':'Original','first_air_date':'2002-01-01'})
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[{'id':42,'name':'Original','first_air_date':'2002-01-01'}])
    assert processor_search.search_tmdb_with_fallback('tv','Alias',None,[],search_cfg())[0] is None
