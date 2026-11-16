"""R06: AI selections must be structured and remain suggestions."""
from pathlib import Path
import pytest

CANDIDATES=[{'id':101,'name':'Target'}, {'id':202,'name':'Target'}]

@pytest.mark.parametrize('response',[
    '排除 1，应该选 2', '排除 101，应该选 202', '2020 年选择 101', '{"selected_id":999,"media_type":"tv","reason":"x"}',
    '{"selected_id":true,"media_type":"tv","reason":"x"}',
    '{"selected_id":101.0,"media_type":"tv","reason":"x"}',
    '{"selected_id":101,"media_type":"movie","reason":"x"}',
    '{"selected_id":null,"media_type":"tv","reason":"无法确认"}',
    '{"selected_id":101,"selected_id":202,"media_type":"tv","reason":"x"}',
])
def test_selection_invalid_or_abstain_is_not_a_match(tmp_path,monkeypatch,response):
    from core import processor_search, processor_folder_ai, ai_client
    monkeypatch.setattr(ai_client,'call_ai_api',lambda *a,**kw:response)
    cfg={'ai_parser':{'enabled':True},'video_extensions':['.mkv']}
    assert processor_search.ai_select_best_match(tmp_path/'Title.mkv',CANDIDATES,'Target','tv',cfg) is None
    assert processor_folder_ai._ai_select_tmdb_series(tmp_path,CANDIDATES,cfg) is None


def test_structured_selection_does_not_bypass_ambiguous_evidence(tmp_path,monkeypatch):
    from core import processor_search,processor_folder_ai,ai_client
    monkeypatch.setattr(ai_client,'call_ai_api',lambda *a,**kw:'{"selected_id":101,"media_type":"tv","reason":"x"}')
    cfg={'ai_parser':{'enabled':True},'video_extensions':['.mkv']}
    assert processor_search.ai_select_best_match(tmp_path/'Title.mkv',CANDIDATES,'Target','tv',cfg) is None
    assert processor_folder_ai._ai_select_tmdb_series(tmp_path,CANDIDATES,cfg) is None


def test_disabled_ai_never_called(tmp_path,monkeypatch):
    from core import processor_search,processor_folder_ai,ai_client
    monkeypatch.setattr(ai_client,'call_ai_api',lambda *a,**kw:pytest.fail('AI disabled'))
    cfg={'ai_parser':{'enabled':False}}
    assert processor_search.ai_select_best_match(tmp_path/'Title.mkv',CANDIDATES,'Target','tv',cfg) is None
    assert processor_folder_ai._ai_select_tmdb_series(tmp_path,CANDIDATES,cfg) is None


def test_structured_selection_accepts_only_matching_unambiguous_candidate(tmp_path,monkeypatch):
    from core import processor_search,processor_folder_ai,ai_client
    folder=tmp_path/'Target';folder.mkdir()
    candidates=[{'id':101,'name':'Target'}, {'id':202,'name':'Unrelated'}]
    monkeypatch.setattr(ai_client,'call_ai_api',lambda *a,**kw:'{"selected_id":101,"media_type":"tv","reason":"exact"}')
    cfg={'ai_parser':{'enabled':True},'video_extensions':['.mkv']}
    assert processor_search.ai_select_best_match(folder/'Title.mkv',candidates,'Target','tv',cfg)['id']==101
    assert processor_folder_ai._ai_select_tmdb_series(folder,candidates,cfg)['id']==101


def test_title_correction_cycle_stops_at_two(monkeypatch,tmp_path):
    from core import processor_search,search_enhancer,tmdb_client
    monkeypatch.setattr(processor_search,'_lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'lookup_local_alias',lambda *_:None)
    monkeypatch.setattr(search_enhancer,'search_tvmaze',lambda *a,**k:None)
    monkeypatch.setattr(tmdb_client,'search_tmdb_multi',lambda *a,**k:[{'id':55,'name':'Unrelated'}])
    calls=[]
    def correct(src,title,*a):
        calls.append(title)
        return {'A':'B','B':'A'}[title]
    monkeypatch.setattr(processor_search,'ai_verify_and_correct_title',correct)
    cfg={'tmdb_api':{'api_key':'synthetic'},'ai_parser':{'enabled':True}}
    result,_,_=processor_search.search_tmdb_with_fallback('tv','A',None,[],cfg,src=tmp_path/'A.mkv')
    assert result is None
    assert calls==['A','B']


def test_ai_budget_never_sends_more_requests_than_allowed(monkeypatch):
    from core import ai_client
    from core.ai_budget import recognition_budget_scope, AIBudgetExceeded
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'{}'}}]}
    class Session:
        def post(self,*a,**k):calls.append(1);return Response()
    monkeypatch.setattr(ai_client,'create_session',lambda:Session())
    cfg={'provider':'openai','api_key':'synthetic'}
    with recognition_budget_scope(limit=2):
        assert ai_client.call_ai_api('x',cfg)=='{}'
        assert ai_client.call_ai_api('x',cfg)=='{}'
        with pytest.raises(AIBudgetExceeded):ai_client.call_ai_api('x',cfg)
    assert len(calls)==2


