"""A release season TMDB folds into one long season is mapped only through TMDB's own episode groups."""
from pathlib import Path

from core import processor_tv, tmdb_client


def group(*parts, type=6, name='Seasons'):
    """parts: (name, [(tmdb season, tmdb episode), ...]) in order"""
    return {'id': 'g' + name.replace(' ', ''), 'type': type, 'name': name,
            'groups': [{'name': n, 'order': i, 'episodes': [{'order': j, 'season_number': s, 'episode_number': e}
                                                          for j, (s, e) in enumerate(eps)]} for i, (n, eps) in enumerate(parts)]}


def use(monkeypatch, *groups):
    monkeypatch.setattr(tmdb_client, 'get_tv_episode_groups', lambda *a, **k: [{'id': g['id'], 'type': g['type'], 'name': g['name']} for g in groups])
    monkeypatch.setattr(tmdb_client, 'get_episode_group', lambda gid, *a, **k: next((g for g in groups if g['id'] == gid), None))


def s1(start, count):
    return [(1, start + i) for i in range(count)]


def test_named_seasons_map_to_the_long_tmdb_season(monkeypatch):
    use(monkeypatch, group(('Specials', [(0, 1)]), ('Season 1', s1(1, 25)), ('Season 2 Part 1', s1(26, 13)), ('Season 2 Part 2', s1(39, 12)),
                           ('Season 3', s1(51, 16)), ('Season 4', s1(67, 12))))
    assert processor_tv.season_from_episode_groups(1, 4, 3, 'k', 'zh-CN')[:2] == (1, 69)
    assert processor_tv.season_from_episode_groups(1, 2, 14, 'k', 'zh-CN')[:2] == (1, 39)   # a season split into two parts
    assert processor_tv.season_from_episode_groups(1, 4, 13, 'k', 'zh-CN') is None          # past the end of that season
    assert processor_tv.season_from_episode_groups(1, 5, 1, 'k', 'zh-CN') is None


def test_groups_that_are_arcs_or_disagree_are_not_used(monkeypatch):
    use(monkeypatch, group(('Arc 1', s1(1, 10)), ('Arc 4', s1(11, 10))))
    assert processor_tv.season_from_episode_groups(1, 4, 1, 'k', 'zh-CN') is None
    use(monkeypatch, group(('Season 1', s1(1, 12)), ('Season 3', s1(13, 12))))   # a gap: not an ordered list of seasons
    assert processor_tv.season_from_episode_groups(1, 3, 1, 'k', 'zh-CN') is None
    use(monkeypatch, group(('Season 1', s1(1, 12)), ('Season 2', s1(13, 12)), name='A'),
        group(('Season 1', s1(1, 13)), ('Season 2', s1(14, 12)), name='B'))
    assert processor_tv.season_from_episode_groups(1, 2, 1, 'k', 'zh-CN') is None
    use(monkeypatch, group(('第一季', s1(1, 12)), ('第二季', s1(13, 12)), name='A'), group(('S1', s1(1, 12)), ('S2', s1(13, 12)), name='B'))
    assert processor_tv.season_from_episode_groups(1, 2, 1, 'k', 'zh-CN')[:2] == (1, 13)   # two groups that agree
    use(monkeypatch, group(('Season 1', s1(1, 12)), ('Season 2', s1(13, 12)), type=5))   # story arcs are not seasons
    assert processor_tv.season_from_episode_groups(1, 2, 1, 'k', 'zh-CN') is None


def test_special_marker():
    assert not processor_tv._SPECIAL_MARK.search('Ultraman Taiga Tri-Squad Voice Drama - 20')
    assert all(processor_tv._SPECIAL_MARK.search(t) for t in ('Show OVA 2', 'Show - SP01', 'Show S00E03', '某剧 特别篇'))
    assert not any(processor_tv._SPECIAL_MARK.search(t) for t in ('Spy x Family - 03', 'Lisp - 01', 'Show S01E03'))


import pytest
from core import config_manager


@pytest.fixture
def branch(config_file, tmp_path, monkeypatch):
    def make(name, seasons, episodes_by_season):
        src = tmp_path / 'source' / name
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(b'temporary-video')
        cfg = config_manager.load_config(config_file)
        cfg.update(source_folders=[str(src.parent)], tv_target_folder=str(tmp_path / 'tv'), dry_run=True, download_images=False)
        cfg['subtitle'] = {'enabled': False}
        details = {'title': 'Example', 'name': 'Example', 'overview': '', 'seasons': [{'season_number': n, 'episode_count': c} for n, c in seasons]}
        monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k: details)
        monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes',
                            lambda tv, sn, *a, **k: [{'episode_number': e, 'name': f'S{sn}E{e}'} for e in episodes_by_season.get(sn, [])])
        return src, cfg, details
    return make


