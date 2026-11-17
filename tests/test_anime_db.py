"""Offline anime databases: a release name is found in an anime database, then translated to TMDB."""
import json
from pathlib import Path

import pytest
import requests

from core import anime_db


MANAMI = {"data": [
    {"sources": ["https://anilist.co/anime/21355", "https://myanimelist.net/anime/31240", "https://anidb.net/anime/11370"],
     "title": "Re:Zero kara Hajimeru Isekai Seikatsu", "type": "TV", "episodes": 25, "animeSeason": {"year": 2016},
     "duration": {"value": 1500, "unit": "SECONDS"}, "synonyms": ["Re:ZERO -Starting Life in Another World-"]},
    {"sources": ["https://anilist.co/anime/189046", "https://myanimelist.net/anime/61316", "https://anidb.net/anime/19242"],
     "title": "Re:Zero kara Hajimeru Isekai Seikatsu 4th Season", "type": "TV", "episodes": 12, "animeSeason": {"year": 2026},
     "synonyms": ["Re:ZERO -Starting Life in Another World- Season 4"]},
    {"sources": ["https://anilist.co/anime/8277"], "title": "Baka to Test to Shoukanjuu Ni!", "type": "TV", "episodes": 13,
     "animeSeason": {"year": 2011}, "synonyms": []},
    {"sources": ["https://anilist.co/anime/100"], "title": "Hentatsu", "type": "TV", "episodes": 12, "animeSeason": {"year": 2018}, "synonyms": []},
    {"sources": ["https://anilist.co/anime/101"], "title": "Hentatsu (TV)", "type": "TV", "episodes": 12, "animeSeason": {"year": 2020},
     "synonyms": ["Hentatsu"]},
    {"sources": ["https://anilist.co/anime/200"], "title": "Twin Show", "type": "TV", "episodes": 12, "animeSeason": {"year": 2019},
     "duration": {"value": 240, "unit": "SECONDS"}, "synonyms": []},
    {"sources": ["https://anilist.co/anime/201"], "title": "Twin Show", "type": "TV", "episodes": 12, "animeSeason": {"year": 2019},
     "duration": {"value": 1440, "unit": "SECONDS"}, "synonyms": []},
    {"sources": ["https://anilist.co/anime/300"], "title": "Movie Only", "type": "MOVIE", "episodes": 1, "synonyms": []},
    {"sources": ["https://anilist.co/anime/400"], "title": "Room Camp", "type": "TV", "episodes": 12, "synonyms": ["Heya Camp"]},
]}
BANGUMI = {"items": [
    {"title": "左ききのエレン", "titleTranslate": {"zh-Hans": ["左撇子艾伦"], "en": ["Eren the Southpaw"]}, "type": "tv",
     "begin": "2026-04-07T15:00:00.000Z", "sites": [{"site": "bangumi", "id": "409468"}, {"site": "tmdb", "id": "tv/305567"}]},
    {"title": "【推しの子】(第3期)", "titleTranslate": {"zh-Hans": ["【我推的孩子】 第三季"]}, "type": "tv", "begin": "2026-01-14T14:00:00.000Z",
     "sites": [{"site": "bangumi", "id": "517057"}, {"site": "tmdb", "id": "tv/203737/season/1/episode/25"}]},
]}
BRIDGE = {
    "$meta": {"schema_version": "3"},
    "anilist:21355": {"tmdb_show:65942:s1": {"1-25": "1-25"}},
    "anilist:189046": {"tmdb_show:65942:s1": {"1-12": "67-78"}},
    "anidb:19242:R": {"tmdb_show:65942:s1": {"1-12": "67-78"}},
    "anilist:8277": {"tmdb_show:56343:s2": {}},
    "anilist:100": {"tmdb_show:97407:s1": {}},
    "anilist:101": {"tmdb_show:97407:s2": {}},
    "anilist:200": {"tmdb_show:500:s1": {}},
    "anilist:201": {"tmdb_show:501:s1": {}},
    "anilist:300": {"tmdb_movie:9": {}},
    "anilist:400": {"tmdb_show:95623:s1": {}},
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    folder = tmp_path / "animedb"
    folder.mkdir()
    files = {}
    for name, data in (("manami", MANAMI), ("bangumi", BANGUMI), ("anibridge", BRIDGE)):
        files[name] = folder / f"{name}.json"
        files[name].write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("ANIME_DB_PATH", str(folder))
    anime_db.build_index(files, anime_db.index_path())
    anime_db.reset_run()
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no download while recognising"))
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("no web search unless enabled"))
    return folder


