"""T05: preview mode performs no media/config/cache writes."""

from copy import deepcopy
import importlib
import json
from pathlib import Path

import pytest

from core import cache_manager, config_manager, tmdb_client


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob('*') if 'logs' not in path.relative_to(root).parts}


@pytest.fixture
def media(config_file, tmp_path, monkeypatch):
    src = tmp_path / 'source' / 'episode.mkv'
    src.parent.mkdir()
    src.write_bytes(b'temporary-video')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], dry_run=False, download_images=True)
    cfg['subtitle'] = {'enabled': True, 'auto_sync': True}
    config_manager.save_config(cfg, config_file)
    details = {'title': 'Example', 'name': 'Example', 'overview': 'sample',
               'poster_path': '/fake.jpg', 'backdrop_path': '/fake-bg.jpg',
               'seasons': [{'season_number': 1, 'episode_count': 1}]}
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: details)
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: [
        {'episode_number': 1, 'name': 'Pilot'}])
    return src, cfg, details


@pytest.mark.parametrize('flags,expected', [
    (['--dry-run'], {'dry_run': True}),
    (['--force-full'], {'incremental': False}),
    (['--dry-run', '--force-full'], {'dry_run': True, 'incremental': False}),
])
def test_cli_passes_overrides_without_editing_config(flags, expected, config_file, monkeypatch):
    import main
    original = config_file.read_bytes()
    calls = []
    monkeypatch.setattr('sys.argv', ['main.py', '--config', str(config_file), *flags])
    monkeypatch.setattr(main, 'run_processor_with_callback', lambda *a, **k: calls.append(k))
    main.main()
    assert calls[0]['config_overrides'] == expected
    assert config_file.read_bytes() == original


@pytest.mark.parametrize('kind', ['movie', 'tv', 'manual_movie', 'manual_tv'])
def test_preview_branches_never_create_stage_or_metadata(kind, media, tmp_path, monkeypatch):
    from core import processor_movie, processor_tv, processor_manual, nfo_writer, subtitle_handler
    src, cfg, details = media
    cfg['dry_run'] = True
    def forbidden(*a, **k):
        pytest.fail('preview must plan before invoking a writer')
    for name in ('write_movie_nfo', 'write_tvshow_nfo', 'write_season_nfo', 'write_episode_nfo'):
        monkeypatch.setattr(nfo_writer, name, forbidden)
    monkeypatch.setattr(tmdb_client, 'download_image', forbidden)
    monkeypatch.setattr(subtitle_handler, 'process_subtitles_for_video', forbidden)
    before = snapshot(tmp_path)
    cache = {}
    messages = []
    def log(*args):
        messages.append(str(args))
    if kind == 'movie':
        result = processor_movie.process_movie_branch(src, cfg, cache, log, 'Example', '', 1, details, 90)
    elif kind == 'tv':
        result = processor_tv.process_tv_branch(src, cfg, cache, log, 'Example', '', 1, details,
                                                {'season': 1, 'episode': 1}, 90)
    else:
        result = processor_manual.process_video_with_manual_correction(src, cfg, cache, 1, kind.split('_')[1], 1, 1, log)
    assert result
    assert snapshot(tmp_path) == before
    assert cache == {}
    assert messages and '.animeman-stage-' not in ''.join(messages)


def test_runner_preview_propagates_readonly_context_to_workers(media, config_file, monkeypatch, tmp_path):
    from core import processor_runner, parser_manager
    src, cfg, details = media
    cache_manager.save_cache({'old': {'media_type': 'failed'}})
    before = snapshot(tmp_path)
    received = []
    def process(source, effective, result, log):
        received.append(deepcopy(effective))
        cache_manager.save_cache({'unexpected-write': {}})
        parser_manager._save_parse_result('new', {'title': 'preview'})
        return True
    monkeypatch.setattr(processor_runner, 'process_video', process)
    processor_runner.run_processor_with_callback(str(config_file), lambda *a: None,
                                                  config_overrides={'dry_run': True, 'incremental': False})
    assert received[0]['dry_run'] is True and received[0]['incremental'] is False
    assert snapshot(tmp_path) == before


