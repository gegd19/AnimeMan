"""Unnumbered Roman titles need an explicit season policy."""
import pytest


@pytest.mark.parametrize('filename,roman',[
    ('Sword Art Online II [05].mp4','II'),
    ('Toaru Majutsu no Index III [21].mkv','III'),
    ('Project X [01].mkv','X'),
])
def test_bracket_episode_keeps_roman_in_title_and_source_name(filename,roman):
    from core.parser_anitopy import parse_with_anitopy
    result=parse_with_anitopy(filename)
    assert result['_cleaned_filename']==filename
    assert result['title'].split()[-1]==roman



@pytest.mark.parametrize('ai_enabled',[False,True])
def test_ambiguous_roman_season_needs_review_before_ai_or_tmdb(tmp_path,config_file,monkeypatch,ai_enabled):
    from core import config_manager,parser_manager,processor_core,ai_client
    root=tmp_path/'source';root.mkdir()
    src=root/'Project X [01].mkv';src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)])
    cfg['ai_parser'].update(enabled=ai_enabled,api_key='synthetic')
    monkeypatch.setattr(ai_client,'call_ai_api_with_messages',lambda *a,**k:pytest.fail('ambiguity cannot use AI'))
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('ambiguity cannot search'))
    info=parser_manager.parse_filename(src,cfg)
    assert info['reason_code']=='ambiguous_roman_season' and info['season'] is None
    assert info['episode']==1 and info['title']=='Project X'
    cache={};assert not processor_core.process_video(src,cfg,cache)
    assert '人工确认' in cache[str(src.resolve())]['failed_reason']
    assert src.read_bytes()==b'synthetic'


def test_explicit_directory_season_removes_roman_ambiguity(tmp_path,config_file):
    from core import config_manager,parser_manager
    root=tmp_path/'source';folder=root/'Project X'/'Season 02';folder.mkdir(parents=True)
    src=folder/'Project X [01].mkv';src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(root)]
    info=parser_manager.parse_filename(src,cfg)
    assert info.get('reason_code') is None
    assert info['title']=='Project X' and (info['season'],info['episode'])==(2,1)


def test_confirmed_single_file_rule_supplies_roman_season(tmp_path,config_file,monkeypatch):
    from core import config_manager,user_recognition_rules as rules,processor_core,tmdb_client,video_info
    root=tmp_path/'source';root.mkdir();src=root/'Project X [01].mkv';src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],user_rules={'enabled':True})
    rules.create_rule(cfg,str(src),'file',42,'tv',season=2,episode=1)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':42,'name':'Project X'})
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('confirmed ID must not search'))
    observed=[];monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:(observed.append(a[-2]) or True))
    assert processor_core.process_video(src,cfg,{})
    assert observed[0]['title']=='Project X' and (observed[0]['season'],observed[0]['episode'])==(2,1)
    assert src.read_bytes()==b'synthetic'


def test_explicit_numbering_map_supplies_roman_season(tmp_path,config_file,monkeypatch):
    from core import config_manager,numbering_maps as maps,processor_core,tmdb_client,video_info
    root=tmp_path/'source';root.mkdir();src=root/'Project X [01].mkv';src.write_bytes(b'synthetic')
    (root/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">42</uniqueid></tvshow>')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],identity_hints={'enabled':True},numbering_maps={'enabled':True})
    maps.add_exact(cfg,str(root),42,'01',2,1)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':42,'name':'Project X'})
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('confirmed identity must not search'))
    observed=[];monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:(observed.append(a[-2]) or True))
    assert processor_core.process_video(src,cfg,{})
    assert (observed[0]['season'],observed[0]['episode'])==(2,1)
    assert src.read_bytes()==b'synthetic'


@pytest.mark.parametrize('filename,roman',[
    ('Legend XIV [01].mkv','XIV'),
    ('Legend XXIV [02].mkv','XXIV'),
    ('Legend XXX [03].mkv','XXX'),
])
def test_long_roman_tokens_remain_title_and_unknown_season(filename,roman):
    from core.parser_anitopy import parse_with_anitopy
    result=parse_with_anitopy(filename)
    assert result['title'].endswith(roman)
    assert result['season'] is None and result['reason_code']=='ambiguous_roman_season'