def resolve(tmp_path, name, title, episode, folder="dl", duration=None, config=None):
    src = tmp_path / folder / name
    src.parent.mkdir(parents=True, exist_ok=True)
    info = {"media_type": "tv", "title": title, "season": 1, "episode": episode}
    return anime_db.resolve(src, info, config or {}, duration=duration)


def test_a_later_season_named_in_the_file_is_translated_to_tmdbs_long_season(db, tmp_path):
    result = resolve(tmp_path, "Re.ZERO.Starting.Life.in.Another.World.S04E03.mkv", "Re ZERO Starting Life in Another World", 3)
    assert result["status"] == "match" and (result["tmdb_id"], result["season"], result["episode"]) == (65942, 1, 69)
    assert "anibridge" in result["evidence"]


def test_a_stated_later_season_never_falls_back_to_the_first_season_entry(db, tmp_path):
    # Only season 1 is known under this name; S03E02 must not become season 1 episode 2.
    assert resolve(tmp_path, "Re.Zero.kara.Hajimeru.Isekai.Seikatsu.S03E02.mkv", "Re Zero kara Hajimeru Isekai Seikatsu", 2) is None


def test_romanisation_of_long_vowels_does_not_matter(db, tmp_path):
    result = resolve(tmp_path, "[Commie] Baka to Test to Shokanju Ni - 09.mkv", "Baka to Test to Shokanju Ni", 9)
    assert (result["tmdb_id"], result["season"], result["episode"]) == (56343, 2, 9)


def test_chinese_names_and_bangumi_cour_links(db, tmp_path):
    result = resolve(tmp_path, "[喵萌奶茶屋][左撇子艾伦][03][1080p].mp4", "左撇子艾伦", 3)
    assert (result["tmdb_id"], result["season"], result["episode"]) == (305567, 1, 3)
    result = resolve(tmp_path, "[字幕组][我推的孩子 第三季][09].mkv", "【我推的孩子】 第三季", 9)
    assert (result["tmdb_id"], result["season"], result["episode"]) == (203737, 1, 33)


def test_two_works_with_one_name_need_the_year_or_a_person(db, tmp_path):
    ambiguous = resolve(tmp_path, "[Group] Hentatsu - 04.mkv", "Hentatsu", 4)
    assert ambiguous["status"] == "ambiguous" and "Hentatsu" in ambiguous["message"]
    dated = resolve(tmp_path, "[Group] Hentatsu (2020) - 04.mkv", "Hentatsu", 4, folder="dated")
    assert (dated["tmdb_id"], dated["season"], dated["episode"]) == (97407, 2, 4)
    assert "年份 2020" in dated["evidence"]


def test_the_video_length_separates_a_short_from_a_regular_series(db, tmp_path):
    assert resolve(tmp_path, "Twin Show - 05.mkv", "Twin Show", 5)["status"] == "ambiguous"
    short = resolve(tmp_path, "Twin Show - 05.mkv", "Twin Show", 5, folder="short", duration=lambda: 4.0)
    assert short["tmdb_id"] == 500 and "时长" in short["evidence"]


def test_movies_unknown_names_and_missing_data_say_nothing(db, tmp_path, monkeypatch):
    assert resolve(tmp_path, "Movie Only - 01.mkv", "Movie Only", 1) is None
    assert resolve(tmp_path, "Nothing Like It - 01.mkv", "Nothing Like It", 1) is None
    src = tmp_path / "x" / "Re ZERO - 01.mkv"
    assert anime_db.resolve(src, {"media_type": "tv", "title": "Re:ZERO -Starting Life in Another World-", "episode": 1},
                            {"anime_db": {"enabled": False}}) is None
    monkeypatch.setenv("ANIME_DB_PATH", str(tmp_path / "empty"))
    assert anime_db.resolve(src, {"media_type": "tv", "title": "Re:ZERO -Starting Life in Another World-", "episode": 1}, {}) is None


def test_one_folder_cannot_hold_one_name_for_two_works(db, tmp_path, monkeypatch):
    first = resolve(tmp_path, "Twin Show - 05.mkv", "Twin Show", 5, folder="mixed", duration=lambda: 4.0)
    second = resolve(tmp_path, "Twin Show - 06.mkv", "Twin Show", 6, folder="mixed", duration=lambda: 24.0)
    assert first["status"] == "match" and second["status"] == "conflict"


