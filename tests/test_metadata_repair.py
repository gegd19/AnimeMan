"""T08: XML round trips, exact sidecar paths, atomic IO and complete repair."""
from concurrent.futures import ThreadPoolExecutor
import binascii
import os
from pathlib import Path
import struct
import threading
from xml.etree import ElementTree as ET
import zlib

import pytest

TEXT = 'A & B <特别篇> "引号"'


def png_bytes():
    def chunk(kind, body):
        return struct.pack('!I',len(body))+kind+body+struct.pack('!I',binascii.crc32(kind+body)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\xff\x00\x00'))+chunk(b'IEND',b'')


@pytest.fixture
def media(config_file,tmp_path,monkeypatch):
    from core import config_manager,tmdb_client
    src=tmp_path/'source'/'input.mkv';src.parent.mkdir();src.write_bytes(b'original-media')
    config=config_manager.load_config(config_file)
    config.update(source_folders=[str(src.parent)],download_images=False,subtitle={'enabled':False})
    details={'name':TEXT,'title':TEXT,'overview':TEXT,'first_air_date':'2024-01-01',
             'release_date':'2024-01-01','seasons':[{'season_number':1,'episode_count':2}],
             'poster_path':'/poster.png','backdrop_path':'/backdrop.png'}
    episodes=[{'episode_number':i,'name':'Pilot' if i==1 else '', 'overview':TEXT,'air_date':'2024-02-01'} for i in (1,2)]
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda *a,**k:details)
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',lambda *a,**k:episodes)
    return src,config,details,episodes


@pytest.mark.parametrize('kind',['movie','tvshow','episode'])
def test_xml_round_trip_does_not_double_escape(kind,media,tmp_path):
    from core import nfo_writer
    _,config,_,_=media
    directory=tmp_path/'nfo'
    if kind=='movie':
        nfo_writer.write_movie_nfo(directory,TEXT,1,TEXT,'2024',config)
    elif kind=='tvshow':
        nfo_writer.write_tvshow_nfo(directory,TEXT,1,TEXT,'2024',1,config)
    else:
        nfo_writer.write_episode_nfo(directory,{'name':TEXT,'overview':TEXT},TEXT,1,1,1,config)
    path,=directory.glob('*.nfo')
    parsed=ET.parse(path).getroot()
    assert parsed.findtext('title')==TEXT and parsed.findtext('plot')==TEXT


@pytest.mark.parametrize('manual',[False,True])
@pytest.mark.parametrize('add_year',[False,True])
@pytest.mark.parametrize('episode_name',['Pilot',''])
def test_episode_nfo_uses_video_stem(manual,add_year,episode_name,media):
    from core.processor_manual import process_video_with_manual_correction
    from core.processor_tv import process_tv_branch
    src,config,details,episodes=media
    config['add_year_to_folder']=add_year
    episodes[0]['name']=episode_name
    cache={}
    if manual:
        assert process_video_with_manual_correction(src,config,cache,1,'tv',1,1)
    else:
        assert process_tv_branch(src,config,cache,None,TEXT,'2024',1,details,{'season':1,'episode':1},90)
    video=Path(cache[str(src)]['target'])
    assert video.with_suffix('.nfo').is_file()
    assert set(video.parent.glob('*.nfo'))=={video.with_suffix('.nfo'),video.parent/'season.nfo'}
    assert src.read_bytes()==video.read_bytes()==b'original-media'


