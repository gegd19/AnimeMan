"""Verify TMDB detail aliases without trusting a directory name or a lone hit."""
import pytest


def config(enabled=True):
    return {'tmdb_api':{'api_key':'synthetic','language':'zh-CN'},
            'ai_parser':{'enabled':False},'recognition_aliases':{'enabled':enabled}}


def run(monkeypatch, candidates, details, *, enabled=True, year='2020'):
    from core import processor_search, tmdb_client
    calls=[]
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:candidates)
    def detail(kind,ident,*a,**kw):
        calls.append((kind,ident))
        return details.get(ident)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',detail)
    selected,kind,_=processor_search.search_tmdb_with_fallback('tv','Sakura no Uta',year,[],config(enabled))
    return selected,kind,calls


def test_verified_detail_alias_resolves_localized_search_candidate(monkeypatch):
    candidate={'id':42,'name':'樱花之歌','first_air_date':'2020-01-01'}
    detail={**candidate,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}}
    selected,kind,calls=run(monkeypatch,[candidate],{42:detail})
    assert selected['id']==42 and kind=='tv' and calls==[('tv',42)]


def test_directory_or_single_candidate_without_confirmed_alias_stays_review(monkeypatch):
    candidate={'id':42,'name':'樱花之歌','first_air_date':'2020-01-01'}
    selected,_,calls=run(monkeypatch,[candidate],{42:candidate})
    assert selected is None and calls==[('tv',42)]


def test_multiple_matching_detail_aliases_are_ambiguous(monkeypatch):
    candidates=[{'id':42,'name':'作品甲'},{'id':43,'name':'作品乙'}]
    details={item['id']:{**item,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}} for item in candidates}
    selected,_,calls=run(monkeypatch,candidates,details,year=None)
    assert selected is None and set(calls)=={('tv',42),('tv',43)}


def test_conflicting_detail_year_or_identity_never_resolves(monkeypatch):
    candidate={'id':42,'name':'樱花之歌','first_air_date':'2020-01-01'}
    for detail in [
        {'id':43,'name':'樱花之歌','first_air_date':'2020-01-01','alternative_titles':{'results':[{'title':'Sakura no Uta'}]}},
        {'id':42,'name':'樱花之歌','first_air_date':'2019-01-01','alternative_titles':{'results':[{'title':'Sakura no Uta'}]}},
        {'id':42,'title':'樱花之歌','alternative_titles':{'results':[{'title':'Sakura no Uta'}]}},
    ]:
        assert run(monkeypatch,[candidate],{42:detail})[0] is None


def test_detail_fallback_is_disabled_by_default_and_bounded(monkeypatch):
    one=[{'id':42,'name':'樱花之歌'}]
    assert run(monkeypatch,one,{42:one[0]},enabled=False)[2]==[]
    many=[{'id':n,'name':f'作品{n}'} for n in range(1,6)]
    selected,_,calls=run(monkeypatch,many,{item['id']:item for item in many})
    assert selected is None and calls==[]


def test_processor_accepts_only_verified_detail_alias_without_touching_source(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    root=tmp_path/'source';folder=root/'樱花之歌';folder.mkdir(parents=True)
    src=folder/'Sakura no Uta S01E01.mkv';src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file)
    cfg.update(source_folders=[str(root)],recognition_aliases={'enabled':True})
    candidate={'id':42,'name':'樱花之歌','first_air_date':'2020-01-01'}
    detail={**candidate,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]},'seasons':[{'season_number':1}]}
    calls=[]
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[candidate])
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:(calls.append(1) or detail))
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    observed=[];monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:(observed.append(a) or True))
    assert processor_core.process_video(src,cfg,{})
    assert observed and observed[0][6]==42 and len(calls)==2
    assert '候选标题或已核验备用标题与输入一致' in observed[0][-2]['_recognition_score']['evidence']
    assert src.read_bytes()==b'synthetic'


def test_detail_fallback_never_ignores_conflicting_sequel_suffix(monkeypatch):
    candidate={'id':42,'name':'Sakura no Uta II','first_air_date':'2020-01-01'}
    details={**candidate,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}}
    selected,_,_=run(monkeypatch,[candidate],{42:details})
    assert selected is None


def test_one_unavailable_detail_cannot_hide_ambiguous_candidate(monkeypatch):
    candidates=[{'id':42,'name':'作品甲'},{'id':43,'name':'作品乙'}]
    details={42:{**candidates[0],'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}},43:None}
    selected,_,calls=run(monkeypatch,candidates,details,year=None)
    assert selected is None and set(calls)=={('tv',42),('tv',43)}


def test_ambiguous_detail_aliases_do_not_fall_through_to_ai(monkeypatch):
    from core import processor_search,tmdb_client
    candidates=[{'id':42,'name':'作品甲'},{'id':43,'name':'作品乙'}]
    details={c['id']:{**c,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}} for c in candidates}
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:candidates)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda kind,ident,*a,**k:details[ident])
    monkeypatch.setattr(processor_search,'ai_verify_and_correct_title',lambda *a,**k:pytest.fail('ambiguity must not be overridden'))
    cfg=config();cfg['ai_parser']['enabled']=True
    assert processor_search.search_tmdb_with_fallback('tv','Sakura no Uta',None,[],cfg,src=__import__('pathlib').Path('/synthetic/file.mkv'))[0] is None


def test_detail_network_error_is_not_converted_into_valid_candidate(monkeypatch):
    import requests
    from core import processor_search,tmdb_client
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[{'id':42,'name':'作品'}])
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:(_ for _ in ()).throw(requests.Timeout('synthetic')))
    with pytest.raises(requests.Timeout):
        processor_search.search_tmdb_with_fallback('tv','Sakura no Uta',None,[],config())


def test_changed_detail_after_alias_selection_never_reaches_media_branch(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Sakura no Uta S01E01.mkv';src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],recognition_aliases={'enabled':True})
    candidate={'id':42,'name':'樱花之歌','first_air_date':'2020-01-01'}
    verified={**candidate,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}}
    changed={'id':43,'name':'其他作品','first_air_date':'2020-01-01'}
    responses=iter([verified,changed])
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[candidate])
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:next(responses))
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:pytest.fail('changed identity must not write'))
    assert not processor_core.process_video(src,cfg,{})
    assert src.read_bytes()==b'synthetic'


def test_removed_alias_after_selection_cannot_be_replaced_with_ai(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info,ai_client
    root=tmp_path/'source';folder=root/'Show';folder.mkdir(parents=True)
    src=folder/'Sakura no Uta S01E01.mkv';src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],recognition_aliases={'enabled':True})
    cfg['ai_parser'].update(enabled=True,api_key='synthetic')
    candidate={'id':42,'name':'樱花之歌','first_air_date':'2020-01-01'}
    verified={**candidate,'alternative_titles':{'results':[{'title':'Sakura no Uta'}]}}
    responses=iter([verified,candidate])
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[candidate])
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:next(responses))
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(ai_client,'parse_filename_with_ai',lambda *a,**k:pytest.fail('changed evidence must stop before AI'))
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:pytest.fail('removed alias must not write'))
    assert not processor_core.process_video(src,cfg,{})
    assert src.read_bytes()==b'synthetic'
