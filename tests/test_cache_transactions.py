"""T07 cache interruption, corruption and deterministic lost-update regressions."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
import os
from pathlib import Path
import threading

import pytest

# Public cache accessors; every file uses the test's temporary CACHE_PATH.
STORES = [
    ('core.cache_manager','save_cache','load_cache','auto_processed_cache.json'),
    ('core.cache_manager','save_ai_parse_cache','load_ai_parse_cache','ai_parse_cache.json'),
    ('core.folder_ai_cache','save_folder_cache','load_folder_cache','folder_ai_parse_cache.json'),
    ('core.folder_parser','save_folder_cache','load_folder_cache','folder_ai_cache.json'),
    ('core.offline_ai_preparser','save_raw_cache','load_raw_cache','raw_scan_cache.json'),
    ('core.offline_ai_preparser','save_ai_preparse_cache','load_ai_preparse_cache','ai_preparse_cache.json'),
    ('core.media_library_cache','save_media_library_cache','load_media_library_cache','media_library_cache.json'),
]

@pytest.mark.parametrize('module,save,load,name', STORES)
def test_failed_serialization_preserves_old_document(module,save,load,name,tmp_path,monkeypatch):
    mod=importlib.import_module(module)
    getattr(mod,save)({'old':{'value':1}})
    original=(tmp_path/name).read_bytes()
    def interrupted(value,stream,*a,**k):
        stream.write('{"partial":')
        raise OSError('injected write failure')
    monkeypatch.setattr(json,'dump',interrupted)
    with pytest.raises(OSError,match='injected'):
        getattr(mod,save)({'new':2})
    assert (tmp_path/name).read_bytes()==original
    assert not list(tmp_path.glob('*.tmp'))

@pytest.mark.parametrize('module,save,load,name', STORES)
@pytest.mark.parametrize('broken',[b'{"truncated":',b'[]'])
def test_corrupt_cache_is_backed_up_and_never_overwritten(module,save,load,name,broken,tmp_path):
    mod=importlib.import_module(module)
    path=tmp_path/name
    path.write_bytes(broken)
    with pytest.raises(Exception,match='损坏|corrupt'):
        getattr(mod,load)()
    backups=list(tmp_path.glob(name+'.corrupt-*.bak'))
    assert backups and all(p.read_bytes()==broken for p in backups)
    with pytest.raises(Exception,match='损坏|corrupt'):
        getattr(mod,save)({'replacement':{}})
    assert path.read_bytes()==broken


def test_replace_failure_keeps_old_file_and_uses_unique_temp(tmp_path,monkeypatch):
    from core import cache_manager
    cache_manager.save_cache({'old':1})
    seen=[]
    def fail_replace(src,dst):
        seen.append(Path(src).name)
        raise OSError('replace failure')
    monkeypatch.setattr(os,'replace',fail_replace)
    for i in range(2):
        with pytest.raises(OSError,match='replace failure'):
            cache_manager.save_cache({'new':i})
    assert cache_manager.load_cache()=={'old':1}
    assert len(set(seen))==2
    assert not list(tmp_path.glob('*.tmp'))


def test_folder_parse_record_updates_do_not_lose_other_folder(tmp_path,monkeypatch):
    from core import folder_ai_cache
    gate=threading.Barrier(2)
    def fingerprint(*a):
        gate.wait(timeout=5)
        return 'dummy-fingerprint'
    monkeypatch.setattr(folder_ai_cache.parse_identity,'folder_snapshot',lambda folder,cfg:(fingerprint(),[Path(folder)/'x.mkv']))
    def save(i):
        folder_ai_cache.save_folder_parse_result(tmp_path/str(i), {'folder_title':str(i),'files':{'x.mkv':{'media_type':'movie','title':str(i)}}}, {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save,range(2)))
    assert set(folder_ai_cache.load_folder_cache())=={str(tmp_path/str(i)) for i in range(2)}


def test_offline_workers_and_full_parse_keep_all_records(tmp_path,monkeypatch):
    from core import offline_ai_preparser as offline, ai_client
    folders=[tmp_path/str(i) for i in range(2)]
    for folder in folders:
        folder.mkdir();(folder/'x.mkv').write_bytes(b'test')
    offline.save_raw_cache({str(f):[{'path':str(f/'x.mkv'),'name':'x.mkv'}] for f in folders})
    gate=threading.Barrier(2)
    def parse(folder,*a,**k):
        gate.wait(timeout=5)
        return {'folder_title':folder.name,'files':{'x.mkv':{'media_type':'movie','title':folder.name}}}
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',parse)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda f:offline.parse_folder_on_demand(f,{}),folders))
    assert set(offline.load_ai_preparse_cache())==set(map(str,folders))
    # Full preparse must return freshly committed records rather than its old snapshot.
    offline.save_ai_preparse_cache({})
    from core import folder_ai_cache
    folder_ai_cache.save_folder_cache({})
    monkeypatch.setattr(ai_client,'parse_folder_with_ai',lambda f,*a,**k:{'folder_title':f.name,'files':{'x.mkv':{'media_type':'movie','title':f.name}}})
    result=offline.run_ai_preparse({})
    assert set(result)==set(map(str,folders))
    assert offline.load_ai_preparse_cache()==result


def test_runner_merges_only_changed_records(config_file,tmp_path,monkeypatch):
    from core import processor_runner as runner, cache_manager, config_manager
    src=tmp_path/'input.mkv';src.write_bytes(b'test')
    config=config_manager.load_config(config_file)
    config.update(source_folders=[str(tmp_path)],incremental=False)
    cache_manager.save_cache({'history':{'media_type':'movie','title':'old'}})
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    def process(src,cfg,result,log):
        cache_manager.save_cache({'history':{'media_type':'movie','title':'updated elsewhere'},
                                  'side-effect':{'media_type':'movie'}})
        result[str(src)]={'media_type':'movie','target':'temporary-target'}
        return True
    monkeypatch.setattr(runner,'process_video',process)
    runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    saved=cache_manager.load_cache()
    assert saved['history']['title']=='updated elsewhere'
    assert 'side-effect' in saved and str(src) in saved


def test_corruption_in_preview_reports_without_creating_backup(tmp_path):
    from core import cache_manager
    from core.execution_mode import preview_mode
    path=tmp_path/cache_manager.CACHE_FILE;path.write_text('{bad')
    before={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with preview_mode(True),pytest.raises(Exception,match='损坏|corrupt'):
        cache_manager.load_cache()
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}==before


@pytest.mark.parametrize('module,save,load,name',[
    ('core.tmdb_cache','_save_cache','_load_cache','tmdb_search_cache.json'),
    ('web.routes_config','_save_poster_cache','_load_poster_cache','poster_cache.json'),
])
def test_auxiliary_cache_corruption_cannot_be_hidden_by_memory(module,save,load,name,tmp_path):
    mod=importlib.import_module(module)
    path=tmp_path/name;path.write_text('{broken')
    from core.json_store import CacheCorruptionError
    with pytest.raises(CacheCorruptionError):
        getattr(mod,load)()
    assert list(tmp_path.glob(name+'.corrupt-*.bak'))
    with pytest.raises(CacheCorruptionError):
        getattr(mod,save)(**({'cache_data':{}} if 'tmdb_cache' in module else {}))
    assert path.read_text()=='{broken'


def test_folder_meta_concurrent_records_are_merged(tmp_path,monkeypatch):
    from core import folder_parser
    gate=threading.Barrier(2)
    def parse(folder,*a,**k):
        gate.wait(timeout=5)
        return {'media_type':'movie','title':folder.name}
    monkeypatch.setattr(folder_parser,'parse_folder_with_ai',parse)
    folders=[tmp_path/str(i) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda f:folder_parser.get_folder_meta(f,{'ai_parser':{'enabled':True}}),folders))
    assert set(folder_parser.load_folder_cache())==set(map(str,folders))


def test_record_transactions_serialize_read_modify_write(tmp_path):
    from core import cache_manager
    gate=threading.Barrier(2)
    def update(i):
        gate.wait(timeout=5)
        cache_manager.update_records({str(i):{'media_type':'movie'}})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update,range(2)))
    assert set(cache_manager.load_cache())=={'0','1'}


def test_cache_commit_error_rolls_back_new_publication(config_file,tmp_path,monkeypatch):
    from core import cache_manager,config_manager,processor_runner as runner,tmdb_client
    from core.processor_manual import process_video_with_manual_correction
    from core.json_store import CacheCorruptionError
    src=tmp_path/'source'/'input.mkv';src.parent.mkdir();src.write_bytes(b'original')
    config=config_manager.load_config(config_file)
    config.update(source_folders=[str(src.parent)],incremental=False,download_images=False,subtitle={'enabled':False})
    old=Path(config['movie_target_folder'])/'Old'/'Old.mkv';old.parent.mkdir(parents=True);old.hardlink_to(src)
    cache_manager.save_cache({str(src):{'target':str(old),'media_type':'movie'}})
    original=Path(cache_manager.CACHE_FILE).read_bytes()
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:{'title':'New'})
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    monkeypatch.setattr(runner,'process_video',lambda src,cfg,result,log:
                        process_video_with_manual_correction(src,cfg,result,1,'movie',1,1,log))
    def broken(*a):
        raise CacheCorruptionError('injected corrupt commit')
    monkeypatch.setattr(cache_manager,'update_records',broken)
    with pytest.raises(CacheCorruptionError):
        runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert not (Path(config['movie_target_folder'])/'New'/'New.mkv').exists()
    assert old.read_bytes()==src.read_bytes()==b'original'
    assert Path(cache_manager.CACHE_FILE).read_bytes()==original


def test_web_clear_reports_corruption_and_keeps_original(client,tmp_path):
    from core import cache_manager
    path=tmp_path/cache_manager.CACHE_FILE;path.write_bytes(b'{broken')
    response=client.post('/api/processed_cache/clear',json={},auth=('test-user','test-pass'))
    assert response.status_code==503 and response.json['code']=='cache_corrupt'
    assert path.read_bytes()==b'{broken'
    assert list(tmp_path.glob(path.name+'.corrupt-*.bak'))


def test_legacy_backup_failure_stops_before_media_work(config_file,tmp_path,monkeypatch):
    from core import cache_manager,config_manager,processor_runner as runner
    src=tmp_path/'input.mkv';src.write_bytes(b'original')
    config=config_manager.load_config(config_file);config.update(source_folders=[str(tmp_path)])
    cache_manager.save_cache({str(src):{'media_type':'failed'}})
    original=Path(cache_manager.CACHE_FILE).read_bytes()
    monkeypatch.setattr(runner,'_scan_video_files',lambda *a:[src])
    monkeypatch.setattr(runner,'process_video',lambda *a:pytest.fail('started before backup'))
    def fail(*a):
        raise PermissionError('backup denied')
    monkeypatch.setattr(cache_manager,'backup_json',fail)
    with pytest.raises(PermissionError,match='backup denied'):
        runner.run_processor_with_callback(str(config_file),lambda *a:None,effective_config=config)
    assert Path(cache_manager.CACHE_FILE).read_bytes()==original and src.read_bytes()==b'original'