def test_episode_range_targets_with_gaps_and_ratios():
    assert anime_db._target_episode(0, "1-6,8-13") == 1
    assert anime_db._target_episode(6, "1-6,8-13") == 8
    assert anime_db._target_episode(3, "14-") == 17
    assert anime_db._target_episode(0, "1-|2") is None
    assert anime_db._in_range(14, "14-") == 0 and anime_db._in_range(13, "14-") is None and anime_db._in_range(5, "1-4") is None
    assert anime_db.ids_from_urls(["https://bangumi.tv/subject/409468", "https://myanimelist.net/anime/1/x"]) == ["bgm:409468", "mal:1"]


def web_config(**search):
    return {"ai_parser": {"provider": "deepseek", "api_key": "sk-test", "base_url": "https://api.deepseek.com"},
            "anime_db": {"web_search": {"enabled": True, "max_per_run": 1, **search}}}


def test_web_search_finds_the_database_page_only_when_the_result_shows_the_title(db, tmp_path, monkeypatch):
    calls = []

    class Reply:
        def __init__(self, results): self.results = results
        def raise_for_status(self): pass
        def json(self): return {"results": self.results}

    def post(url, json=None, **kwargs):
        calls.append(json["query"])
        return Reply([{"url": "https://www.bangumi.tv/subject/409468", "title": "左ききのエレン", "snippet": "别名: Hidarikiki no Eren"},
                      {"url": "https://anilist.co/anime/200", "title": "Unrelated", "snippet": "nothing here"}])
    monkeypatch.setattr(requests, "post", post)
    src = tmp_path / "web" / "[SubsPlease] Hidarikiki no Eren - 03.mkv"
    info = {"media_type": "tv", "title": "Hidarikiki no Eren", "episode": 3}
    result = anime_db.resolve(src, info, web_config())
    assert (result["tmdb_id"], result["episode"]) == (305567, 3) and len(calls) == 1
    assert "site:bangumi.tv" in calls[0] and "sk-test" not in calls[0]
    anime_db.resolve(src, info, web_config())                       # the same title is not searched twice
    assert len(calls) == 1
    other = tmp_path / "web" / "Another Unknown Title - 01.mkv"
    assert anime_db.resolve(other, {"media_type": "tv", "title": "Another Unknown Title", "episode": 1}, web_config()) is None
    assert len(calls) == 1                                          # the per-run budget is spent
    anime_db.reset_run()
    no_key = web_config(); no_key["ai_parser"]["api_key"] = ""
    assert anime_db.resolve(other, {"media_type": "tv", "title": "Another Unknown Title", "episode": 1}, no_key) is None
    assert len(calls) == 1


def test_update_downloads_builds_and_keeps_old_data_when_a_mirror_fails(tmp_path, monkeypatch):
    folder = tmp_path / "fresh"
    monkeypatch.setenv("ANIME_DB_PATH", str(folder))
    payload = {"manami": MANAMI, "anibridge": BRIDGE, "bangumi": BANGUMI}
    seen = []

    class Stream:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, size): yield self.body

    def get(url, **kwargs):
        seen.append(url)
        if "jsdelivr" in url:
            raise requests.ConnectionError("blocked")
        name = "manami" if "manami" in url else "anibridge" if "anibridge" in url else "bangumi"
        return Stream(json.dumps(payload[name]).encode())
    monkeypatch.setattr(requests, "get", get)
    report = anime_db.update({})
    assert report["counts"]["works"] >= 8 and anime_db.status()["available"]
    assert any("unpkg" in url for url in seen)                       # the next bangumi-data mirror was used
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline")))
    report = anime_db.update({})
    assert all(source["kept_previous"] for source in report["sources"].values())
    assert anime_db.index_path().is_file()