def test_full_run_reprocesses_but_preserves_and_saves_history(media, config_file, monkeypatch):
    from core import processor_runner
    src, cfg, details = media
    cache_manager.save_cache({str(src): {'target': 'old', 'media_type': 'movie'},
                              'unscanned': {'media_type': 'failed'}})
    seen = []
    def process(source, effective, result, log):
        seen.append(source)
        result[str(source)] = {'target': 'new', 'media_type': 'movie'}
        return True
    monkeypatch.setattr(processor_runner, 'process_video', process)
    processor_runner.run_processor_with_callback(str(config_file), lambda *a: None,
                                                  config_overrides={'incremental': False})
    assert seen == [src]
    assert cache_manager.load_cache()[str(src)]['target'] == 'new'
    assert 'unscanned' in cache_manager.load_cache()


def test_cli_preview_missing_config_does_not_create_default(tmp_path, monkeypatch):
    import main
    path = tmp_path / 'missing.json'
    monkeypatch.setattr('sys.argv', ['main.py', '--config', str(path), '--dry-run'])
    before = snapshot(tmp_path)
    main.main()
    assert snapshot(tmp_path) == before
    assert not path.exists()


@pytest.mark.parametrize('media_type', ['movie', 'tv'])
def test_preview_repair_uses_cache_even_when_full_and_writes_nothing(media_type, media, config_file, monkeypatch, tmp_path):
    import main
    from core import nfo_writer
    src, cfg, details = media
    folder = Path(cfg['movie_target_folder'] if media_type == 'movie' else cfg['tv_target_folder']) / 'Old'
    if media_type == 'tv':
        folder /= 'Season 01'
    folder.mkdir(parents=True)
    target = folder / 'old.mkv'
    target.hardlink_to(src)
    cache_manager.save_cache({str(src): {'target': str(target), 'media_type': media_type,
                                       'tmdb_id': 1, 'title': 'Old', 'year': ''}})
    calls = []
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: calls.append(a) or details)
    def forbidden(*a, **k):
        pytest.fail('repair preview invoked a writer')
    monkeypatch.setattr(nfo_writer, 'write_movie_nfo', forbidden)
    monkeypatch.setattr(nfo_writer, 'write_tvshow_nfo', forbidden)
    monkeypatch.setattr(tmdb_client, 'download_image', forbidden)
    before = snapshot(tmp_path)
    monkeypatch.setattr('sys.argv', ['main.py', '--config', str(config_file), '--dry-run', '--force-full', '--repair'])
    main.main()
    assert calls
    assert snapshot(tmp_path) == before


def test_preview_correction_does_not_quarantine_or_clean_old_cache(media, tmp_path):
    from core.library_transaction import reprocess_safely
    src, cfg, details = media
    cfg['dry_run'] = True
    cache_manager.save_cache({str(src): {'target': str(src), 'media_type': 'movie'}})
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        reprocess_safely(src, cfg, lambda *a: True)
    assert snapshot(tmp_path) == before


def test_preview_subtitle_organization_does_not_sync_or_copy(media, tmp_path, monkeypatch):
    from core import subtitle_handler
    src, cfg, details = media
    cfg['dry_run'] = True
    sub = src.with_suffix('.ass')
    sub.write_text('temporary subtitle')
    monkeypatch.setattr(subtitle_handler, 'sync_subtitle_with_ffsubsync', lambda *a: pytest.fail('preview tried sync'))
    folder = Path(cfg['tv_target_folder']) / 'Example'
    before = snapshot(tmp_path)
    assert subtitle_handler.execute_subtitle_organization(str(sub), {'target_path': str(folder / 'episode.mkv'),
                                                           'target_dir': str(folder)}, cfg, auto_sync=True)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('module,function', [
    ('core.cache_manager', 'save_cache'), ('core.cache_manager', 'save_ai_parse_cache'),
    ('core.folder_ai_cache', 'save_folder_cache'), ('core.folder_parser', 'save_folder_cache'),
    ('core.offline_ai_preparser', 'save_raw_cache'), ('core.offline_ai_preparser', 'save_ai_preparse_cache'),
    ('core.media_library_cache', 'save_media_library_cache'),
])
def test_preview_suppresses_all_persistent_cache_savers(module, function, tmp_path):
    from core.execution_mode import preview_mode
    save = getattr(importlib.import_module(module), function)
    save({'original': 1})
    before = snapshot(tmp_path)
    with preview_mode(True):
        save({'preview': 2})
    assert snapshot(tmp_path) == before


