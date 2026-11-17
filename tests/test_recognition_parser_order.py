"""R08: reliable local evidence precedes optional AI recognition."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest


def configured(config_file, root):
    from core import config_manager
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(root)]
    cfg['ai_parser'].update(enabled=True,api_key='synthetic',batch_folder_enabled=True)
    return cfg


def test_two_clear_episodes_use_no_ai(tmp_path,config_file,monkeypatch):
    from core import parser_manager,ai_client
    folder=tmp_path/'Show';folder.mkdir()
    files=[folder/'Show S01E01.mkv',folder/'Show S01E02.mkv']
    for src in files:src.write_bytes(b'synthetic')
    cfg=configured(config_file,folder)
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',lambda *a,**kw:pytest.fail('clear files should not use AI'))
    monkeypatch.setattr(ai_client,'parse_filename_with_ai',lambda *a,**kw:pytest.fail('clear files should not use AI'))
    results=[parser_manager.parse_filename(src,cfg) for src in files]
    assert [(r['season'],r['episode']) for r in results]==[(1,1),(1,2)]


def test_real_first_episode_does_not_trigger_second_batch(tmp_path,config_file,monkeypatch):
    from core import processor_folder_ai
    src=tmp_path/'Show [01].mkv';src.write_bytes(b'synthetic')
    cfg=configured(config_file,tmp_path)
    monkeypatch.setattr(processor_folder_ai,'_get_tmdb_info_for_folder',lambda *a,**k:pytest.fail('clear first episode should not start AI'))
    info={'_parser':'anitopy','title':'Show','media_type':'tv','season':1,'episode':1}
    assert processor_folder_ai.try_folder_ai_batch(src,cfg,info,None) is None


def test_manual_mapping_skips_ai_parser(tmp_path,config_file,monkeypatch):
    from core import processor_helpers,parser_manager
    src=tmp_path/'Show OVA.mkv';src.write_bytes(b'synthetic')
    cfg=configured(config_file,tmp_path)
    def parse(_src,effective,*a):
        assert effective['ai_parser']['enabled'] is False
        return {'title':'Show','media_type':'tv','season':1,'episode':1}
    monkeypatch.setattr(parser_manager,'parse_filename',parse)
    info=processor_helpers.parse_filename_info(src,cfg,None,force_tmdb_id=42,force_media_type='tv',force_season=0,force_episode=2)
    assert (info['tmdb_id'],info['title'],info['season'],info['episode'])==(42,'Show',0,2)
    assert cfg['ai_parser']['enabled'] is True


def test_invalid_ai_falls_back_to_valid_partial_local(tmp_path,config_file,monkeypatch):
    from core import parser_manager,ai_client
    folder=tmp_path/'Show';folder.mkdir();src=folder/'ambiguous.mkv';src.write_bytes(b'synthetic')
    cfg=configured(config_file,folder);cfg['ai_parser']['batch_folder_enabled']=False
    local={'_anitopy_success':False,'media_type':'tv','title':'Show','season':1,'episode':2}
    monkeypatch.setattr(parser_manager,'parse_with_anitopy',lambda *a,**k:local)
    monkeypatch.setattr(ai_client,'parse_filename_with_ai',lambda *a,**k:{'media_type':'unknown'})
    result=parser_manager.parse_filename(src,cfg)
    assert (result['title'],result['season'],result['episode'])==('Show',1,2)


def test_ambiguous_folder_concurrent_ai_is_single_flight(tmp_path,config_file,monkeypatch):
    from core import parser_manager,ai_client
    folder=tmp_path/'Show';folder.mkdir();files=[folder/'ambiguous-a.mkv',folder/'ambiguous-b.mkv']
    for src in files:src.write_bytes(b'synthetic')
    cfg=configured(config_file,folder)
    monkeypatch.setattr(parser_manager,'parse_with_anitopy',lambda *a,**k:{'media_type':'unknown','_anitopy_success':False})
    calls=[];entered=threading.Event();release=threading.Event()
    def parse(folder_path,paths,config,log_func=None,tmdb_structure=''):
        calls.append(1);entered.set();assert release.wait(5)
        return {'files':{f.name:{'media_type':'tv','title':'Show','season':1,'episode':i+1} for i,f in enumerate(paths)}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(parser_manager.parse_filename,files[0],cfg)
        assert entered.wait(5)
        second=pool.submit(parser_manager.parse_filename,files[1],cfg)
        time.sleep(0.1);release.set()
        results=[first.result(timeout=5),second.result(timeout=5)]
    assert len(calls)==1 and [r['episode'] for r in results]==[1,2]


def test_ai_disabled_valid_local_movie_works_when_regex_fallback_off(tmp_path,config_file,monkeypatch):
    from core import parser_manager
    src=tmp_path/'Movie.mkv';src.write_bytes(b'synthetic')
    cfg=configured(config_file,tmp_path)
    cfg['ai_parser']['enabled']=False
    cfg['anime_parser']['fallback_to_regex']=False
    monkeypatch.setattr(parser_manager,'parse_with_anitopy',lambda *a,**k:{'_anitopy_success':True,'media_type':'movie','title':'Movie'})
    result=parser_manager.parse_filename(src,cfg)
    assert result['media_type']=='movie' and result['title']=='Movie'


def test_forced_mapping_runs_real_local_parser_without_ai(tmp_path,config_file,monkeypatch):
    from core import processor_helpers,ai_client
    src=tmp_path/'Show OVA 02.mkv';src.write_bytes(b'synthetic')
    cfg=configured(config_file,tmp_path)
    monkeypatch.setattr(ai_client,'parse_filename_with_ai',lambda *a,**k:pytest.fail('manual mapping must not invoke AI'))
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',lambda *a,**k:pytest.fail('manual mapping must not invoke AI'))
    info=processor_helpers.parse_filename_info(src,cfg,None,42,'tv',0,2)
    assert (info['tmdb_id'],info['media_type'],info['season'],info['episode'])==(42,'tv',0,2)
