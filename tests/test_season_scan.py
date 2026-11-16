"""T09: complete numeric tokens, unknown episodes and a shared scan policy."""
from pathlib import Path
import pytest

@pytest.mark.parametrize('filename,season,episode',[
    ('Show S00E01.mkv',0,1),('Show S01E123.mkv',1,123),('Show [123].mkv',1,123),
    ('Spirit S01E02.mkv',1,2),('Show S02E03 1080p.mkv',2,3),
    ('Show 第十一季 第123集.mkv',11,123),('Show S01E12345.mkv',1,None),
    ('Show 1080p 2024.mkv',None,None),('Show.mkv',None,None),
    ('Show OVA 02.mkv',0,2),('Show SP S00E03.mkv',0,3),
])
def test_regex_keeps_reliable_complete_season_episode(filename,season,episode):
    from core.parser_regex import parse_with_regex
    result=parse_with_regex(filename)
    assert (result['season'],result['episode'])==(season,episode)
    if episode is None: assert result['media_type']=='unknown'
    else: assert result['media_type']=='tv'


def test_unknown_tv_episode_never_gets_defaulted_in_core(config_file,tmp_path,monkeypatch):
    from core import processor_core,config_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'temporary')
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a:{'media_type':'tv','title':'Show','season':1,'episode':None})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('searched a fabricated episode'))
    assert not processor_core.process_video(src,config_manager.load_config(config_file),{},None)


@pytest.mark.parametrize('mode',['default','mapping','include','disabled','exclude','ignore'])
def test_scan_and_offline_agree_on_special_policy(mode,tmp_path,config_file):
    from core import config_manager,processor_runner,offline_ai_preparser
    root=tmp_path/'source';special=root/'OVA'/'Show OVA 01.mkv'
    special.parent.mkdir(parents=True);special.write_bytes(b'temporary')
    regular=root/'Spirit S01E02.mkv';regular.write_bytes(b'temporary')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(root)],ignore_patterns=[])
    mapping={'keyword':'Show OVA','tmdb_id':1,'media_type':'tv','season':0,'episode':1,'enabled':mode!='disabled'}
    config['special_mappings']=[mapping] if mode in {'mapping','disabled','exclude','ignore'} else []
    if mode=='include':config['scan_policy']={'include_specials':True}
    if mode=='exclude':config['scan_policy']={'exclude_patterns':['OVA']}
    if mode=='ignore':config['ignore_patterns']=['OVA']
    expected={regular,special} if mode in {'mapping','include'} else {regular}
    direct=set(processor_runner._scan_video_files(root,config))
    offline={Path(f['path']) for values in offline_ai_preparser.scan_source_folders(config).values() for f in values}
    assert direct==offline==expected


def test_anitopy_does_not_turn_zero_season_or_missing_episode_into_one(monkeypatch):
    from core import parser_anitopy
    monkeypatch.setattr(parser_anitopy.anitopy,'parse',lambda *a:{'anime_title':'Show','anime_season':'0','episode_number':'123'})
    result=parser_anitopy.parse_with_anitopy('Show S00E123.mkv')
    assert (result['season'],result['episode'])==(0,123)
    monkeypatch.setattr(parser_anitopy.anitopy,'parse',lambda *a:{'anime_title':'Show'})
    result=parser_anitopy.parse_with_anitopy('Show.mkv')
    assert result['episode'] is None
