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
