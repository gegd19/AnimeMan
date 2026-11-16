"""R01: season lookup must not fabricate episodes or silently switch seasons."""
import requests
import pytest


@pytest.mark.parametrize('mode', ['timeout', 'http404', 'empty'])
def test_special_lookup_never_fabricates(monkeypatch, mode):
    from core import tmdb_client
    class Response:
        status_code = 404 if mode == 'http404' else 200
        def raise_for_status(self):
            if mode == 'http404':
                raise requests.HTTPError(response=self)
        def json(self):
            return {'episodes': []}
    class Session:
        def get(self, *args, **kwargs):
            if mode == 'timeout':
                raise requests.Timeout('synthetic timeout')
            return Response()
    monkeypatch.setattr(tmdb_client, 'create_session', lambda *a: Session())
    monkeypatch.setattr(tmdb_client._tmdb_limiter, 'wait', lambda: None)
    assert tmdb_client.get_tv_season_episodes(42, 0, 'synthetic') == []


def test_cross_season_ambiguous_returns_none(monkeypatch):
    from core import tmdb_client, search_enhancer
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: {'seasons': [{'season_number': 1}, {'season_number': 2}]})
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: [{'episode_number': 1}])
    assert search_enhancer.find_episode_across_seasons(42, 1, 'synthetic') == (None, None)


def test_cross_season_does_not_infer_special(monkeypatch):
    from core import tmdb_client, search_enhancer
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: {'seasons': [{'season_number': 0}]})
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: [{'episode_number': 1}])
    assert search_enhancer.find_episode_across_seasons(42, 1, 'synthetic') == (None, None)


@pytest.mark.parametrize('scenario', ['missing_season', 'missing_episode', 'only_special'])
def test_explicit_season_never_silently_changes(tmp_path, config_file, monkeypatch, scenario):
    from core import config_manager, tmdb_client
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show S02E01.mkv'
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], dry_run=False, download_images=False)
    cfg['subtitle']['enabled'] = False
    seasons = [{'season_number': 0}] if scenario == 'only_special' else [{'season_number': 0}, {'season_number': 1}, {'season_number': 2}]
    details = {'seasons': seasons}
    def episodes(_id, season, *a, **k):
        if season == 2:
            return [{'episode_number': 2, 'name': 'other'}] if scenario == 'missing_episode' else []
        return [{'episode_number': 1, 'name': 'not the requested season'}]
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', episodes)
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: details)
    info = {'season': 2, 'episode': 1, 'explicit_season': 2, '_parser': 'regex'}
    cache = {}
    assert not process_tv_branch(src, cfg, cache, None, 'Show', '2020', 42, details, info, 80)
    assert src.read_bytes() == b'synthetic'
    assert cache.get(str(src.resolve()), {}).get('media_type') != 'tv'
    assert not list((tmp_path / 'tv').rglob('*.mkv'))
    assert not list((tmp_path / 'tv').rglob('*.nfo'))


def test_explicit_special_mapping_with_real_episode_succeeds(tmp_path, config_file, monkeypatch):
    from core import config_manager, tmdb_client
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show OVA 02.mkv'
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], dry_run=False, download_images=False)
    cfg['subtitle']['enabled'] = False
    details = {'seasons': [{'season_number': 0}]}
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: [{'episode_number': 2, 'name': 'OVA'}])
    from core.processor_helpers import apply_special_mapping
    cfg['special_mappings'] = [{'keyword': 'Show OVA', 'tmdb_id': 42, 'media_type': 'tv', 'season': 0, 'episode': 2, 'enabled': True}]
    tmdb_id, media_type, season, episode = apply_special_mapping(src, cfg, None)
    assert (tmdb_id, media_type, season, episode) == (42, 'tv', 0, 2)
    info = {'season': season, 'episode': episode, 'explicit_season': season, '_parser': 'regex'}
    cache = {}
    assert process_tv_branch(src, cfg, cache, None, 'Show', '2020', 42, details, info, 100)
    assert cache[str(src.resolve())]['season'] == 0
    assert cache[str(src.resolve())]['episode'] == 2
    assert src.read_bytes() == b'synthetic'


def test_timeout_keeps_transient_failure_and_no_artifacts(tmp_path, config_file, monkeypatch):
    from core import config_manager, tmdb_client
    from core.failure_policy import failure_scope
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show S02E01.mkv'
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], download_images=False)
    cfg['subtitle']['enabled'] = False
    class Session:
        def get(self, *a, **k):
            raise requests.Timeout('synthetic timeout')
    monkeypatch.setattr(tmdb_client, 'create_session', lambda *a: Session())
    monkeypatch.setattr(tmdb_client._tmdb_limiter, 'wait', lambda: None)
    cache = {}
    with failure_scope(cfg):
        assert not process_tv_branch(src, cfg, cache, None, 'Show', '2020', 42,
                                     {'seasons': [{'season_number': 2}]},
                                     {'season': 2, 'episode': 1, 'explicit_season': 2}, 80)
    entry = cache[str(src.resolve())]
    assert entry['failure_category'] == 'transient'
    assert entry['retry_after'] is not None
    assert src.read_bytes() == b'synthetic'
    assert not list((tmp_path / 'tv').rglob('*.nfo'))
    assert not list((tmp_path / 'tv').rglob('*.mkv'))


def test_ai_cannot_change_explicit_season(tmp_path, config_file, monkeypatch):
    from core import config_manager, tmdb_client, ai_client
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show S02E01.mkv'
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], download_images=False)
    cfg['subtitle']['enabled'] = False
    cfg['ai_parser']['enabled'] = True
    cfg['ai_parser']['api_key'] = 'synthetic'
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: [{'episode_number': 2}])
    monkeypatch.setattr(ai_client, 'call_ai_api', lambda *a, **k: '{"corrected_season": 0, "corrected_episode": 1}')
    cache = {}
    assert not process_tv_branch(src, cfg, cache, None, 'Show', '2020', 42,
                                 {'seasons': [{'season_number': 0}, {'season_number': 2}]},
                                 {'season': 2, 'episode': 1, 'explicit_season': 2, '_parser': 'anitopy'}, 80)
    assert cache[str(src.resolve())]['media_type'] != 'tv'
    assert not list((tmp_path / 'tv').rglob('*.mkv'))


def test_unique_cross_season_requires_complete_regular_seasons(monkeypatch):
    from core import tmdb_client, search_enhancer
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: {'seasons': [{'season_number': 1}, {'season_number': 2}]})
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda _id, season, *a, **k: [{'episode_number': season}])
    assert search_enhancer.find_episode_across_seasons(42, 2, 'synthetic')[0] == 2
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda _id, season, *a, **k: [] if season == 1 else [{'episode_number': 2}])
    assert search_enhancer.find_episode_across_seasons(42, 2, 'synthetic') == (None, None)
