"""E01: explicit local identity evidence must be typed and source bounded."""
from pathlib import Path
import pytest


@pytest.mark.parametrize('tag,ident', [('{tmdb-123}',123),('[tmdbid=456]',456),('{TMDB-7}',7)])
def test_path_identity_tag(tag,ident,tmp_path):
    from core.explicit_media_identity import extract_path_identity
    root=tmp_path/'source';folder=root/f'Show {tag}';folder.mkdir(parents=True)
    src=folder/'Show S01E01.mkv';src.write_bytes(b'synthetic')
    assert extract_path_identity(src,[root])==ident


@pytest.mark.parametrize('tag', ['{tmdb-0}','{tmdb--1}','{tmdb-12345678901234567890}','[tmdbid=0]'])
def test_invalid_path_identity_is_never_accepted(tag,tmp_path):
    from core.explicit_media_identity import extract_path_identity, IdentityEvidenceError
    root=tmp_path/'source';root.mkdir();src=root/f'Show {tag}.mkv';src.write_bytes(b'synthetic')
    with pytest.raises(IdentityEvidenceError):extract_path_identity(src,[root])


def test_conflicting_path_ids_need_review(tmp_path):
    from core.explicit_media_identity import extract_path_identity, IdentityEvidenceError
    root=tmp_path/'source';folder=root/'Show {tmdb-123}';folder.mkdir(parents=True)
    src=folder/'Show [tmdbid=456].mkv';src.write_bytes(b'synthetic')
    with pytest.raises(IdentityEvidenceError):extract_path_identity(src,[root])


def test_identity_outside_source_is_not_used(tmp_path):
    from core.explicit_media_identity import extract_path_identity
    root=tmp_path/'Outside {tmdb-999}'/'source';root.mkdir(parents=True)
    src=root/'Show S01E01.mkv';src.write_bytes(b'synthetic')
    assert extract_path_identity(src,[root]) is None


def test_disabled_by_default_does_not_use_tag(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    src=tmp_path/'src'/'Show {tmdb-123} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg['source_folders']=[str(src.parent)]
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:{'media_type':'tv','title':'Show','season':1,'episode':1})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    calls=[]
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:(calls.append(1) or (None,'tv',0)))
    assert not processor_core.process_video(src,cfg,{}) and calls==[1]


def test_explicit_tv_id_skips_search_but_verifies_details(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Show {tmdb-123} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:{'media_type':'tv','title':'Show','season':1,'episode':1})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('explicit ID should not search'))
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    calls=[]
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:calls.append((kw['media_type'],kw['tmdb_id'])) or {'id':123,'name':'Show','seasons':[]})
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:True)
    assert processor_core.process_video(src,cfg,{})
    assert calls==[('tv',123)]


def test_path_id_conflicts_with_manual_mapping_are_not_processed(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    src=tmp_path/'src'/'Show {tmdb-123} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'apply_special_mapping',lambda *a:(456,'tv',1,1))
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:{'media_type':'tv','title':'Show','season':1,'episode':1,'tmdb_id':456})
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('conflicting identity must not search'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['media_type']=='failed'
    assert src.read_bytes()==b'synthetic'


def test_untyped_explicit_id_requires_review(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    src=tmp_path/'src'/'Show {tmdb-123}.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:{'media_type':'movie','title':'Show'})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:pytest.fail('untyped ID cannot use AI to guess type'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['media_type']=='failed'


def test_mismatched_details_for_explicit_id_cannot_write_or_fallback(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Show {tmdb-123} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:{'media_type':'tv','title':'Show','season':1,'episode':1})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':124,'name':'Wrong'})
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('cannot fall back'))
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:pytest.fail('identity mismatch cannot write'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['media_type']=='failed'
    assert src.read_bytes()==b'synthetic'


def test_invalid_hint_is_rejected_before_parser_or_ai(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    src=tmp_path/'src'/'Show {tmdb-0} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:pytest.fail('invalid hint must be rejected before parsing'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['media_type']=='failed'


def test_explicit_identity_disables_new_ai_parsing(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Show {tmdb-123} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    cfg['ai_parser'].update(enabled=True,api_key='synthetic')
    def parse(_src,local_cfg,*a):
        assert local_cfg['ai_parser']['enabled'] is False
        return {'media_type':'tv','title':'Show','season':1,'episode':1}
    monkeypatch.setattr(processor_core,'parse_filename_info',parse)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':123,'name':'Show'})
    monkeypatch.setattr(processor_core,'process_tv_branch',lambda *a:True)
    assert processor_core.process_video(src,cfg,{})
    assert cfg['ai_parser']['enabled'] is True


def test_identity_hint_config_requires_boolean():
    from copy import deepcopy
    from core.config_manager import DEFAULT_CONFIG
    from core.validation import validate_config, ValidationError
    cfg=deepcopy(DEFAULT_CONFIG);cfg['identity_hints']={'enabled':'yes'}
    with pytest.raises(ValidationError):validate_config(cfg)


def test_movie_and_tv_identity_same_id_require_type_evidence(tmp_path):
    from core.explicit_media_identity import explicit_media_type
    root=tmp_path/'source';tv=root/'TV'/'Show {tmdb-7} S01E01.mkv';movie=root/'Movies'/'Film {tmdb-7}.mkv'
    tv.parent.mkdir(parents=True);movie.parent.mkdir(parents=True)
    tv.write_bytes(b'synthetic');movie.write_bytes(b'synthetic')
    assert explicit_media_type(tv,[root])=='tv'
    assert explicit_media_type(movie,[root])=='movie'
