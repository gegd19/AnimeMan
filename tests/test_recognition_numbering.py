"""R03: preserve explicit season and episode evidence."""
from pathlib import Path
import pytest


def test_chinese_season_episode_not_misclassified(tmp_path, config_file, monkeypatch):
    from core import config_manager, parser_manager, ai_client
    src = tmp_path / '示例' / '示例 第二季 第01集.mkv'
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)])
    cfg['ai_parser'].update(enabled=True, api_key='synthetic')
    monkeypatch.setattr(ai_client, 'parse_filename_with_ai', lambda *a, **k: pytest.fail('explicit season and episode should use local evidence'))
    result = parser_manager.parse_filename(src, cfg)
    assert (result['media_type'], result['season'], result['episode']) == ('tv', 2, 1)
    assert result['total_episode'] is None


@pytest.mark.parametrize('filename,season,episode', [
    ('Show S00E02.mkv', 0, 2), ('Show S01E123.mkv', 1, 123),
    ('Show 第十一季 第123集.mkv', 11, 123),
])
def test_valid_numbering_preserved(filename, season, episode):
    from core.parser_regex import parse_with_regex
    result = parse_with_regex(filename)
    assert (result['season'], result['episode']) == (season, episode)


@pytest.mark.parametrize('filename', ['Example - 12.5.mkv', 'Example - 01-02.mkv', 'Example S01E01-E02.mkv', 'Example [12.5].mkv',
                                      'Example - 12.125.mkv', 'Example [12.125].mkv', 'Example.S01E07.125.1080p.mkv', 'Example - 12.125v2.mkv',
                                      'Example - 12.5v2.mkv', 'Example E07.5.mkv', 'Example.S01E07.5.1080p.mkv'])
@pytest.mark.parametrize('ai_enabled', [False, True])
def test_ambiguous_numbering_never_reaches_tmdb(tmp_path, config_file, monkeypatch, filename, ai_enabled):
    from core import config_manager, parser_manager, processor_core
    src = tmp_path / 'Example' / filename
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg.update(source_folders=[str(src.parent)], dry_run=False)
    cfg['ai_parser'].update(enabled=ai_enabled, api_key='synthetic')
    monkeypatch.setattr(processor_core, 'try_folder_ai_batch', lambda *a, **k: pytest.fail('ambiguous input must not invoke AI batch'))
    monkeypatch.setattr(processor_core, 'search_tmdb_with_fallback', lambda *a, **k: pytest.fail('ambiguous input must not search TMDB'))
    result = parser_manager.parse_filename(src, cfg)
    assert result.get('reason_code') == 'unsupported_episode_numbering'
    cache = {}
    assert not processor_core.process_video(src, cfg, cache)
    assert cache[str(src.resolve())]['media_type'] == 'failed'
    assert src.read_bytes() == b'synthetic'
    assert not list((tmp_path / 'tv').rglob('*.mkv'))


@pytest.mark.parametrize('filename', ['Show - 01v2.mkv', 'Show S01E02 [1080p].mkv', 'Show (2020) S01E02.mkv',
                                      # dot-separated scene names: the resolution after the episode is not a decimal episode
                                      'Show.S01E02.1080p.BluRay.Remux.FLAC.2.0.H.264-Grp.mkv', 'Show.S01E01.2160p.WEB-DL.mkv',
                                      'Show.S01E02.720p.HDTV.x264.mkv', 'Show.S01E01.480p.mkv', 'Show.S01E02.4K.HDR.mkv', 'Show.S01E01.10bit.mkv'])
def test_unambiguous_episode_not_blocked(tmp_path, config_file, filename):
    from core import config_manager, parser_manager
    src = tmp_path / 'Show' / filename
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg['source_folders'] = [str(src.parent)]
    result = parser_manager.parse_filename(src, cfg)
    assert result.get('reason_code') != 'unsupported_episode_numbering'
    assert result.get('episode') in (1, 2)


def test_numeric_file_uses_bounded_series_parent(tmp_path, config_file):
    from core import config_manager, parser_manager
    root = tmp_path / 'library'; src = root / 'Example' / 'Season 02' / '01.mkv'
    src.parent.mkdir(parents=True); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file); cfg['source_folders'] = [str(root)]
    result = parser_manager.parse_filename(src, cfg)
    assert (result['title'], result['season'], result['episode']) == ('Example', 2, 1)


def test_numeric_file_does_not_use_ancestor_outside_source(tmp_path, config_file):
    from core import config_manager, parser_manager
    root = tmp_path / 'SecretSeries' / 'Season 02'; src = root / '01.mkv'
    src.parent.mkdir(parents=True); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file); cfg['source_folders'] = [str(root)]
    result = parser_manager.parse_filename(src, cfg)
    assert result['media_type'] == 'unknown'
    assert result.get('reason_code') == 'missing_series_title'


def test_conflicting_file_and_directory_seasons_require_review(tmp_path, config_file, monkeypatch):
    from core import config_manager, parser_manager, processor_core
    root = tmp_path / 'Example'; src = root / 'Season 02' / 'Example S01E01.mkv'
    src.parent.mkdir(parents=True); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file); cfg['source_folders'] = [str(root)]
    result = parser_manager.parse_filename(src, cfg)
    assert result.get('reason_code') == 'conflicting_season_evidence'
    monkeypatch.setattr(processor_core, 'search_tmdb_with_fallback', lambda *a, **k: pytest.fail('must not search on conflicting season evidence'))
    cache = {}
    assert not processor_core.process_video(src, cfg, cache)
    assert cache[str(src.resolve())]['media_type'] == 'failed'


def test_numeric_bdrip_folder_preserves_zero_season(tmp_path, config_file):
    from core import config_manager, parser_manager
    root = tmp_path / 'Example'; src = root / 'Season 00' / 'BDRip' / '02.mkv'
    src.parent.mkdir(parents=True); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file); cfg['source_folders'] = [str(root)]
    result = parser_manager.parse_filename(src, cfg)
    assert (result['title'], result['season'], result['episode']) == ('Example', 0, 2)


def test_conflicting_directory_seasons_require_review(tmp_path, config_file):
    from core import config_manager, parser_manager
    root = tmp_path / 'Example'; src = root / 'Season 01' / 'Season 02' / '01.mkv'
    src.parent.mkdir(parents=True); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file); cfg['source_folders'] = [str(root)]
    assert parser_manager.parse_filename(src, cfg).get('reason_code') == 'conflicting_season_evidence'
