"""T03 path permission checks happen before scanning, writing or workers."""

from pathlib import Path

import pytest
from core import config_manager

AUTH = ("test-user", "test-pass")


@pytest.fixture
def paths(config_file, tmp_path):
    src, outside, tv = (tmp_path / name for name in ("source", "outside", "tv"))
    for path in (src, outside, tv):
        path.mkdir()
    config = config_manager.load_config(str(config_file))
    config["source_folders"] = [str(src)]
    config_manager.save_config(config, str(config_file))
    return src, outside, tv


def test_browse_does_not_grant_ancestors_or_symlink_escape(client, paths):
    src, outside, tv = paths
    (src / "escape").symlink_to(outside, target_is_directory=True)
    for target in (src.parent, outside, src / "escape"):
        assert client.get("/api/browse", query_string={"path": str(target)}, auth=AUTH).status_code == 403
    response = client.get("/api/browse", query_string={"path": str(src)}, auth=AUTH)
    assert response.status_code == 200
    assert response.json["parent"] is None
    assert all(p["name"] != "escape" for p in response.json["dirs"])


def test_explicit_browse_root_does_not_grant_source_read(client, paths, config_file):
    src, outside, tv = paths
    config = config_manager.load_config(str(config_file))
    config["browse_roots"] = [str(outside)]
    config_manager.save_config(config, str(config_file))
    assert client.get("/api/browse", query_string={"path": str(outside)}, auth=AUTH).status_code == 200
    assert client.post("/api/subtitle/scan", json={"folder": str(outside)}, auth=AUTH).status_code == 403


@pytest.mark.parametrize("endpoint", ["/api/failed_cache/correct", "/api/processed/retry", "/api/processed_cache/retry"])
def test_manual_source_outside_roots_is_rejected(endpoint, client, paths):
    src, outside, tv = paths
    video = outside / "file.mkv"
    video.write_bytes(b"keep")
    response = client.post(endpoint, json={"src_path": str(video), "tmdb_id": 1, "media_type": "movie"}, auth=AUTH)
    assert response.status_code == 403
    assert video.read_bytes() == b"keep"


def test_batch_correction_rejects_outside_before_starting(client, paths):
    src, outside, tv = paths
    response = client.post("/api/failed_cache/batch_correct", json={"src_paths": [str(outside / "file.mkv")], "tmdb_id": 1}, auth=AUTH)
    assert response.status_code == 403


def test_subtitle_scan_outside_does_not_call_scanner(client, paths, monkeypatch):
    from core import subtitle_handler
    src, outside, tv = paths
    monkeypatch.setattr(subtitle_handler, "scan_subtitle_folder", lambda *a: pytest.fail("scanner must not run"))
    assert client.post("/api/subtitle/scan", json={"folder": str(outside)}, auth=AUTH).status_code == 403


def test_subtitle_execute_rejects_entire_batch_before_writes(client, paths, monkeypatch):
    from core import subtitle_handler
    src, outside, tv = paths
    monkeypatch.setattr(subtitle_handler, "execute_subtitle_organization", lambda *a: pytest.fail("writer must not run"))
    response = client.post("/api/subtitle/execute", json={"items": [{
        "subtitle_path": str(src / "one.ass"),
        "target_media": {"target_path": str(tv / "episode.mkv"), "target_dir": str(outside)}}]}, auth=AUTH)
    assert response.status_code == 403


def test_subtitle_rename_cannot_escape_source(client, paths):
    src, outside, tv = paths
    sub = src / "one.ass"
    sub.write_text("keep")
    response = client.post("/api/subtitle/batch_rename", json={"renames": [
        {"old_path": str(sub), "new_path": str(outside / "stolen.ass")}]}, auth=AUTH)
    assert response.status_code == 403
    assert sub.read_text() == "keep"


def test_library_video_symlink_to_allowed_source_can_be_used(client, paths, monkeypatch):
    from core import subtitle_handler
    src, outside, tv = paths
    (src / "video.mkv").write_bytes(b"video")
    (tv / "video.mkv").symlink_to(src / "video.mkv")
    sub = src / "one.ass"
    sub.write_text("sample")
    monkeypatch.setattr(subtitle_handler, "execute_subtitle_organization", lambda *a: True)
    response = client.post("/api/subtitle/execute", json={"items": [{"subtitle_path": str(sub),
        "target_media": {"target_path": str(tv / "video.mkv"), "target_dir": str(tv)}}]}, auth=AUTH)
    assert response.status_code == 200


def test_scan_does_not_return_symlinked_outside_subtitles(client, paths):
    src, outside, tv = paths
    secret = outside / "secret.ass"
    secret.write_text("outside")
    (src / "escape.ass").symlink_to(secret)
    response = client.post("/api/subtitle/scan", json={"folder": str(src)}, auth=AUTH)
    assert response.status_code == 200
    assert response.json["subtitles"] == []


def test_folder_details_skips_outside_symlink_directory(client, paths):
    src, outside, tv = paths
    (outside / "secret.mkv").write_bytes(b"outside")
    (src / "escape").symlink_to(outside, target_is_directory=True)
    response = client.get("/api/failed_cache/folder_details", query_string={"folder": str(src)}, auth=AUTH)
    assert response.status_code == 200
    assert "secret.mkv" not in response.get_data(as_text=True)