@pytest.mark.parametrize('link_type',['hard','symlink'])
def test_repair_restores_every_episode_and_season_at_cached_paths(link_type,media,monkeypatch):
    from core import processor_repair,tmdb_client
    src,config,details,episodes=media
    cache={};originals={};calls=[]
    for i in (1,2):
        target=Path(config['tv_target_folder'])/'Legacy Show'/'Season 01'/f'custom-original-{i}.mkv'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.hardlink_to(src) if link_type == 'hard' else target.symlink_to(src)
        cache[str(src) if i==1 else str(src.with_name('second.mkv'))]={
            'target':str(target),'media_type':'tv','tmdb_id':1,'title':TEXT,'season':1,'episode':i}
        originals[target]=(target.read_bytes(),target.stat().st_ino)
    def season(*a,**k):
        calls.append((a,k));return episodes
    monkeypatch.setattr(tmdb_client,'get_tv_season_episodes',season)
    processor_repair.repair_missing_metadata(config,cache)
    for video,before in originals.items():
        assert video.with_suffix('.nfo').is_file()
        assert (video.read_bytes(),video.stat().st_ino)==before
        assert video.is_symlink() == (link_type == 'symlink')
        assert (video.parent/'season.nfo').is_file()
    assert len(calls)==1
    victim=next(iter(originals)).with_suffix('.nfo');victim.unlink()
    processor_repair.repair_missing_metadata(config,cache)
    assert victim.is_file()
    assert src.read_bytes()==b'original-media'


@pytest.mark.parametrize('kind',['movie','tv'])
def test_repair_and_manual_images_forward_proxy(kind,media,monkeypatch):
    from core import processor_repair,tmdb_client
    from core.processor_manual import process_video_with_manual_correction
    src,config,_,_=media
    config['download_images']=True;config['tmdb_api']['proxy']='http://proxy.invalid:8080'
    seen=[]
    monkeypatch.setattr(tmdb_client,'download_image',lambda *a,**k:seen.append(k.get('proxy')) or True)
    cache={}
    assert process_video_with_manual_correction(src,config,cache,1,kind,1,1)
    assert len(seen)==2 and set(seen)=={config['tmdb_api']['proxy']}
    seen.clear()
    processor_repair.repair_missing_metadata(config,cache)
    assert len(seen)==2 and set(seen)=={config['tmdb_api']['proxy']}


@pytest.mark.parametrize('bad',[b'',b'<movie><title>unfinished'])
def test_invalid_nfo_is_rebuilt_with_backup(bad,media,tmp_path):
    from core import nfo_writer
    _,config,_,_=media
    path=tmp_path/'movie.nfo';path.write_bytes(bad)
    nfo_writer.write_movie_nfo(tmp_path,TEXT,1,TEXT,'2024',config)
    assert ET.parse(path).findtext('title')==TEXT
    backup,=tmp_path.glob('movie.nfo.t08-*.bak')
    assert backup.read_bytes()==bad


def test_atomic_metadata_replace_failure_preserves_original(media,tmp_path,monkeypatch):
    from core import nfo_writer
    _,config,_,_=media
    path=tmp_path/'movie.nfo';path.write_bytes(b'<unfinished')
    def fail(*a):raise OSError('replace interrupted')
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError,match='replace interrupted'):
        nfo_writer.write_movie_nfo(tmp_path,TEXT,1,TEXT,'2024',config)
    assert path.read_bytes()==b'<unfinished' and not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('body',[b'',b'<html>upstream error</html>',png_bytes()[:40]])
def test_invalid_download_never_becomes_cached_image(body,tmp_path,monkeypatch):
    from core import tmdb_client
    class Response:
        content=body
        def raise_for_status(self):pass
    class Session:
        def get(self,*a,**k):return Response()
    monkeypatch.setattr(tmdb_client,'create_session',lambda *a:Session())
    path=tmp_path/'poster.jpg'
    assert not tmdb_client.download_image('https://example.invalid/image',path)
    assert not path.exists() and not list(tmp_path.glob('*.tmp'))


def test_invalid_cached_image_is_refetched_and_backed_up(tmp_path,monkeypatch):
    from core import tmdb_client
    path=tmp_path/'poster.jpg';path.write_bytes(b'not an image')
    calls=[]
    class Response:
        content=png_bytes()
        def raise_for_status(self):pass
    class Session:
        def get(self,*a,**k):calls.append(1);return Response()
    monkeypatch.setattr(tmdb_client,'create_session',lambda *a:Session())
    assert tmdb_client.download_image('https://example.invalid/image',path)
    assert calls==[1] and path.read_bytes()==png_bytes()
    backup,=tmp_path.glob('poster.jpg.t08-*.bak');assert backup.read_bytes()==b'not an image'
    assert tmdb_client.download_image('https://example.invalid/image',path) and calls==[1]


