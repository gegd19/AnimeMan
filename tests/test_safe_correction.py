"""T02 failure, collision, concurrency and shared-artifact regressions."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading

import pytest

from core import cache_manager, config_manager, file_linker, tmdb_client
from core.processor_movie import process_movie_branch
from core.processor_tv import process_tv_branch
from core.processor_manual import process_video_with_manual_correction

AUTH = ("test-user", "test-pass")


@pytest.fixture
def media(config_file, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    src = source / "input.mkv"
    src.write_bytes(b"original")
    config = config_manager.load_config(str(config_file))
    config.update(source_folders=[str(source)], download_images=False)
    config["subtitle"] = {"enabled": False}
    config_manager.save_config(config, str(config_file))
    details = {"title": "New", "name": "New", "seasons": [{"season_number": 1, "episode_count": 1}]}
    monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: details)
    monkeypatch.setattr(tmdb_client, "get_tv_season_episodes", lambda *a, **k: [{"episode_number": 1, "name": "Pilot"}])
    return src, config, details


def run_branch(kind, src, config, details, cache):
    if kind == "movie":
        return process_movie_branch(src, config, cache, None, "New", "", 1, details, 90)
    if kind == "tv":
        return process_tv_branch(src, config, cache, None, "New", "", 1, details, {"season": 1, "episode": 1}, 90)
    return process_video_with_manual_correction(src, config, cache, 1, kind.split("_")[1], 1, 1)


@pytest.mark.parametrize("kind", ["movie", "tv", "manual_movie", "manual_tv"])
def test_different_target_is_never_overwritten(kind, media):
    src, config, details = media
    is_movie = kind.endswith("movie")
    parent = Path(config["movie_target_folder"] if is_movie else config["tv_target_folder"]) / "New"
    if not is_movie:
        parent /= "Season 01"
    parent.mkdir(parents=True)
    target = parent / ("New.mkv" if is_movie else "New - S01E01 - Pilot.mkv")
    target.write_bytes(b"keep-existing-version")
    (parent / "custom.nfo").write_text("user metadata")
    cache = {}
    assert not run_branch(kind, src, config, details, cache)
    assert target.read_bytes() == b"keep-existing-version"
    assert (parent / "custom.nfo").read_text() == "user metadata"
    assert cache[str(src)]["error_code"] == "target_conflict"


@pytest.mark.parametrize("endpoint", ["/api/failed_cache/correct", "/api/processed/retry", "/api/processed_cache/retry"])
@pytest.mark.parametrize("failure", ["tmdb", "link", "nfo", "publish", "cache"])
def test_correction_failure_keeps_old_files_and_cache(endpoint, failure, media, client, monkeypatch):
    from core import nfo_writer, processor_core
    src, config, details = media
    old = Path(config["movie_target_folder"]) / "Old" / "Old.mkv"
    assert file_linker.create_link(src, old, "hard")
    nfo = old.parent / "movie.nfo"
    nfo.write_text("old metadata")
    entry = {"target": str(old), "source_path": str(src), "media_type": "movie", "tmdb_id": 9}
    cache_manager.save_cache({str(src): entry})
    original = Path(cache_manager.CACHE_FILE).read_bytes()
    # Retry identification is deterministic; do not hit real parsers/APIs.
    monkeypatch.setattr(processor_core, "process_video", lambda s, c, d, cb:
                        process_video_with_manual_correction(s, c, d, 1, "movie", 1, 1, cb))
    from web import routes_failed
    monkeypatch.setattr(routes_failed, "process_video", processor_core.process_video)
    if failure == "tmdb":
        monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: None)
    elif failure == "link":
        monkeypatch.setattr(file_linker, "create_link", lambda *a, **k: False)
    elif failure == "nfo":
        def fail_nfo(*a, **k):
            raise OSError("disk full")
        monkeypatch.setattr(nfo_writer, "write_movie_nfo", fail_nfo)
    elif failure == "publish":
        real_link = os.link
        def fail_metadata_publication(source, destination, *a, **k):
            if Path(destination).suffix == ".nfo":
                raise OSError("publication disk full")
            return real_link(source, destination, *a, **k)
        monkeypatch.setattr(os, "link", fail_metadata_publication)
    else:
        def fail_cache(*a, **k):
            raise OSError("cache disk full")
        monkeypatch.setattr(cache_manager, "save_cache", fail_cache)
    response = client.post(endpoint, json={"src_path": str(src), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 500
    assert old.read_bytes() == b"original"
    assert nfo.read_text() == "old metadata"
    assert Path(cache_manager.CACHE_FILE).read_bytes() == original
    assert not (Path(config["movie_target_folder"]) / "New" / "New.mkv").exists()


def test_success_publishes_cache_before_removing_old(media, client, monkeypatch):
    src, config, details = media
    old = Path(config["movie_target_folder"]) / "Old" / "Old.mkv"
    assert file_linker.create_link(src, old, "symlink")
    cache_manager.save_cache({str(src): {"target": str(old), "media_type": "movie"}})
    real_unlink = Path.unlink

    def check_order(path, *a, **k):
        if path == old:
            new_entry = cache_manager.load_cache()[str(src)]
            assert new_entry["target"] != str(old)
            assert Path(new_entry["target"]).is_file()
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(Path, "unlink", check_order)
    response = client.post("/api/failed_cache/correct", json={"src_path": str(src), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 200
    assert not os.path.lexists(old)
    assert Path(cache_manager.load_cache()[str(src)]["target"]).read_bytes() == b"original"


def test_same_target_retry_is_idempotent(media, client):
    src, config, details = media
    cache = {}
    assert run_branch("manual_movie", src, config, details, cache)
    cache_manager.save_cache(cache)
    target = Path(cache[str(src)]["target"])
    inode = target.stat().st_ino
    response = client.post("/api/failed_cache/correct", json={"src_path": str(src), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 200
    assert target.stat().st_ino == inode


def test_two_sources_racing_for_one_target_have_one_winner(media):
    src, config, details = media
    other = src.with_name("other.mkv")
    other.write_bytes(b"other-version")
    gate = threading.Barrier(2)

    def work(path):
        gate.wait(timeout=5)
        cache = {}
        return run_branch("movie", path, config, details, cache), path, cache

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, [src, other]))
    assert sum(bool(r[0]) for r in results) == 1
    winner = next(r for r in results if r[0])
    assert Path(winner[2][str(winner[1])]["target"]).read_bytes() == winner[1].read_bytes()


def test_delete_one_version_keeps_shared_metadata(media, client):
    src, config, details = media
    other = src.with_name("other.mkv")
    other.write_bytes(b"other")
    folder = Path(config["movie_target_folder"]) / "Shared"
    first, second = folder / "v1.mkv", folder / "v2.mkv"
    assert file_linker.create_link(src, first, "hard")
    assert file_linker.create_link(other, second, "hard")
    nfo = folder / "movie.nfo"
    nfo.write_text("shared metadata")
    cache_manager.save_cache({str(src): {"target": str(first), "media_type": "movie", "artifacts": [str(nfo)]},
                              str(other): {"target": str(second), "media_type": "movie"}})
    assert client.post("/api/media/delete", json={"src_path": str(src)}, auth=AUTH).status_code == 200
    assert second.exists()
    assert nfo.read_text() == "shared metadata"


def test_failed_attempt_does_not_replace_successful_cache_record(media):
    from core.processor_cache_ops import save_failed_cache
    src, config, details = media
    old = {"target": str(Path(config["movie_target_folder"]) / "old.mkv"), "media_type": "movie"}
    cache = {str(src): old.copy()}
    save_failed_cache(src, "temporary TMDB error", cache)
    assert cache[str(src)] == old


def test_cleanup_failure_is_recorded_after_success(media, client, monkeypatch):
    src, config, details = media
    old = Path(config["movie_target_folder"]) / "Old" / "Old.mkv"
    assert file_linker.create_link(src, old, "hard")
    cache_manager.save_cache({str(src): {"target": str(old), "media_type": "movie"}})
    real_unlink = Path.unlink
    def fail_old_cleanup(path, *a, **k):
        if path == old:
            raise PermissionError("old directory is read-only")
        return real_unlink(path, *a, **k)
    monkeypatch.setattr(Path, "unlink", fail_old_cleanup)
    response = client.post("/api/failed_cache/correct", json={"src_path": str(src), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 200
    entry = cache_manager.load_cache()[str(src)]
    assert entry["target"] != str(old)
    assert Path(entry["target"]).read_bytes() == old.read_bytes() == b"original"
    assert entry["pending_cleanup"][0]["entry"]["target"] == str(old)


def test_conflict_response_preserves_old_cache(media, client):
    src, config, details = media
    old = Path(config["movie_target_folder"]) / "Old" / "Old.mkv"
    assert file_linker.create_link(src, old, "hard")
    cache_manager.save_cache({str(src): {"target": str(old), "media_type": "movie"}})
    original = Path(cache_manager.CACHE_FILE).read_bytes()
    conflict = Path(config["movie_target_folder"]) / "New" / "New.mkv"
    conflict.parent.mkdir()
    conflict.write_bytes(b"someone-else")
    response = client.post("/api/failed_cache/correct", json={"src_path": str(src), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 409
    assert response.json["code"] == "target_conflict"
    assert Path(cache_manager.CACHE_FILE).read_bytes() == original
    assert old.read_bytes() == b"original" and conflict.read_bytes() == b"someone-else"


def test_dangling_target_is_a_conflict(media):
    src, config, details = media
    target = Path(config["movie_target_folder"]) / "New" / "New.mkv"
    target.parent.mkdir(parents=True)
    target.symlink_to(src.with_name("missing.mkv"))
    cache = {}
    assert not run_branch("movie", src, config, details, cache)
    assert target.is_symlink()
    assert cache[str(src)]["error_code"] == "target_conflict"


def test_only_manifest_owned_metadata_is_collected(media, client):
    src, config, details = media
    cache = {}
    assert run_branch("movie", src, config, details, cache)
    cache_manager.save_cache(cache)
    target = Path(cache[str(src)]["target"])
    owned = target.parent / "movie.nfo"
    custom = target.parent / "custom.nfo"
    custom.write_text("user-owned")
    assert str(owned) in cache[str(src)]["artifacts"]
    response = client.post("/api/media/delete", json={"src_path": str(src)}, auth=AUTH)
    assert response.status_code == 200
    assert not target.exists() and not owned.exists()
    assert custom.read_text() == "user-owned"


def test_relative_source_produces_a_valid_final_symlink(media):
    src, config, details = media
    config["link_type"] = "symlink"
    cache = {}
    assert run_branch("movie", src.relative_to(Path.cwd()), config, details, cache)
    target = Path(cache[str(src)]["target"])
    assert target.is_symlink() and target.resolve() == src
