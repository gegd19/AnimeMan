"""T14: local fake videos/solid-color images; no external requests or user files."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading

from PIL import Image
import pytest

from core import cache_manager, config_manager, media_library_cache, subtitle_handler
from core.cancellation import cancellation_scope, ProcessingCancelled
from web import routes_config

AUTH=('test-user','test-pass')


@pytest.fixture
def library(tmp_path, config_file, monkeypatch):
    monkeypatch.setenv('CONFIG_PATH', str(config_file))
    cfg=config_manager.load_config(config_file)
    source=tmp_path/'source';source.mkdir()
    cfg['source_folders']=[str(source)]
    config_manager.save_config(cfg,config_file)
    records={};targets={};posters={}
    for kind in ('movie','tv'):
        src=source/(kind+'.mkv');src.write_bytes(b'fake '+kind.encode())
        folder=Path(cfg['movie_target_folder'])/'Movie' if kind=='movie' else Path(cfg['tv_target_folder'])/'Show'/'Season 00'
        folder.mkdir(parents=True)
        target=folder/('Movie.mkv' if kind=='movie' else 'Show.S00E01.mkv')
        target.write_bytes(src.read_bytes())
        root=folder if kind=='movie' else folder.parent
        poster=root/'poster.jpg'
        Image.new('RGB',(2,2),'red' if kind=='movie' else 'blue').save(poster)
        records[str(src)]={'media_type':kind,'tmdb_id':7,'title':kind.title(),'year':'2026',
            'target':str(target),'source_path':str(src),'season':0 if kind=='tv' else None,
            'episode':1 if kind=='tv' else None,'processed_time':1}
        targets[kind]=target;posters[kind]=poster
    cache_manager.save_cache(records)
    return cfg,records,targets,posters


def current_library(client):
    response=client.get('/api/media/library',auth=AUTH)
    assert response.status_code==200,response.get_data(as_text=True)
    return response.json


@pytest.mark.parametrize('warm',[False,True])
def test_same_numeric_id_movie_tv_have_distinct_posters(client,library,warm):
    cfg,records,targets,posters=library
    if warm:routes_config._scan_all_posters()
    for kind in ('movie','tv'):
        response=client.get(f'/media_poster/{kind}/7',auth=AUTH)
        assert response.status_code==200
        assert response.data==posters[kind].read_bytes()


def test_old_poster_url_refuses_ambiguous_type_even_if_one_image_missing(client,library):
    cfg,records,targets,posters=library
    posters['tv'].unlink()
    assert client.get('/media_poster/7',auth=AUTH).status_code==409


def test_old_url_compatible_only_with_one_current_identity(client,library):
    cfg,records,targets,posters=library
    cache_manager.save_cache({key:entry for key,entry in records.items() if entry['media_type']=='movie'})
    response=client.get('/media_poster/7',auth=AUTH)
    assert response.status_code==200 and response.data==posters['movie'].read_bytes()


def test_poster_refresh_has_type_qualified_keys(library,tmp_path):
    routes_config._scan_all_posters()
    data=json.loads((tmp_path/'poster_cache.json').read_text())
    assert data['_schema']==14
    assert set(data['items'])=={'movie:7','tv:7'}
    assert data['items']['movie:7']['media_type']=='movie'
    assert data['items']['tv:7']['tmdb_id']==7


def test_deleting_cache_record_does_not_leave_a_ghost_poster_or_list_item(client,library,tmp_path):
    cfg,records,targets,posters=library
    source,entry=next((key,value) for key,value in records.items() if value['media_type']=='movie')
    cache_manager.save_cache({source:entry})
    routes_config._scan_all_posters()
    assert client.get('/media_poster/7',auth=AUTH).status_code==200
    media_library_cache.update_media_library_cache()
    response=client.post('/api/processed_cache/delete',auth=AUTH,json={'src_path':source})
    assert response.status_code==200
    assert client.get('/media_poster/7',auth=AUTH).status_code==404
    assert current_library(client)['movies']==[]
    # Cache-only deletion deliberately leaves the user-owned physical artifacts.
    assert targets['movie'].exists() and posters['movie'].exists()
    assert Path(source).read_bytes()==b'fake movie'


def test_media_delete_updates_list_and_cannot_serve_leftover_custom_poster(client,library):
    cfg,records,targets,posters=library
    current_library(client);routes_config._scan_all_posters()
    source=next(key for key,value in records.items() if value['media_type']=='movie')
    response=client.post('/api/media/delete',auth=AUTH,json={'src_path':source,'delete_source':False})
    assert response.status_code==200
    assert current_library(client)['movies']==[]
    assert client.get('/media_poster/movie/7',auth=AUTH).status_code==404
    assert client.get('/media_poster/tv/7',auth=AUTH).data==posters['tv'].read_bytes()
    assert Path(source).exists() and posters['movie'].exists()


def test_correction_publication_changes_library_and_poster_identity(client,library,tmp_path):
    cfg,records,targets,posters=library
    current_library(client);routes_config._scan_all_posters()
    source=next(key for key,value in records.items() if value['media_type']=='movie')
    folder=Path(cfg['movie_target_folder'])/'Corrected';folder.mkdir()
    target=folder/'Corrected.mkv';target.write_bytes(b'new fake video')
    image=folder/'poster.jpg';Image.new('RGB',(2,2),'green').save(image)
    updated=dict(records[source],title='Corrected',tmdb_id=8,target=str(target))
    cache_manager.update_records({source:updated})
    data=current_library(client)
    assert [(row['tmdb_id'],row['title']) for row in data['movies']]==[(8,'Corrected')]
    assert client.get('/media_poster/movie/7',auth=AUTH).status_code==404
    assert client.get('/media_poster/movie/8',auth=AUTH).data==image.read_bytes()
    assert client.get('/media_poster/tv/7',auth=AUTH).data==posters['tv'].read_bytes()
    assert posters['movie'].exists()


def test_restart_or_external_primary_replacement_cannot_reuse_old_derived_frame(client,library,tmp_path):
    current_library(client);routes_config._scan_all_posters()
    # Bypass process-local notification, as a restart/external atomic writer can.
    from core.json_store import write_json
    write_json(tmp_path/cache_manager.CACHE_FILE,{})
    assert current_library(client)['tv_shows']==[]
    assert client.get('/media_poster/7',auth=AUTH).status_code==404


@pytest.mark.parametrize('name,legacy',[
    ('media_library_cache.json',{'movies':[{'cache_key':'ghost'}],'tv_shows':[]}),
    ('poster_cache.json',{'7':{'poster_path':'untrusted-path'}}),
    ('media_library_cache.json',{}),
    ('poster_cache.json',{}),
])
def test_legacy_derived_cache_is_backed_up_before_rebuild(client,library,tmp_path,name,legacy):
    path=tmp_path/name;path.write_text(json.dumps(legacy));before=path.read_bytes()
    if name.startswith('media_library'):current_library(client)
    else:assert client.get('/media_poster/movie/7',auth=AUTH).status_code==200
    backups=list(tmp_path.glob(name+'.t14-*.bak'))
    assert len(backups)==1 and backups[0].read_bytes()==before
    assert json.loads(path.read_text())['_schema']==14


def test_old_wrong_poster_mapping_is_never_served(client,library,tmp_path):
    cfg,records,targets,posters=library
    (tmp_path/'poster_cache.json').write_text(json.dumps({'7':{'poster_path':str(posters['tv'])}}))
    response=client.get('/media_poster/movie/7',auth=AUTH)
    assert response.status_code==200 and response.data==posters['movie'].read_bytes()


@pytest.mark.parametrize('name',['poster_cache.json','media_library_cache.json'])
def test_corrupt_derived_cache_is_not_silently_overwritten(client,library,tmp_path,name):
    path=tmp_path/name;path.write_text('{broken')
    route='/media_poster/movie/7' if name.startswith('poster') else '/api/media/library'
    response=client.get(route,auth=AUTH)
    assert response.status_code==503
    assert path.read_text()=='{broken'
    assert list(tmp_path.glob(name+'.corrupt-*.bak'))


def test_missing_video_is_explicit_but_is_not_a_logical_delete(client,library):
    cfg,records,targets,posters=library
    current_library(client)
    targets['movie'].unlink()
    data=current_library(client)
    assert len(data['movies'])==1 and data['movies'][0]['target_exists'] is False
    assert client.get('/media_poster/movie/7',auth=AUTH).status_code==404
    assert len(cache_manager.load_cache())==2


def test_source_image_symlink_escape_is_not_served(client,library,tmp_path):
    cfg,records,targets,posters=library
    source=Path(cfg['source_folders'][0])/'private.jpg'
    Image.new('RGB',(2,2),'yellow').save(source)
    original=source.read_bytes()
    posters['movie'].unlink();posters['movie'].symlink_to(source)
    assert client.get('/media_poster/movie/7',auth=AUTH).status_code==404
    assert source.read_bytes()==original


def test_image_repair_changes_poster_without_a_primary_cache_write(client,library):
    cfg,records,targets,posters=library
    routes_config._scan_all_posters()
    Image.new('RGB',(3,3),'green').save(posters['movie'])
    response=client.get('/media_poster/movie/7',auth=AUTH)
    assert response.status_code==200 and response.data==posters['movie'].read_bytes()


def test_subtitles_and_failed_records_do_not_create_media_identities(client,library):
    cfg,records,targets,posters=library
    record=next(value for value in records.values() if value['media_type']=='movie')
    cache_manager.save_cache({'subtitle':dict(record,media_type='subtitle'),'failed':dict(record,media_type='failed')})
    assert current_library(client)['movies']==[]
    assert client.get('/media_poster/7',auth=AUTH).status_code==404


def test_same_id_string_and_integer_share_one_tv_identity(client,library):
    cfg,records,targets,posters=library
    key,entry=next((key,value) for key,value in records.items() if value['media_type']=='tv')
    other=targets['tv'].with_name('Show.S00E02.mkv');other.write_bytes(b'fake episode')
    cache_manager.update_records({'other-source':dict(entry,tmdb_id='7',episode=2,target=str(other))})
    data=current_library(client)
    assert len(data['tv_shows'])==1
    assert [ep['episode'] for ep in data['tv_shows'][0]['seasons']['0']['episodes']]==[1,2]


@pytest.mark.parametrize('name',['poster_cache.json','media_library_cache.json'])
def test_refresh_write_failure_preserves_previous_complete_snapshot(library,tmp_path,monkeypatch,name):
    cfg,records,targets,posters=library
    routes_config._scan_all_posters();media_library_cache.update_media_library_cache()
    path=tmp_path/name;before=path.read_bytes();memory=deepcopy(routes_config._poster_cache)
    cache_manager.save_cache({})
    from core import json_store
    original=json_store.os.replace
    def fail(src,dst,*args,**kwargs):
        if Path(dst)==path:raise OSError('derived cache disk full')
        return original(src,dst,*args,**kwargs)
    monkeypatch.setattr(json_store.os,'replace',fail)
    with pytest.raises(OSError):
        if name.startswith('poster'):routes_config._scan_all_posters()
        else:media_library_cache.update_media_library_cache()
    assert path.read_bytes()==before
    assert routes_config._poster_cache==memory
    assert not list(tmp_path.glob(name+'*.tmp'))


def test_cancelled_poster_refresh_does_not_replace_snapshot(library,tmp_path):
    routes_config._scan_all_posters()
    path=tmp_path/'poster_cache.json';before=path.read_bytes();memory=deepcopy(routes_config._poster_cache)
    event=threading.Event();event.set()
    with cancellation_scope(event),pytest.raises(ProcessingCancelled):routes_config._scan_all_posters()
    assert path.read_bytes()==before and routes_config._poster_cache==memory


def test_preview_reads_and_refreshes_create_no_derived_files(client,library,tmp_path,config_file):
    cfg,records,targets,posters=library
    cfg['dry_run']=True;config_manager.save_config(cfg,config_file)
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and 'logs' not in p.parts}
    current_library(client)
    assert client.get('/media_poster/movie/7',auth=AUTH).status_code==200
    routes_config._scan_all_posters()
    media_library_cache.update_media_library_cache()
    after={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and 'logs' not in p.parts}
    assert after==before


def test_concurrent_snapshots_are_complete_and_match_one_source_generation(library,tmp_path):
    cfg,records,targets,posters=library
    media_library_cache.update_media_library_cache()
    gate=threading.Barrier(3)
    def writer():
        gate.wait(timeout=5)
        for i in range(24):cache_manager.save_cache(records if i%2 else {})
    def reader():
        gate.wait(timeout=5)
        for _ in range(24):
            data=subtitle_handler.get_media_library_from_cache(cfg)
            assert (len(data['movies']),len(data['tv_shows'])) in ((0,0),(1,1))
            saved=json.loads((tmp_path/'media_library_cache.json').read_text())
            assert (len(saved['movies']),len(saved['tv_shows'])) in ((0,0),(1,1))
            assert saved['_schema']==14 and saved['source_revision']
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(writer),pool.submit(reader),pool.submit(reader)]
        for future in futures:future.result(timeout=15)


def test_invalidation_after_primary_commit_performs_no_filesystem_reads(tmp_path,monkeypatch):
    from core import derived_cache
    def forbidden(*args,**kwargs):pytest.fail('post-commit invalidation must not perform filesystem I/O')
    with monkeypatch.context() as patch:
        patch.setattr(Path,'resolve',forbidden)
        patch.setattr(Path,'stat',forbidden)
        derived_cache.invalidate(tmp_path/'committed-primary.json')


def test_failed_primary_write_keeps_projection_current(client,library,tmp_path,monkeypatch):
    current_library(client);routes_config._scan_all_posters()
    assert client.get('/api/media/poster_cache',auth=AUTH).json['stale'] is False
    from core import json_store
    original=json_store.os.replace
    def fail(src,dst,*args,**kwargs):
        if Path(dst)==tmp_path/cache_manager.CACHE_FILE:raise OSError('primary commit failed')
        return original(src,dst,*args,**kwargs)
    monkeypatch.setattr(json_store.os,'replace',fail)
    with pytest.raises(OSError):cache_manager.save_cache({})
    assert client.get('/api/media/poster_cache',auth=AUTH).json['stale'] is False
    assert len(current_library(client)['movies'])==1


def test_stale_status_does_not_advertise_old_items_or_publish(client,library,tmp_path):
    routes_config._scan_all_posters()
    path=tmp_path/'poster_cache.json';before=path.read_bytes()
    cache_manager.save_cache({})
    status=client.get('/api/media/poster_cache',auth=AUTH).json
    assert status['stale'] is True and status['cached_count']==0
    assert path.read_bytes()==before


def test_cache_namespace_switch_cannot_reuse_another_library(client,library,tmp_path,monkeypatch):
    current_library(client);routes_config._scan_all_posters()
    other=tmp_path/'other-cache';other.mkdir()
    for name in (cache_manager.CACHE_FILE,'poster_cache.json','media_library_cache.json'):
        (other/name).write_text('{}')
    monkeypatch.setenv('CACHE_PATH',str(other))
    assert current_library(client)['movies']==[]
    assert client.get('/media_poster/7',auth=AUTH).status_code==404


def test_even_a_well_formed_poster_frame_cannot_redirect_to_other_type(client,library,tmp_path):
    from core import derived_cache
    cfg,records,targets,posters=library
    routes_config._scan_all_posters()
    path=tmp_path/'poster_cache.json';frame=json.loads(path.read_text())
    frame['items']['movie:7']['poster_path']=str(posters['tv'])
    frame['checksum']=derived_cache._digest({key:value for key,value in frame.items() if key!='checksum'})
    path.write_text(json.dumps(frame))
    response=client.get('/media_poster/movie/7',auth=AUTH)
    assert response.status_code==404


@pytest.mark.parametrize('bad_kind',['unsafe_target','unknown_episode'])
def test_invalid_primary_identity_is_reported_without_rewriting_primary(client,library,tmp_path,bad_kind):
    cfg,records,targets,posters=library
    if bad_kind=='unsafe_target':
        key,record=next((key,value) for key,value in records.items() if value['media_type']=='movie')
        record=dict(record,target=key)
    else:
        key,record=next((key,value) for key,value in records.items() if value['media_type']=='tv')
        record=dict(record);record.pop('season');record.pop('episode')
    cache_manager.save_cache({key:record})
    before=(tmp_path/cache_manager.CACHE_FILE).read_bytes()
    data=current_library(client)
    assert data['movies']==[] and data['tv_shows']==[] and data['issues']
    assert client.get('/media_poster/7',auth=AUTH).status_code==404
    assert (tmp_path/cache_manager.CACHE_FILE).read_bytes()==before


def test_unidentified_shows_are_not_merged_into_one_none_id(client,library):
    cfg,records,targets,posters=library
    key,record=next((key,value) for key,value in records.items() if value['media_type']=='tv')
    second=Path(cfg['tv_target_folder'])/'Other'/'Season 00'/'Other.S00E01.mkv'
    second.parent.mkdir(parents=True);second.write_bytes(b'fake other episode')
    cache_manager.save_cache({key:dict(record,tmdb_id=None),'other':dict(record,tmdb_id=None,target=str(second))})
    data=current_library(client)
    assert len(data['tv_shows'])==2 and all(show['tmdb_id'] is None for show in data['tv_shows'])


@pytest.mark.parametrize('filename',['poster.JPG','poster.png','fanart.PNG'])
def test_supported_image_extensions_and_fanart_fallback_are_preserved(client,library,filename):
    cfg,records,targets,posters=library
    folder=posters['movie'].parent
    posters['movie'].unlink()
    image=folder/filename
    Image.new('RGB',(2,2),'green').save(image,format='PNG' if filename.lower().endswith('.png') else 'JPEG')
    response=client.get('/media_poster/movie/7',auth=AUTH)
    assert response.status_code==200 and response.data==image.read_bytes()


def test_warm_poster_request_does_not_rescan_unrelated_media_folders(client,library,monkeypatch):
    cfg,records,targets,posters=library
    routes_config._scan_all_posters()
    original=Path.glob
    unrelated=[]
    def observe(folder,pattern,*args,**kwargs):
        if folder==posters['tv'].parent:unrelated.append(pattern)
        return original(folder,pattern,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'glob',observe)
        response=client.get('/media_poster/movie/7',auth=AUTH)
    assert response.status_code==200 and not unrelated