def test_preview_tmdb_expiry_does_not_rewrite_cache(tmp_path):
    from core import tmdb_cache
    from core.execution_mode import preview_mode
    tmdb_cache.set_cached_result('sample', 'tv', '', {'id': 1}, ttl=-1)
    before = snapshot(tmp_path)
    with preview_mode(True):
        assert tmdb_cache.get_cached_result('sample', 'tv') is None
        tmdb_cache.set_cached_result('another', 'movie', '', {'id': 2})
    assert snapshot(tmp_path) == before


def test_direct_sync_preview_does_not_launch_subprocess(media, tmp_path, monkeypatch):
    from core import subtitle_handler
    src, cfg, details = media
    cfg['dry_run'] = True
    sub = src.with_suffix('.ass')
    sub.write_text('sample')
    monkeypatch.setattr(subtitle_handler.subprocess, 'run', lambda *a, **k: pytest.fail('preview launched subprocess'))
    before = snapshot(tmp_path)
    assert subtitle_handler.sync_subtitle_with_ffsubsync(src, sub, cfg) is None
    assert snapshot(tmp_path) == before


def test_web_preview_subtitle_rename_is_labelled_as_planned(media, client, config_file, tmp_path):
    src, cfg, details = media
    cfg['dry_run'] = True
    config_manager.save_config(cfg, config_file)
    sub = src.with_suffix('.ass')
    sub.write_text('sample')
    before = snapshot(tmp_path)
    response = client.post('/api/subtitle/batch_rename', auth=('test-user', 'test-pass'), json={
        'renames': [{'old_path': str(sub), 'new_path': str(src.with_name('renamed.ass'))}]})
    assert response.status_code == 200
    assert response.json['dry_run'] is True and response.json['planned'] == 1
    assert response.json['success'] == 0
    assert snapshot(tmp_path) == before


def test_web_preview_correction_preserves_old_target_and_cache(media, client, config_file, tmp_path):
    src, cfg, details = media
    cfg['dry_run'] = True
    config_manager.save_config(cfg, config_file)
    target = Path(cfg['movie_target_folder']) / 'Old' / 'old.mkv'
    target.parent.mkdir(parents=True)
    target.hardlink_to(src)
    cache_manager.save_cache({str(src): {'target': str(target), 'media_type': 'movie'}})
    before = snapshot(tmp_path)
    response = client.post('/api/failed_cache/correct', auth=('test-user', 'test-pass'), json={
        'src_path': str(src), 'tmdb_id': 1, 'media_type': 'movie'})
    assert response.status_code == 200 and response.json['dry_run'] is True
    assert snapshot(tmp_path) == before


def test_cli_preview_runs_real_parser_without_cache_or_media_writes(media, config_file, monkeypatch, tmp_path):
    import main
    from core import processor_core
    src, cfg, details = media
    monkeypatch.setattr(processor_core.video_info, 'get_video_duration', lambda *a: None)
    monkeypatch.setattr(processor_core, 'compute_confidence', lambda *a: 90)
    monkeypatch.setattr(processor_core, 'search_tmdb_with_fallback', lambda *a, **k: ({'id': 1}, 'movie', 1))
    before = snapshot(tmp_path)
    monkeypatch.setattr('sys.argv', ['main.py', '--config', str(config_file), '--dry-run', '--force-full'])
    main.main()
    assert snapshot(tmp_path) == before


def test_preview_rejects_conflicting_target_without_touching_it(media):
    from core.processor_movie import process_movie_branch
    src, cfg, details = media
    cfg['dry_run'] = True
    target = Path(cfg['movie_target_folder']) / 'Example' / 'Example.mkv'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'other-version')
    cache = {}
    assert not process_movie_branch(src, cfg, cache, None, 'Example', '', 1, details, 90)
    assert target.read_bytes() == b'other-version' and cache == {}


def test_web_preview_conflict_returns_409_without_writes(media, client, config_file, tmp_path):
    src, cfg, details = media
    cfg['dry_run'] = True
    config_manager.save_config(cfg, config_file)
    target = Path(cfg['movie_target_folder']) / 'Example' / 'Example.mkv'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'other-version')
    before = snapshot(tmp_path)
    response = client.post('/api/failed_cache/correct', auth=('test-user', 'test-pass'), json={
        'src_path': str(src), 'tmdb_id': 1, 'media_type': 'movie'})
    assert response.status_code == 409 and response.json['code'] == 'target_conflict'
    assert snapshot(tmp_path) == before
