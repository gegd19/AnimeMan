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


@pytest.mark.parametrize('filename', ['Example - 12.5.mkv', 'Example - 01-02.mkv', 'Example S01E01-E02.mkv', 'Example [12.5].mkv'])
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


@pytest.mark.parametrize('filename', ['Show - 01v2.mkv', 'Show S01E02 [1080p].mkv', 'Show (2020) S01E02.mkv'])
def test_unambiguous_episode_not_blocked(tmp_path, config_file, filename):
    from core import config_manager, parser_manager
    src = tmp_path / 'Show' / filename
    src.parent.mkdir(); src.write_bytes(b'synthetic')
    cfg = config_manager.load_config(config_file)
    cfg['source_folders'] = [str(src.parent)]
    result = parser_manager.parse_filename(src, cfg)
    assert result.get('reason_code') != 'unsupported_episode_numbering'
    assert result.get('episode') in (1, 2)