def test_budget_exhaustion_records_review_without_processing(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,parser_manager,ai_client
    src=tmp_path/'source'/'Show.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['ai_parser'].update(enabled=True,provider='openai',api_key='synthetic')
    calls=[]
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'{}'}}]}
    class Session:
        def post(self,*a,**k):calls.append(1);return Response()
    monkeypatch.setattr(ai_client,'create_session',lambda:Session())
    def parse(*a,**kw):
        for _ in range(4):ai_client.call_ai_api('test',cfg['ai_parser'])
        pytest.fail('exhaustion was not enforced')
    monkeypatch.setattr(parser_manager,'parse_filename',parse)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('must stop after budget exhaustion'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert len(calls)==3
    assert '预算' in cache[str(src.resolve())]['failed_reason']
    assert src.read_bytes()==b'synthetic'
    assert not list((tmp_path/'tv').rglob('*.mkv'))


def test_ai_season_correction_prompt_does_not_default_special(tmp_path,config_file,monkeypatch):
    from core import config_manager,tmdb_client,ai_client
    from core.processor_tv import process_tv_branch
    src=tmp_path/'source'/'Show S02E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['ai_parser'].update(enabled=True,api_key='synthetic')
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**kw:[{'episode_number':2}])
    prompts=[]
    monkeypatch.setattr(ai_client,'call_ai_api',lambda prompt,*a,**kw:prompts.append(prompt) or '{"corrected_season":null,"corrected_episode":null,"reason":"无法确认"}')
    assert not process_tv_branch(src,cfg,{},None,'Show','2020',42,{'seasons':[{'season_number':2}]},
        {'season':2,'episode':1,'explicit_season':2,'_parser':'anitopy'},80)
    assert len(prompts)==1 and '默认归为第 0 季' not in prompts[0] and '电影，应返回 season=0' not in prompts[0]


@pytest.mark.parametrize('reply',[
    '{"corrected_season":2,"corrected_episode":true,"reason":"x"}',
    '{"corrected_season":2.0,"corrected_episode":1,"reason":"x"}',
    '年份2020 {"corrected_season":2,"corrected_episode":1,"reason":"x"}',
    '{"corrected_season":2,"corrected_episode":1,"corrected_episode":2,"reason":"x"}',
])
def test_invalid_ai_season_json_never_applied(tmp_path,config_file,monkeypatch,reply):
    from core import config_manager,tmdb_client,ai_client
    from core.processor_tv import process_tv_branch
    src=tmp_path/'source'/'Show S02E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['ai_parser'].update(enabled=True,api_key='synthetic')
    responses=iter([[{'episode_number':2}], [{'episode_number':1}]])
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**kw:next(responses))
    monkeypatch.setattr(ai_client,'call_ai_api',lambda *a,**kw:reply)
    cache={}
    assert not process_tv_branch(src,cfg,cache,None,'Show','2020',42,{'seasons':[{'season_number':2}]},
        {'season':2,'episode':1,'explicit_season':2,'_parser':'anitopy'},80)
    assert cache[str(src.resolve())].get('media_type')=='failed'
    assert not list((tmp_path/'tv').rglob('*.mkv'))


def test_ai_cancellation_propagates(tmp_path,monkeypatch):
    from core import processor_search, processor_folder_ai, ai_client
    from core.cancellation import ProcessingCancelled
    def cancelled(*a,**kw):raise ProcessingCancelled()
    monkeypatch.setattr(ai_client,'call_ai_api',cancelled)
    cfg={'ai_parser':{'enabled':True}}
    with pytest.raises(ProcessingCancelled):
        processor_search.ai_select_best_match(tmp_path/'A.mkv',CANDIDATES,'Target','tv',cfg)
    with pytest.raises(ProcessingCancelled):
        processor_folder_ai._ai_select_tmdb_series(tmp_path,CANDIDATES,cfg)


def test_exhaustion_inside_tv_transaction_leaves_no_media(tmp_path,config_file,monkeypatch):
    from core import config_manager,tmdb_client,ai_client
    from core.ai_budget import recognition_budget_scope, consume_recognition_call
    from core.processor_tv import process_tv_branch
    src=tmp_path/'source'/'Show S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],download_images=False)
    cfg['ai_parser'].update(enabled=True,provider='openai',api_key='synthetic')
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:[{'episode_number':2}])
    monkeypatch.setattr(ai_client,'create_session',lambda:pytest.fail('budget must block AI request'))
    cache={}
    with recognition_budget_scope(limit=1):
        consume_recognition_call()
        assert not process_tv_branch(src,cfg,cache,None,'Show','2020',42,{'seasons':[{'season_number':1}]},
                                     {'season':1,'episode':1,'explicit_season':1,'_parser':'anitopy'},80)
    assert '预算' in cache[str(src.resolve())]['failed_reason']
    assert src.read_bytes()==b'synthetic'
    assert not list((tmp_path/'tv').rglob('*.mkv'))