def test_weekly_refresh_only_after_a_first_download(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIME_DB_PATH", str(tmp_path / "none"))
    monkeypatch.setattr(anime_db, "update_in_background", lambda *a, **k: pytest.fail("never download unasked"))
    assert anime_db.maybe_refresh({}) is False


def test_processor_uses_the_database_identity_and_refuses_a_disagreeing_search(tmp_path, config_file, monkeypatch):
    from core import config_manager, processor_core, tmdb_client, video_info
    root = tmp_path / "source"; folder = root / "anime"; folder.mkdir(parents=True)
    src = folder / "Hidarikiki no Eren S01E03.mkv"; src.write_bytes(b"synthetic")
    cfg = config_manager.load_config(config_file); cfg.update(source_folders=[str(root)])
    match = {"status": "match", "tmdb_id": 305567, "season": 1, "episode": 3, "evidence": "离线番剧库：测试", "names": "左ききのエレン"}
    monkeypatch.setattr(anime_db, "resolve", lambda *a, **k: dict(match))
    monkeypatch.setattr(video_info, "get_video_duration", lambda *a: None)
    detail = {"id": 305567, "name": "左撇子艾伦", "first_air_date": "2026-04-07", "seasons": [{"season_number": 1}]}
    monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: detail)
    monkeypatch.setattr(tmdb_client, "search_tmdb_multi", lambda *a, **k: [])
    observed = []
    monkeypatch.setattr(processor_core, "process_tv_branch", lambda *a: (observed.append(a) or True))
    assert processor_core.process_video(src, cfg, {})
    final = observed[0][-2]
    assert observed[0][6] == 305567 and (final["season"], final["episode"]) == (1, 3)
    assert "离线番剧库：测试" in final["_recognition_score"]["evidence"]
    # The ordinary search finds a different work: a person decides.
    other = {"id": 97418, "name": "Hidarikiki no Eren", "original_name": "Hidarikiki no Eren", "first_air_date": "2019-10-20",
             "seasons": [{"season_number": 1}]}
    monkeypatch.setattr(tmdb_client, "search_tmdb_multi", lambda *a, **k: [other])
    monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: other if 97418 in (*a, k.get("tmdb_id")) else detail)
    cache = {}
    observed.clear()
    processor_core._folder_tmdb_cache.clear()
    assert not processor_core.process_video(src, cfg, cache)
    reasons = json.dumps(cache, ensure_ascii=False)
    assert not observed and "离线番剧库" in reasons and "97418" in reasons


def test_status_and_update_api(client, monkeypatch):
    auth = ("test-user", "test-pass")
    assert client.get("/api/anime_db/status").status_code == 401
    state = client.get("/api/anime_db/status", auth=auth).get_json()
    assert state["available"] is False and "bangumi" in state["sources"]
    started = []
    monkeypatch.setattr(anime_db, "update_in_background", lambda config, log=None: started.append(config) or True)
    response = client.post("/api/anime_db/update", auth=auth)
    assert response.status_code == 200 and response.get_json()["status"] == "started" and started
    assert client.post("/api/anime_db/update").status_code == 401


def test_settings_are_validated():
    from core.validation import validate_config, ValidationError
    from core.config_manager import DEFAULT_CONFIG
    import copy
    good = copy.deepcopy(DEFAULT_CONFIG)
    good["anime_db"] = {"enabled": True, "update_days": 7, "urls": {"bangumi": "https://mirror.example/data.json"},
                        "web_search": {"enabled": False, "max_per_run": 30}}
    validate_config(good)
    for bad in ({"update_days": -1}, {"urls": {"other": "https://x"}}, {"urls": {"manami": "file:///etc/passwd"}},
                {"web_search": {"max_per_run": "many"}}, {"enabled": "yes"}):
        broken = copy.deepcopy(good); broken["anime_db"] = {**good["anime_db"], **bad}
        with pytest.raises(ValidationError):
            validate_config(broken)


def test_a_stated_year_rules_out_an_older_series_of_the_same_name(db, tmp_path):
    # Only the 2018 and 2020 "Hentatsu" entries exist; a file from 1995 matches neither.
    assert resolve(tmp_path, "[Group] Hentatsu (1995) - 04.mkv", "Hentatsu", 4, folder="old") is None
    single = resolve(tmp_path, "[Group] Baka to Test to Shokanju Ni (2011) - 09.mkv", "Baka to Test to Shokanju Ni", 9, folder="y")
    assert single["tmdb_id"] == 56343
    assert resolve(tmp_path, "[Group] Baka to Test to Shokanju Ni (2001) - 09.mkv", "Baka to Test to Shokanju Ni", 9, folder="z") is None


def test_a_search_result_the_databases_know_by_another_name(db):
    assert anime_db.known_under_other_name(95623, ["Yuru Camp"], ["Room Camp"])
    assert not anime_db.known_under_other_name(95623, ["Heya Camp"], ["Room Camp"])
    assert not anime_db.known_under_other_name(95623, ["Yuru Camp"], ["Unverified Name"])
    assert not anime_db.known_under_other_name(97418, ["Hidarikiki no Eren"], ["Another Name"])


