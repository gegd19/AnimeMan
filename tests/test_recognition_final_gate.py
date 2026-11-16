"""R02: validate final confidence and identity before any media output."""
import pytest


def run_case(tmp_path, config_file, monkeypatch, start, *, dry_run=False, season=1, episode=1, tmdb_id=42, title='Show', corrected=True):
    from core import config_manager, tmdb_client
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show S01E01.mkv'
    src.parent.mkdir(exist_ok=True)
    src.write_bytes(b'synthetic')
    config = config_manager.load_config(config_file)
    config.update(source_folders=[str(src.parent)], dry_run=dry_run, download_images=False)
    config['subtitle']['enabled'] = False
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: [{'episode_number': 1, 'name': 'Example'}])
    details = {'seasons': [{'season_number': 1}]}
    info = {'season': season, 'episode': episode, 'explicit_season': season}
    if corrected:
        info.update(corrected_season=1, corrected_episode=1)
    cache, messages = {}, []
    result = process_tv_branch(src, config, cache, lambda *args: messages.append(args[-2]), title, '2020', tmdb_id, details, info, start)
    assert src.read_bytes() == b'synthetic'
    return result, cache, messages, src


@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('start,expected', [(64, False), (65, True)])
def test_final_confidence_boundaries(tmp_path, config_file, monkeypatch, start, expected, dry_run):
    result, cache, messages, src = run_case(tmp_path, config_file, monkeypatch, start, dry_run=dry_run)
    assert result is expected
    if not expected:
        assert not list((tmp_path / 'tv').rglob('*.mkv'))
        assert not list((tmp_path / 'tv').rglob('*.nfo'))
        if not dry_run:
            entry = cache[str(src.resolve())]
            assert entry['media_type'] == 'failed'
            assert '59' in entry['failed_reason']
            assert '最终' in entry['failed_reason']
        else:
            assert not cache


@pytest.mark.parametrize('field,value', [('season', None), ('episode', None), ('tmdb_id', None), ('tmdb_id', True), ('title', '')])
def test_missing_identity_cannot_be_rescued_by_score(tmp_path, config_file, monkeypatch, field, value):
    result, cache, messages, src = run_case(tmp_path, config_file, monkeypatch, 95, corrected=False, **{field:value})
    assert not result
    assert cache.get(str(src.resolve()), {}).get('media_type') != 'tv'
    assert not list((tmp_path / 'tv').rglob('*.mkv'))
    assert not list((tmp_path / 'tv').rglob('*.nfo'))


def test_ai_second_pass_below_threshold_does_not_write(tmp_path, config_file, monkeypatch):
    from core import config_manager, tmdb_client, ai_client
    from core.processor_tv import process_tv_branch
    src = tmp_path / 'source' / 'Show S01E01.mkv'
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    config = config_manager.load_config(config_file)
    config.update(source_folders=[str(src.parent)], dry_run=False, download_images=False)
    config['subtitle']['enabled'] = False
    config['ai_parser'].update(enabled=True, api_key='synthetic')
    responses = iter([[{'episode_number': 2}], [{'episode_number': 1, 'name': 'Example'}]])
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', lambda *a, **k: next(responses))
    monkeypatch.setattr(ai_client, 'call_ai_api', lambda *a, **k: '{"corrected_season":1,"corrected_episode":1}')
    cache = {}
    assert not process_tv_branch(src, config, cache, None, 'Show', '2020', 42,
                                 {'seasons': [{'season_number': 1}]},
                                 {'season': 1, 'episode': 1, 'explicit_season': 1, '_parser': 'anitopy'}, 69)
    assert '最终' in cache[str(src.resolve())]['failed_reason']
    assert '59' in cache[str(src.resolve())]['failed_reason']
    assert src.read_bytes() == b'synthetic'
    assert not list((tmp_path / 'tv').rglob('*.mkv'))
    assert not list((tmp_path / 'tv').rglob('*.nfo'))
