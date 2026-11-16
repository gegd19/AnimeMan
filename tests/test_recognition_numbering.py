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