def run(src, cfg, details, info):
    cache, logs = {}, []
    real_save = processor_tv.save_failed_cache
    processor_tv.save_failed_cache = lambda s, reason, *a, **k: logs.append('failed: ' + reason)
    try:
        ok = processor_tv.process_tv_branch(src, cfg, cache, lambda *a: logs.append(str(a)), 'Example', '', 1, details, info, 90)
    finally:
        processor_tv.save_failed_cache = real_save
    return ok, cache, ' '.join(logs)


def test_release_season_missing_on_tmdb_is_filed_through_episode_groups(branch, monkeypatch):
    src, cfg, details = branch('Example S04E03.mkv', [(1, 78)], {1: list(range(1, 79))})
    use(monkeypatch, group(('Season 1', s1(1, 25)), ('Season 2', s1(26, 25)), ('Season 3', s1(51, 16)), ('Season 4', s1(67, 12))))
    ok, cache, logs = run(src, cfg, details, {'season': 4, 'episode': 3})
    assert ok and 'S04E03 → S01E69' in logs
    use(monkeypatch)                                   # no groups: still sent to review, nothing guessed
    ok, cache, logs = run(src, cfg, details, {'season': 4, 'episode': 3})
    assert not ok and '无法获取季 4 的集列表' in logs


def test_a_special_only_the_ai_suggested_goes_to_review(branch):
    src, cfg, details = branch('Ultraman Taiga Tri-Squad Voice Drama - 20.mp4', [(0, 30), (1, 25)], {0: list(range(1, 31)), 1: list(range(1, 26))})
    ok, cache, logs = run(src, cfg, details, {'season': 0, 'episode': 20, '_from_ai': True})
    assert not ok and '特别篇' in logs
    src, cfg, details = branch('Example OVA - 02.mkv', [(0, 3), (1, 12)], {0: [1, 2, 3], 1: list(range(1, 13))})
    assert run(src, cfg, details, {'season': 0, 'episode': 2, '_from_ai': True})[0]


def english_titles(monkeypatch, titles):
    """titles: {(season, episode): English name}; other languages get placeholder names."""
    processor_tv._EPISODE_TITLE_CACHE.clear()
    def episodes(tv, season, api_key, language='zh-CN', *a, **k):
        numbers = sorted(e for s, e in titles if s == season)
        return [{'episode_number': e, 'name': titles[(season, e)] if language == 'en-US' else f'第{e}集'} for e in numbers]
    monkeypatch.setattr(tmdb_client, 'get_tv_season_episodes', episodes)


def test_episode_title_in_the_name_confirms_or_questions_the_episode(branch, monkeypatch):
    names = {(1, n): f'Ordinary Title Number {n}' for n in range(1, 13)}
    names[(1, 5)] = 'The Beginning of All Battles'
    src, cfg, details = branch('The.Drops.of.God.S01E05.The.Beginning.of.All.Battles.mkv', [(1, 12)], {})
    english_titles(monkeypatch, names)
    ok, cache, logs = run(src, cfg, details, {'season': 1, 'episode': 5, 'episode_title': 'The Beginning of All Battles'})
    assert ok and '集名与 TMDB 该集一致' in logs
    ok, cache, logs = run(src, cfg, details, {'season': 1, 'episode': 3, 'episode_title': 'The Beginning of All Battles'})
    assert not ok and '对应 TMDB 第 5 集' in logs and '与集号 3 不一致' in logs
    ok, cache, logs = run(src, cfg, details, {'season': 1, 'episode': 3, 'episode_title': 'Episode 3'})   # says nothing
    assert ok


def test_episode_title_finds_the_episode_when_tmdb_folds_the_season(branch, monkeypatch):
    names = {(1, n): f'Ordinary Title Number {n}' for n in range(1, 27)}
    names[(1, 14)] = 'Day-Tripping Down to Naniwa!'
    src, cfg, details = branch('My.Hero.Academia.Vigilantes.S02E01.Day-Tripping.Down.to.Naniwa.mkv', [(1, 26)], {})
    english_titles(monkeypatch, names)
    use(monkeypatch)                                              # no episode groups to go by
    ok, cache, logs = run(src, cfg, details, {'season': 2, 'episode': 1, 'episode_title': 'Day-Tripping Down to Naniwa'})
    assert ok and 'S01E14' in logs
    ok, cache, logs = run(src, cfg, details, {'season': 2, 'episode': 1, 'episode_title': 'A Title Nobody Has'})
    assert not ok and '无法获取季 2 的集列表' in logs
