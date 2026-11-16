"""T01: every file is a tiny temporary fixture; network remains disabled."""

import errno
import os
from pathlib import Path

import pytest

from core import cache_manager, config_manager, file_linker
from core.processor_cache_ops import cleanup_previous_artifacts

AUTH = ("test-user", "test-pass")


@pytest.fixture
def media(config_file, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    src = source / "input.mkv"
    src.write_bytes(b"original-video")
    config = config_manager.load_config(str(config_file))
    config.update(source_folders=[str(source)], download_images=False)
    config["subtitle"] = {"enabled": False}
    config_manager.save_config(config, str(config_file))
    return src, config


def make_link(src, target, kind, monkeypatch):
    if kind == "exdev":
        def cross_device(*args):
            raise OSError(errno.EXDEV, "cross-device link")
        monkeypatch.setattr(os, "link", cross_device)
    assert file_linker.create_link(src, target, "hard" if kind in ("hard", "exdev") else "symlink")


def record(src, target, media_type="movie"):
    return {str(src): {"target": str(target), "media_type": media_type,
                       "season": 1, "episode": 1}}


@pytest.mark.parametrize("producer", ["movie", "tv", "manual_movie", "manual_tv", "subtitle"])
def test_all_writers_keep_link_path(producer, media, monkeypatch):
    from core import processor_movie, processor_tv, processor_manual, subtitle_handler, tmdb_client
    src, config = media
    config["link_type"] = "symlink"
    details = {"title": "Example", "name": "Example", "seasons": [{"season_number": 1, "episode_count": 1}]}
    episode = {"episode_number": 1, "name": "Pilot"}
    monkeypatch.setattr(tmdb_client, "get_tmdb_details", lambda *a, **k: details)
    monkeypatch.setattr(tmdb_client, "get_tv_season_episodes", lambda *a, **k: [episode])
    cache = {}
    if producer == "movie":
        result = processor_movie.process_movie_branch(src, config, cache, None, "Example", "", 1, details, 90)
    elif producer == "tv":
        result = processor_tv.process_tv_branch(src, config, cache, None, "Example", "", 1, details,
                                               {"season": 1, "episode": 1}, 90)
    elif producer.startswith("manual"):
        result = processor_manual.process_video_with_manual_correction(
            src, config, cache, 1, producer.split("_")[1], 1, 1)
    else:
        src = src.with_suffix(".ass")
        src.write_text("dummy subtitle")
        target_dir = Path(config["tv_target_folder"]) / "Example"
        config["subtitle_center"]["link_mode"] = "symlink"
        result = subtitle_handler.execute_subtitle_organization(str(src), {
            "target_dir": str(target_dir), "target_path": str(target_dir / "episode.mkv")}, config)
        cache = cache_manager.load_cache()
    assert result
    entry = cache[str(src)]
    assert Path(entry["target"]) != src
    assert Path(entry["target"]).is_symlink()
    assert Path(entry["target"]).resolve() == src
    assert entry["source_path"] == str(src)


@pytest.mark.parametrize("kind", ["hard", "symlink", "exdev", "dangling"])
@pytest.mark.parametrize("action", ["delete", "batch_delete", "cleanup"])
def test_remove_only_target_link(kind, action, media, client, monkeypatch):
    src, config = media
    target = Path(config["movie_target_folder"]) / "Example" / "input.mkv"
    make_link(src, target, kind, monkeypatch)
    cache_manager.save_cache(record(src, target))
    if kind == "dangling":
        src.unlink()
    if action == "cleanup":
        cleanup_previous_artifacts(src, config)
    else:
        payload = {"src_path": str(src)} if action == "delete" else {"src_paths": [str(src)]}
        response = client.post("/api/media/" + action, json=payload, auth=AUTH)
        assert response.status_code == 200
        if action == "batch_delete":
            assert response.json["success"] == 1
    assert not os.path.lexists(target)
    if kind != "dangling":
        assert src.read_bytes() == b"original-video"


@pytest.mark.parametrize("action", ["delete", "batch_delete", "cleanup"])
def test_legacy_source_target_is_backed_up_and_blocked(action, media, client):
    src, config = media
    old = record(src, src)
    cache_manager.save_cache(old)
    original = Path(cache_manager.CACHE_FILE).read_bytes()
    if action == "cleanup":
        with pytest.raises(ValueError):
            cleanup_previous_artifacts(src, config)
    else:
        payload = {"src_path": str(src)} if action == "delete" else {"src_paths": [str(src)]}
        response = client.post("/api/media/" + action, json=payload, auth=AUTH)
        if action == "delete":
            assert response.status_code == 409
        else:
            assert response.json["success"] == 0
            assert response.json["failed"] == 1
    assert src.read_bytes() == b"original-video"
    assert cache_manager.load_cache()[str(src)]["needs_reindex"] is True
    backups = list(Path.cwd().glob(cache_manager.CACHE_FILE + ".t01-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


@pytest.mark.parametrize("bad_target", ["empty", "root", "outside", "escape"])
def test_invalid_target_does_not_delete_files(bad_target, media, client, tmp_path):
    src, config = media
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.mkv"
    victim.write_bytes(b"keep")
    if bad_target == "empty":
        target = ""
    elif bad_target == "root":
        target = config["movie_target_folder"]
        Path(target).mkdir()
    elif bad_target == "outside":
        target = str(victim)
    else:
        root = Path(config["movie_target_folder"])
        root.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        target = str(root / "escape" / victim.name)
    cache_manager.save_cache(record(src, target))
    response = client.post("/api/media/delete", json={"src_path": str(src)}, auth=AUTH)
    assert response.status_code == 409
    assert victim.read_bytes() == b"keep"
    assert src.read_bytes() == b"original-video"
    assert str(src) in cache_manager.load_cache()


@pytest.mark.parametrize("flag", ["false", "true", 1, None])
@pytest.mark.parametrize("action", ["delete", "batch_delete"])
def test_delete_source_requires_boolean(flag, action, media, client, monkeypatch):
    src, config = media
    target = Path(config["movie_target_folder"]) / "input.mkv"
    make_link(src, target, "hard", monkeypatch)
    cache_manager.save_cache(record(src, target))
    payload = {"src_path": str(src)} if action == "delete" else {"src_paths": [str(src)]}
    payload["delete_source"] = flag
    response = client.post("/api/media/" + action, json=payload, auth=AUTH)
    assert response.status_code == 400
    assert target.exists() and src.exists()


def test_explicit_source_delete_requires_allowed_source(media, client, monkeypatch, config_file):
    src, config = media
    target = Path(config["movie_target_folder"]) / "input.mkv"
    make_link(src, target, "hard", monkeypatch)
    cache_manager.save_cache(record(src, target))
    config["source_folders"] = []
    config_manager.save_config(config, str(config_file))
    response = client.post("/api/media/delete", json={"src_path": str(src), "delete_source": True}, auth=AUTH)
    assert response.status_code == 409
    assert target.exists() and src.exists()


def test_explicit_source_delete_removes_both_entries(media, client, monkeypatch):
    src, config = media
    target = Path(config["movie_target_folder"]) / "input.mkv"
    make_link(src, target, "hard", monkeypatch)
    cache_manager.save_cache(record(src, target))
    response = client.post("/api/media/delete", json={"src_path": str(src), "delete_source": True}, auth=AUTH)
    assert response.status_code == 200
    assert not target.exists() and not src.exists()


@pytest.mark.parametrize("endpoint", ["/api/processed/retry", "/api/processed_cache/retry", "/api/failed_cache/correct"])
def test_retry_blocks_unsafe_old_record(endpoint, media, client):
    src, config = media
    cache_manager.save_cache(record(src, src))
    response = client.post(endpoint, json={"src_path": str(src), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 409
    assert src.read_bytes() == b"original-video"
    assert cache_manager.load_cache()[str(src)]["needs_reindex"]


def test_backup_failure_prevents_removal(media, client, monkeypatch):
    src, config = media
    cache_manager.save_cache(record(src, src))
    original = Path(cache_manager.CACHE_FILE).read_bytes()
    real_open = Path.open

    def fail_backup(path, *args, **kwargs):
        if path.name.endswith(".bak"):
            raise OSError("backup disk unavailable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_backup)
    response = client.post("/api/media/delete", json={"src_path": str(src)}, auth=AUTH)
    assert response.status_code == 500
    assert src.read_bytes() == b"original-video"
    assert Path(cache_manager.CACHE_FILE).read_bytes() == original


def test_quarantine_does_not_duplicate_backup_on_retry(media, client):
    src, config = media
    cache_manager.save_cache(record(src, src))
    for _ in range(2):
        assert client.post("/api/media/delete", json={"src_path": str(src)}, auth=AUTH).status_code == 409
    assert len(list(Path.cwd().glob(cache_manager.CACHE_FILE + ".t01-*.bak"))) == 1
    assert src.read_bytes() == b"original-video"


def test_malformed_legacy_entry_is_preserved_in_backup(media, client):
    src, config = media
    cache_manager.save_cache({str(src): None})
    original = Path(cache_manager.CACHE_FILE).read_bytes()
    response = client.post("/api/media/delete", json={"src_path": str(src)}, auth=AUTH)
    assert response.status_code == 409
    assert cache_manager.load_cache()[str(src)]["needs_reindex"]
    backup, = Path.cwd().glob(cache_manager.CACHE_FILE + ".t01-*.bak")
    assert backup.read_bytes() == original
    assert src.exists()


@pytest.mark.parametrize("action", ["delete", "batch_delete", "cleanup"])
def test_parent_symlink_escape_is_also_blocked_for_cleanup(action, media, client, tmp_path):
    src, config = media
    root = Path(config["movie_target_folder"])
    root.mkdir()
    (root / "escape").symlink_to(src.parent, target_is_directory=True)
    cache_manager.save_cache(record(src, root / "escape" / src.name))
    if action == "cleanup":
        with pytest.raises(ValueError):
            cleanup_previous_artifacts(src, config)
    else:
        payload = {"src_path": str(src)} if action == "delete" else {"src_paths": [str(src)]}
        response = client.post("/api/media/" + action, json=payload, auth=AUTH)
        assert response.status_code == 409 if action == "delete" else response.json["failed"] == 1
    assert src.read_bytes() == b"original-video"


def test_batch_removes_valid_link_and_keeps_unsafe_record(media, client, monkeypatch):
    src, config = media
    other = src.with_name("other.mkv")
    other.write_bytes(b"keep-other")
    target = Path(config["movie_target_folder"]) / "valid.mkv"
    make_link(src, target, "symlink", monkeypatch)
    cache = record(src, target)
    cache.update(record(other, other))
    cache_manager.save_cache(cache)
    response = client.post("/api/media/batch_delete", json={"src_paths": [str(src), str(other)]}, auth=AUTH)
    assert response.status_code == 200
    assert response.json["success"] == response.json["failed"] == 1
    assert not target.is_symlink()
    assert src.read_bytes() == b"original-video" and other.read_bytes() == b"keep-other"
    assert cache_manager.load_cache()[str(other)]["needs_reindex"]


def test_collision_with_source_path_is_rejected_by_writer(media):
    from core.processor_movie import process_movie_branch
    src, config = media
    # Source equals the generated target path: no unlink or cache success.
    new_src = src.with_name(src.parent.name + src.suffix)
    src.rename(new_src)
    src = new_src
    config["movie_target_folder"] = str(src.parent.parent)
    result = process_movie_branch(src, config, {}, None, src.parent.name, "", 1, {}, 90)
    assert result is False
    assert src.read_bytes() == b"original-video"


def test_batch_correction_keeps_quarantine_and_prior_success(media, client, monkeypatch):
    from web import routes_failed, task_state
    src, config = media
    unsafe = src.with_name("unsafe.mkv")
    unsafe.write_bytes(b"keep-unsafe")
    old_target = Path(config["movie_target_folder"]) / "old.mkv"
    make_link(src, old_target, "symlink", monkeypatch)
    cache = record(src, old_target)
    cache.update(record(unsafe, unsafe))
    cache_manager.save_cache(cache)
    workers = []
    processed = []

    class QueuedThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            workers.append(self.target)

    def correct(source, config, snapshot, *args):
        processed.append(source)
        new_target = old_target.with_name("new.mkv")
        assert file_linker.create_link(source, new_target, "hard")
        snapshot[str(source)] = {"target": str(old_target.with_name("new.mkv")),
                                 "media_type": "movie", "confidence": 91}
        return True

    monkeypatch.setattr(routes_failed.threading, "Thread", QueuedThread)
    monkeypatch.setattr(routes_failed, "process_video_with_manual_correction", correct)
    try:
        response = client.post("/api/failed_cache/batch_correct", auth=AUTH,
                               json={"src_paths": [str(src), str(unsafe)], "tmdb_id": 1,
                                     "media_type": "movie"})
        assert response.status_code == 200
        workers[0]()
        assert processed == [src]
        saved = cache_manager.load_cache()
        assert saved[str(src)]["confidence"] == 91
        assert saved[str(unsafe)]["needs_reindex"] is True
        assert src.read_bytes() == b"original-video"
        assert unsafe.read_bytes() == b"keep-unsafe"
    finally:
        task_state.reset_task_state()
        task_state.clear_stop_flag()
