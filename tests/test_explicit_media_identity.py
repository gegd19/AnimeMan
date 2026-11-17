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


def test_movie_sidecar_provides_typed_identity(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity
    root=tmp_path/'source';root.mkdir();src=root/'Film.mkv';src.write_bytes(b'synthetic')
    nfo=root/'Film.nfo';raw=b'<movie><uniqueid type="tmdb">123</uniqueid></movie>';nfo.write_bytes(raw)
    assert extract_nfo_identity(src,[root])==('movie',123)
    assert src.read_bytes()==b'synthetic' and nfo.read_bytes()==raw


def test_tvshow_nfo_stays_within_source_root(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity
    parent=tmp_path/'outside';root=parent/'source';season=root/'Season 02';season.mkdir(parents=True)
    src=season/'Show S02E01.mkv';src.write_bytes(b'synthetic')
    (parent/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">999</uniqueid></tvshow>')
    assert extract_nfo_identity(src,[root]) is None
    (root/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">123</uniqueid></tvshow>')
    assert extract_nfo_identity(src,[root])==('tv',123)


@pytest.mark.parametrize('raw',[
    '<episodedetails><uniqueid type="tmdb">123</uniqueid></episodedetails>',
    '<episodedetails><uniqueid type="tmdb">123/2/1</uniqueid></episodedetails>',
    '<movie><uniqueid type="tmdb">0</uniqueid></movie>',
    '<!DOCTYPE movie [<!ENTITY x SYSTEM "file:///etc/passwd">]><movie>&x;</movie>',
    '<movie><uniqueid type="tmdb">123',
])
def test_ambiguous_or_unsafe_nfo_requires_review(tmp_path,raw):
    from core.explicit_media_identity import extract_nfo_identity, IdentityEvidenceError
    root=tmp_path/'source';root.mkdir();src=root/'Episode.mkv';src.write_bytes(b'synthetic')
    (root/'Episode.nfo').write_text(raw)
    with pytest.raises(IdentityEvidenceError):extract_nfo_identity(src,[root])


def test_generic_id_without_tmdb_type_is_not_used(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity
    root=tmp_path/'source';root.mkdir();src=root/'Film.mkv';src.write_bytes(b'synthetic')
    (root/'Film.nfo').write_text('<movie><id>123</id></movie>')
    assert extract_nfo_identity(src,[root]) is None


def test_symlink_nfo_and_oversized_nfo_rejected(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity, IdentityEvidenceError
    root=tmp_path/'source';root.mkdir();src=root/'Film.mkv';src.write_bytes(b'synthetic')
    external=tmp_path/'external.nfo';external.write_text('<movie><uniqueid type="tmdb">123</uniqueid></movie>')
    link=root/'Film.nfo';link.symlink_to(external)
    with pytest.raises(IdentityEvidenceError):extract_nfo_identity(src,[root])
    link.unlink();link.write_bytes(b'x'*(1024*1024+1))
    with pytest.raises(IdentityEvidenceError):extract_nfo_identity(src,[root])


def test_conflicting_nfo_and_path_hints_require_review(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    src=tmp_path/'src'/'Show {tmdb-123} S01E01.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    (src.parent/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">456</uniqueid></tvshow>')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:pytest.fail('conflicting IDs must be rejected before parsing'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['media_type']=='failed'


def test_utf16_doctype_is_rejected(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity, IdentityEvidenceError
    root=tmp_path/'source';root.mkdir();src=root/'Film.mkv';src.write_bytes(b'synthetic')
    raw='<!DOCTYPE movie [<!ENTITY x "123">]><movie><uniqueid type="tmdb">&x;</uniqueid></movie>'.encode('utf-16')
    (root/'Film.nfo').write_bytes(raw)
    with pytest.raises(IdentityEvidenceError):extract_nfo_identity(src,[root])


def test_movie_nfo_identity_skips_search_after_type_validation(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'src'/'Film.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    nfo=src.with_suffix('.nfo');raw=b'<movie><uniqueid type="tmdb">123</uniqueid></movie>';nfo.write_bytes(raw)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:{'media_type':'movie','title':'Film'})
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:pytest.fail('NFO ID should not search'))
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':123,'title':'Film'})
    monkeypatch.setattr(processor_core,'process_movie_branch',lambda *a:True)
    assert processor_core.process_video(src,cfg,{})
    assert nfo.read_bytes()==raw and src.read_bytes()==b'synthetic'


def test_tv_episode_nfo_with_tmdb_id_requires_review_even_with_series_nfo(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity, IdentityEvidenceError
    root=tmp_path/'source';root.mkdir();src=root/'Show S01E01.mkv';src.write_bytes(b'synthetic')
    src.with_suffix('.nfo').write_text('<episodedetails><uniqueid type="tmdb">321</uniqueid></episodedetails>')
    (root/'tvshow.nfo').write_text('<tvshow><uniqueid type="tmdb">123</uniqueid></tvshow>')
    with pytest.raises(IdentityEvidenceError):extract_nfo_identity(src,[root])


def test_conflicting_path_types_cannot_be_resolved_by_nfo(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    root=tmp_path/'source';src=root/'Movies'/'Show S01E01.mkv';src.parent.mkdir(parents=True);src.write_bytes(b'synthetic')
    src.with_suffix('.nfo').write_text('<movie><uniqueid type="tmdb">123</uniqueid></movie>')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],identity_hints={'enabled':True})
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:pytest.fail('type conflict requires review before parsing'))
    cache={}
    assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['media_type']=='failed'


def test_enabled_without_any_identity_hint_preserves_normal_flow(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core
    root=tmp_path/'source';src=root/'Movies'/'Show S01E01.mkv';src.parent.mkdir(parents=True);src.write_bytes(b'synthetic')
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(root)],identity_hints={'enabled':True})
    calls=[]
    monkeypatch.setattr(processor_core,'parse_filename_info',lambda *a,**kw:calls.append('parse') or {'media_type':'tv','title':'Show','season':1,'episode':1})
    monkeypatch.setattr(processor_core,'try_folder_ai_batch',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**kw:(None,'tv',0))
    assert not processor_core.process_video(src,cfg,{})
    assert calls==['parse']


def test_movie_nfo_end_to_end_preserves_source_and_uses_typed_id(tmp_path,config_file,monkeypatch):
    from core import config_manager,processor_core,tmdb_client,video_info
    src=tmp_path/'source'/'Film.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    nfo=src.with_suffix('.nfo');raw=b'<movie><uniqueid type="tmdb">123</uniqueid></movie>';nfo.write_bytes(raw)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True},download_images=False)
    cfg['subtitle']['enabled']=False
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('explicit NFO identity should not search'))
    monkeypatch.setattr(tmdb_client,'get_tmdb_details',lambda **kw:{'id':123,'title':'Film','release_date':'2020-01-01'})
    cache={}
    assert processor_core.process_video(src,cfg,cache)
    entry=cache[str(src.resolve())]
    assert (entry['media_type'],entry['tmdb_id'])==('movie',123)
    assert Path(entry['target']).exists()
    assert nfo.read_bytes()==raw and src.read_bytes()==b'synthetic'


def test_symlinked_source_outside_root_never_reads_external_nfo(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity
    root=tmp_path/'source';root.mkdir();outside=tmp_path/'outside';outside.mkdir()
    src=outside/'Film.mkv';src.write_bytes(b'synthetic')
    (outside/'Film.nfo').write_text('<movie><uniqueid type="tmdb">123</uniqueid></movie>')
    (root/'link').symlink_to(outside,target_is_directory=True)
    assert extract_nfo_identity(root/'link'/'Film.mkv',[root]) is None


def test_nested_person_tmdb_id_cannot_become_movie_identity(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity
    root=tmp_path/'source';root.mkdir();src=root/'Film.mkv';src.write_bytes(b'synthetic')
    src.with_suffix('.nfo').write_text('<movie><actor><uniqueid type="tmdb">123</uniqueid></actor></movie>')
    assert extract_nfo_identity(src,[root]) is None


def test_generic_movie_nfo_requires_single_video(tmp_path):
    from core.explicit_media_identity import extract_nfo_identity
    root=tmp_path/'source';root.mkdir();src=root/'Film.mkv';src.write_bytes(b'synthetic')
    (root/'movie.nfo').write_text('<movie><uniqueid type="tmdb">123</uniqueid></movie>')
    assert extract_nfo_identity(src,[root])==('movie',123)
    (root/'Different.mkv').write_bytes(b'synthetic')
    assert extract_nfo_identity(src,[root]) is None


def test_nfo_tmdb_timeout_preserves_transient_failure(tmp_path,config_file,monkeypatch):
    import requests
    from core import config_manager,processor_core,tmdb_client,video_info
    from core.failure_policy import failure_scope
    src=tmp_path/'source'/'Film.mkv';src.parent.mkdir();src.write_bytes(b'synthetic')
    nfo=src.with_suffix('.nfo');raw=b'<movie><uniqueid type="tmdb">123</uniqueid></movie>';nfo.write_bytes(raw)
    cfg=config_manager.load_config(config_file);cfg.update(source_folders=[str(src.parent)],identity_hints={'enabled':True},download_images=False)
    monkeypatch.setattr(video_info,'get_video_duration',lambda *a:None)
    monkeypatch.setattr(processor_core,'search_tmdb_with_fallback',lambda *a,**k:pytest.fail('must not search on timeout'))
    class Session:
        def get(self,*a,**k):raise requests.Timeout('synthetic')
    monkeypatch.setattr(tmdb_client,'create_session',lambda *a:Session())
    monkeypatch.setattr(tmdb_client._tmdb_limiter,'wait',lambda:None)
    cache={}
    with failure_scope(cfg):assert not processor_core.process_video(src,cfg,cache)
    assert cache[str(src.resolve())]['failure_category']=='transient'
    assert cache[str(src.resolve())]['retry_after'] is not None
    assert nfo.read_bytes()==raw and src.read_bytes()==b'synthetic'


def test_opt_in_config_round_trips_through_authenticated_api(client,config_file):
    import base64,json
    auth={'Authorization':'Basic '+base64.b64encode(b'test-user:test-pass').decode()}
    response=client.post('/api/config',json={'identity_hints':{'enabled':True}},headers=auth)
    assert response.status_code==200
    assert json.loads(config_file.read_text())['identity_hints']['enabled'] is True
    assert client.get('/api/config',headers=auth).get_json()['identity_hints']['enabled'] is True