def test_processor_prefers_the_database_when_the_search_found_another_known_anime(tmp_path, config_file, monkeypatch):
    from core import config_manager, processor_core, tmdb_client, video_info
    folder = tmp_path / "source" / "anime"; folder.mkdir(parents=True)
    src = folder / "Yuru Camp S02E11.mkv"; src.write_bytes(b"synthetic")
    cfg = config_manager.load_config(config_file); cfg.update(source_folders=[str(tmp_path / "source")])
    monkeypatch.setattr(anime_db, "resolve", lambda *a, **k: {"status": "match", "tmdb_id": 76075, "season": 2, "episode": 11,
                                                              "evidence": "离线番剧库：测试", "names": "Yuru Camp Season 2"})
    monkeypatch.setattr(video_info, "get_video_duration", lambda *a: None)
    camp = {"id": 76075, "name": "摇曳露营△", "first_air_date": "2018-01-04", "seasons": [{"season_number": 1}, {"season_number": 2}]}
    spin = {"id": 95623, "name": "Yuru Camp", "original_name": "Yuru Camp", "first_air_date": "2020-01-06", "seasons": [{"season_number": 1}]}
    monkeypatch.setattr(tmdb_client, "search_tmdb_multi", lambda *a, **k: [spin])
    spin_details = dict(spin, name="Room Camp", original_name="Heya Camp")
    monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: spin_details if 95623 in (*a, k.get("tmdb_id")) else camp)
    observed = []
    monkeypatch.setattr(processor_core, "process_tv_branch", lambda *a: (observed.append(a) or True))
    monkeypatch.setattr(anime_db, "known_under_other_name", lambda tmdb_id, titles, names: tmdb_id == 95623 and "Room Camp" in names)
    assert processor_core.process_video(src, cfg, {})
    assert observed[0][6] == 76075 and "另一部作品" in " ".join(observed[0][-2]["_recognition_score"]["evidence"])


def test_bilingual_fansub_titles_are_looked_up_by_each_name(db, tmp_path):
    assert anime_db.bilingual_parts("摇曳露营△ Yuru Camp△") == ["摇曳露营△", "Yuru Camp△"]
    assert anime_db.bilingual_parts("Hentatsu") == []
    result = resolve(tmp_path, "[Prejudice-Studio] 左撇子艾伦 Hidarikiki no Eren - 03 [1080P].mp4", "左撇子艾伦 Hidarikiki no Eren", 3, folder="bi")
    assert (result["tmdb_id"], result["season"], result["episode"]) == (305567, 1, 3)


def test_the_episode_title_settles_a_disagreement_with_the_search(tmp_path, config_file, monkeypatch):
    from core import config_manager, processor_core, processor_tv, tmdb_client, video_info
    folder = tmp_path / "source" / "anime"; folder.mkdir(parents=True)
    src = folder / "Yuru Camp S02E11.mkv"; src.write_bytes(b"synthetic")
    cfg = config_manager.load_config(config_file); cfg.update(source_folders=[str(tmp_path / "source")])
    monkeypatch.setattr(anime_db, "resolve", lambda *a, **k: {"status": "match", "tmdb_id": 76075, "season": 2, "episode": 11,
                                                              "evidence": "离线番剧库：测试", "names": "Yuru Camp Season 2"})
    monkeypatch.setattr(anime_db, "known_under_other_name", lambda *a: False)    # e.g. a live-action series
    monkeypatch.setattr(video_info, "get_video_duration", lambda *a: None)
    camp = {"id": 76075, "name": "摇曳露营△", "first_air_date": "2018-01-04", "seasons": [{"season_number": 2}]}
    drama = {"id": 95623, "name": "Yuru Camp", "original_name": "Yuru Camp", "first_air_date": "2020-01-10", "seasons": [{"season_number": 1}]}
    monkeypatch.setattr(tmdb_client, "search_tmdb_multi", lambda *a, **k: [drama])
    monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: drama if 95623 in (*a, k.get("tmdb_id")) else camp)
    observed = []
    monkeypatch.setattr(processor_core, "process_tv_branch", lambda *a: (observed.append(a) or True))
    monkeypatch.setattr(processor_core, "parse_filename_info", lambda *a, **k: {
        "media_type": "tv", "title": "Yuru Camp", "season": 2, "episode": 11, "episode_title": "Izu Camping!! On the Way", "_parser": "regex"})
    monkeypatch.setattr(processor_tv, "episodes_named", lambda key, tmdb_id, seasons, *a: [(2, 11)] if tmdb_id == 76075 else [])
    assert processor_core.process_video(src, cfg, {})
    assert observed[0][6] == 76075
    monkeypatch.setattr(processor_tv, "episodes_named", lambda *a: [(2, 11), (2, 12)])
    observed.clear(); processor_core._folder_tmdb_cache.clear()
    assert not processor_core.process_video(src, cfg, {}) and not observed
    monkeypatch.setattr(processor_tv, "episodes_named", lambda *a: [])               # no title evidence: a person decides
    observed.clear(); processor_core._folder_tmdb_cache.clear()
    assert not processor_core.process_video(src, cfg, {}) and not observed