def test_shared_metadata_has_one_atomic_publication(tmp_path):
    from core.metadata_io import write_metadata,is_valid_nfo
    gate=threading.Barrier(4);path=tmp_path/'tvshow.nfo'
    def publish(i):
        gate.wait(timeout=5)
        return write_metadata(path,f'<tvshow><title>{i}</title></tvshow>'.encode(),lambda p:is_valid_nfo(p,'tvshow'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(publish,range(4)))
    assert sum(result)==1
    assert ET.parse(path).getroot().tag=='tvshow'
    assert not list(tmp_path.glob('*.tmp'))


def test_repair_refuses_source_target_and_reports_conflict(media):
    from core.processor_repair import repair_missing_metadata
    src,config,_,_=media
    result=repair_missing_metadata(config,{str(src):{'target':str(src),'media_type':'movie','tmdb_id':1}})
    assert result['failed']==1 and result['errors']
    assert not list(src.parent.glob('*.nfo')) and src.read_bytes()==b'original-media'


def test_repair_refuses_sidecar_linked_to_source(media):
    from core.processor_repair import repair_missing_metadata
    src,config,_,_=media
    video=Path(config['movie_target_folder'])/'Old'/'Old.mkv'
    video.parent.mkdir(parents=True);video.hardlink_to(src)
    sidecar=video.parent/'movie.nfo';sidecar.hardlink_to(src)
    result=repair_missing_metadata(config,{str(src):{'target':str(video),'media_type':'movie','tmdb_id':1}})
    assert result['failed']==1
    assert sidecar.read_bytes()==src.read_bytes()==b'original-media'
    assert not list(video.parent.glob('*.bak'))


def test_organize_rejects_invalid_existing_metadata_until_repair(media):
    from core.processor_manual import process_video_with_manual_correction
    from core.media_paths import episode_video_path
    src,config,details,episodes=media
    video=episode_video_path(src,config,TEXT,'2024',1,1,episodes[0]['name'])
    path=video.parent.parent/'tvshow.nfo';path.parent.mkdir(parents=True);path.write_bytes(b'<broken')
    cache={}
    assert not process_video_with_manual_correction(src,config,cache,1,'tv',1,1)
    assert path.read_bytes()==b'<broken' and not video.exists()
    assert src.read_bytes()==b'original-media'


def test_valid_custom_nfo_is_kept_without_enhancement(media,tmp_path,monkeypatch):
    from core import nfo_writer,ai_client
    _,config,_,_=media
    config['ai_plot_enhance']['enabled']=True
    path=tmp_path/'movie.nfo';path.write_bytes(b'<movie><title>My custom title</title></movie>')
    before=(path.read_bytes(),path.stat().st_mtime_ns,path.stat().st_ino)
    monkeypatch.setattr(ai_client,'enhance_plot',lambda *a:pytest.fail('replaced valid custom metadata'))
    nfo_writer.write_movie_nfo(tmp_path,TEXT,1,TEXT,'2024',config)
    assert (path.read_bytes(),path.stat().st_mtime_ns,path.stat().st_ino)==before


@pytest.mark.parametrize('existing',[False,True])
def test_failed_image_publication_preserves_old_or_absent_file(existing,tmp_path,monkeypatch):
    from core import tmdb_client
    path=tmp_path/'poster.jpg'
    if existing:path.write_bytes(b'old-invalid-image')
    class Response:
        content=png_bytes()
        def raise_for_status(self):pass
    class Session:
        def get(self,*a,**k):return Response()
    monkeypatch.setattr(tmdb_client,'create_session',lambda *a:Session())
    def fail(*a):raise OSError('publication failed')
    monkeypatch.setattr(os,'replace',fail)
    assert not tmdb_client.download_image('https://example.invalid/image',path)
    assert path.read_bytes()==b'old-invalid-image' if existing else not path.exists()
    assert not list(tmp_path.glob('*.tmp'))


def test_repair_preview_plans_missing_episode_without_writing(media,monkeypatch):
    from core import nfo_writer,processor_repair
    src,config,_,_=media
    target=Path(config['tv_target_folder'])/'Legacy'/'Season 01'/'custom.mkv'
    target.parent.mkdir(parents=True);target.hardlink_to(src)
    cache={str(src):{'target':str(target),'media_type':'tv','tmdb_id':1,'season':1,'episode':1}}
    before={str(p):p.read_bytes() for p in target.parent.parent.rglob('*') if p.is_file()}
    for name in ('write_tvshow_nfo','write_season_nfo','write_episode_nfo'):
        monkeypatch.setattr(nfo_writer,name,lambda *a,**k:pytest.fail('preview wrote metadata'))
    config['dry_run']=True
    result=processor_repair.repair_missing_metadata(config,cache)
    assert result['planned']==3 and result['repaired']==0
    assert {str(p):p.read_bytes() for p in target.parent.parent.rglob('*') if p.is_file()}==before


def test_publication_race_does_not_accept_new_invalid_nfo(media,monkeypatch):
    from core.processor_manual import process_video_with_manual_correction
    src,config,_,_=media
    actual_link=os.link
    created=[]
    def racing_link(source,destination,*a,**k):
        destination=Path(destination)
        if destination.name=='movie.nfo' and '.animeman-stage-' not in str(destination):
            destination.write_bytes(b'<concurrent-invalid')
            created.append(destination)
            raise FileExistsError(str(destination))
        return actual_link(source,destination,*a,**k)
    monkeypatch.setattr(os,'link',racing_link)
    cache={}
    assert not process_video_with_manual_correction(src,config,cache,1,'movie',1,1)
    assert created and created[0].read_bytes()==b'<concurrent-invalid'
    assert not list(Path(config['movie_target_folder']).rglob('*.mkv'))
    assert src.read_bytes()==b'original-media'


def test_cancel_after_temp_write_keeps_existing_nfo(media,tmp_path,monkeypatch):
    from core import nfo_writer
    from core.cancellation import cancellation_scope,ProcessingCancelled
    _,config,_,_=media
    path=tmp_path/'movie.nfo';path.write_bytes(b'<old-invalid')
    stopped=threading.Event()
    actual=os.fsync
    def fsync_then_stop(fd):
        actual(fd);stopped.set()
    monkeypatch.setattr(os,'fsync',fsync_then_stop)
    with cancellation_scope(stopped),pytest.raises(ProcessingCancelled):
        nfo_writer.write_movie_nfo(tmp_path,TEXT,1,TEXT,'2024',config)
    assert path.read_bytes()==b'<old-invalid'
    assert not list(tmp_path.glob('*.tmp')) and not list(tmp_path.glob('*.bak'))


def test_nfo_serialization_failure_never_creates_final_file(media,tmp_path,monkeypatch):
    from core import nfo_writer
    _,config,_,_=media
    def fail(*a):raise OSError('serialization interrupted')
    monkeypatch.setattr(nfo_writer,'_prettify',fail)
    with pytest.raises(OSError,match='serialization interrupted'):
        nfo_writer.write_movie_nfo(tmp_path,TEXT,1,TEXT,'2024',config)
    assert not (tmp_path/'movie.nfo').exists() and not list(tmp_path.glob('*.tmp'))


def test_invalid_metadata_backup_failure_blocks_replacement(media,tmp_path,monkeypatch):
    from core import nfo_writer,metadata_io
    _,config,_,_=media
    path=tmp_path/'movie.nfo';path.write_bytes(b'<original-invalid')
    def fail(*a,**k):raise PermissionError('backup denied')
    monkeypatch.setattr(metadata_io,'backup_json',fail)
    with pytest.raises(PermissionError,match='backup denied'):
        nfo_writer.write_movie_nfo(tmp_path,TEXT,1,TEXT,'2024',config)
    assert path.read_bytes()==b'<original-invalid' and not list(tmp_path.glob('*.tmp'))
