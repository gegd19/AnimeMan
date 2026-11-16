"""T04: environment routing and migration use only temporary directories."""

import importlib
import json
import logging
from pathlib import Path
import os
import subprocess
import sys

import pytest

from core import config_manager, cache_manager


def test_config_env_is_used_but_explicit_argument_wins(tmp_path, monkeypatch):
    env_config = tmp_path / "persistent" / "config.json"
    env_config.parent.mkdir()
    env_config.write_text('{"max_workers": 8}')
    explicit = tmp_path / "explicit.json"
    explicit.write_text('{"max_workers": 2}')
    monkeypatch.setenv("CONFIG_PATH", str(env_config))
    assert config_manager.load_config()["max_workers"] == 8
    assert config_manager.load_config(explicit)["max_workers"] == 2
    other = tmp_path / "other-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    assert config_manager.load_config()["max_workers"] == 8


def test_web_factory_uses_config_env(tmp_path, monkeypatch):
    from web import create_app
    path = tmp_path / "persistent" / "web.json"
    path.parent.mkdir()
    path.write_text('{"auth":{"enabled":false},"max_workers":8}')
    monkeypatch.setenv("CONFIG_PATH", str(path))
    assert create_app().test_client().get("/api/config").json["max_workers"] == 8


def test_source_environment_overrides_are_effective_not_persisted(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text('{"source_folders":["old"],"tv_target_folder":"old-tv"}')
    monkeypatch.setenv("SOURCE_FOLDERS", json.dumps(["/media/source one", "/media/source two"]))
    monkeypatch.setenv("TV_TARGET_FOLDER", "/media/tv")
    monkeypatch.setenv("MOVIE_TARGET_FOLDER", "/media/movies")
    effective = config_manager.load_config(path)
    assert effective["source_folders"] == ["/media/source one", "/media/source two"]
    assert effective["tv_target_folder"] == "/media/tv"
    assert effective["movie_target_folder"] == "/media/movies"
    assert json.loads(path.read_text())["source_folders"] == ["old"]


@pytest.mark.parametrize("module,save,load,name", [
    ("core.cache_manager", "save_cache", "load_cache", "auto_processed_cache.json"),
    ("core.cache_manager", "save_ai_parse_cache", "load_ai_parse_cache", "ai_parse_cache.json"),
    ("core.folder_ai_cache", "save_folder_cache", "load_folder_cache", "folder_ai_parse_cache.json"),
    ("core.folder_parser", "save_folder_cache", "load_folder_cache", "folder_ai_cache.json"),
    ("core.offline_ai_preparser", "save_raw_cache", "load_raw_cache", "raw_scan_cache.json"),
    ("core.offline_ai_preparser", "save_ai_preparse_cache", "load_ai_preparse_cache", "ai_preparse_cache.json"),
    ("core.media_library_cache", "save_media_library_cache", "load_media_library_cache", "media_library_cache.json"),
])
def test_all_cache_io_uses_current_environment(module, save, load, name, tmp_path, monkeypatch):
    mod = importlib.import_module(module)  # Deliberately import before changing env.
    root = tmp_path / "cache-one"
    monkeypatch.setenv("CACHE_PATH", str(root))
    getattr(mod, save)({"sample": 1})
    assert json.loads((root / name).read_text()) == {"sample": 1}
    assert getattr(mod, load)() == {"sample": 1}
    other = tmp_path / "cache-two"
    monkeypatch.setenv("CACHE_PATH", str(other))
    assert getattr(mod, load)() == {}
    getattr(mod, save)({"sample": 2})
    assert json.loads((root / name).read_text()) == {"sample": 1}
    assert json.loads((other / name).read_text()) == {"sample": 2}
    assert not (tmp_path / name).exists()


def test_tmdb_memory_cache_tracks_storage_path(tmp_path, monkeypatch):
    from core import tmdb_cache
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "one"))
    tmdb_cache.set_cached_result("example", "tv", "", {"id": 1})
    assert tmdb_cache.get_cached_result("example", "tv") == {"id": 1}
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "two"))
    assert tmdb_cache.get_cached_result("example", "tv") is None


def test_poster_cache_tracks_storage_path(tmp_path, monkeypatch):
    from web import routes_config
    root = tmp_path / "posters"
    root.mkdir()
    (root / "poster_cache.json").write_text('{"123":{"poster_path":"dummy"}}')
    monkeypatch.setenv("CACHE_PATH", str(root))
    routes_config._load_poster_cache()
    assert "123" in routes_config._poster_cache
    routes_config._save_poster_cache()
    assert (root / "poster_cache.json").is_file()


def test_logger_and_log_api_share_log_path(client, tmp_path, monkeypatch):
    from core.logger import setup_logging, get_logger
    root = tmp_path / "logs"
    monkeypatch.setenv("LOG_PATH", str(root))
    setup_logging()
    get_logger().warning("temporary-log-marker")
    for handler in logging.getLogger("emby_auto").handlers:
        handler.flush()
    assert "temporary-log-marker" in (root / "auto_processor_errors.log").read_text()
    response = client.get("/api/log", auth=("test-user", "test-pass"))
    assert "temporary-log-marker" in response.json["log"]


def test_cli_passes_selected_config_to_runner(tmp_path, monkeypatch):
    import main
    path = tmp_path / "cli.json"
    path.write_text('{}')
    monkeypatch.setenv("CONFIG_PATH", str(path))
    monkeypatch.setattr("sys.argv", ["main.py"])
    called = []
    monkeypatch.setattr(main, "run_processor_with_callback", lambda path, *a, **k: called.append(path))
    main.main()
    assert called == [str(path)]


def test_no_environment_keeps_legacy_default_locations(tmp_path, monkeypatch):
    for name in ("CONFIG_PATH", "CACHE_PATH", "LOG_PATH"):
        monkeypatch.delenv(name, raising=False)
    config_manager.load_config()
    cache_manager.save_cache({"sample": 1})
    assert (tmp_path / "auto_config.json").exists()
    assert (tmp_path / "auto_processed_cache.json").exists()


def test_legacy_data_requires_explicit_migration(tmp_path, monkeypatch):
    from core.runtime_paths import MigrationRequired
    old = tmp_path / "auto_processed_cache.json"
    old.write_text('{"legacy":1}')
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "persistent"))
    with pytest.raises(MigrationRequired):
        cache_manager.save_cache({"new": 2})
    assert old.read_text() == '{"legacy":1}'
    assert not (tmp_path / "persistent" / old.name).exists()


def test_explicit_migration_backs_up_and_is_idempotent(tmp_path, monkeypatch):
    from core.runtime_paths import migrate_legacy
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for name in ("auto_config.json", "auto_processed_cache.json"):
        (legacy / name).write_text('{"sample":1}')
    (legacy / "auto_processor_errors.log").write_text("old log")
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "config" / "custom.json"))
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "cache"))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "logs"))
    migrate_legacy(legacy, apply=False)
    assert not (tmp_path / "cache").exists()
    migrate_legacy(legacy, apply=True)
    assert (tmp_path / "config" / "custom.json").read_text() == '{"sample":1}'
    assert (tmp_path / "cache" / "auto_processed_cache.json").read_text() == '{"sample":1}'
    assert (tmp_path / "logs" / "auto_processor_errors.log").read_text() == "old log"
    backups = list(tmp_path.rglob("*.pre-t04-*.bak"))
    assert len(backups) == 3
    migrate_legacy(legacy, apply=True)
    assert len(list(tmp_path.rglob("*.pre-t04-*.bak"))) == 3
    assert (legacy / "auto_processed_cache.json").exists()


def test_migration_conflict_does_not_overwrite_or_partially_copy(tmp_path, monkeypatch):
    from core.runtime_paths import migrate_legacy
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "ai_parse_cache.json").write_text('{"old":1}')
    (legacy / "auto_processed_cache.json").write_text('{"old":1}')
    target = tmp_path / "cache"
    target.mkdir()
    (target / "auto_processed_cache.json").write_text('{"new":2}')
    monkeypatch.setenv("CACHE_PATH", str(target))
    with pytest.raises(FileExistsError):
        migrate_legacy(legacy, apply=True)
    assert not (target / "ai_parse_cache.json").exists()
    assert (target / "auto_processed_cache.json").read_text() == '{"new":2}'


def test_environment_managed_paths_survive_web_round_trip(client, config_file, monkeypatch):
    original = json.loads(config_file.read_text())
    monkeypatch.setenv("SOURCE_FOLDERS", "/media/source")
    response = client.get("/api/config", auth=("test-user", "test-pass"))
    assert response.json["source_folders"] == ["/media/source"]
    assert "source_folders" in response.json["environment_managed"]
    assert client.post("/api/config", json=response.json, auth=("test-user", "test-pass")).status_code == 200
    assert json.loads(config_file.read_text())["source_folders"] == original["source_folders"]
    payload = {"source_folders": ["/cannot-override-environment"]}
    assert client.post("/api/config", json=payload, auth=("test-user", "test-pass")).status_code == 400


def test_offline_explicit_cache_path_overrides_environment(tmp_path, monkeypatch):
    from core.offline_ai_preparser import save_raw_cache, load_raw_cache
    monkeypatch.setenv("CACHE_PATH", str(tmp_path / "other"))
    explicit = tmp_path / "explicit" / "raw.json"
    save_raw_cache({"sample": 1}, explicit)
    assert load_raw_cache(explicit) == {"sample": 1}
    assert not (tmp_path / "other").exists()


def test_config_legacy_guard_preserves_existing_auth(tmp_path, monkeypatch):
    from core.runtime_paths import MigrationRequired
    old = tmp_path / "auto_config.json"
    old.write_text('{"auth":{"enabled":true,"username":"dummy","password":"dummy"}}')
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "new" / "config.json"))
    with pytest.raises(MigrationRequired):
        config_manager.load_config()
    assert not (tmp_path / "new").exists()


def test_migration_failure_rolls_back_only_new_files(tmp_path, monkeypatch):
    from core.runtime_paths import migrate_legacy
    legacy, target = tmp_path / "old", tmp_path / "new"
    legacy.mkdir()
    for name in ("auto_processed_cache.json", "ai_parse_cache.json"):
        (legacy / name).write_text('{"old":1}')
    monkeypatch.setenv("CACHE_PATH", str(target))
    real_open = Path.open
    def fail_second(path, *args, **kwargs):
        if path == target / "ai_parse_cache.json":
            raise PermissionError("simulated destination permission failure")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail_second)
    with pytest.raises(PermissionError):
        migrate_legacy(legacy, apply=True)
    assert not (target / "auto_processed_cache.json").exists()
    assert all((legacy / name).read_text() == '{"old":1}' for name in ("auto_processed_cache.json", "ai_parse_cache.json"))
    assert list(target.rglob("*.bak"))


def test_migration_cli_runs_without_processor_initialization(tmp_path, monkeypatch):
    legacy = tmp_path / "old"
    legacy.mkdir()
    (legacy / "auto_processed_cache.json").write_text('{"old":1}')
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), CACHE_PATH=str(tmp_path / "new-cache"),
               LOG_PATH=str(tmp_path / "new-logs"), PYTHONDONTWRITEBYTECODE="1")
    response = subprocess.run([sys.executable, "-m", "core.runtime_paths", "migrate", "--legacy-dir", str(legacy)],
                              env=env, capture_output=True, text=True, timeout=10)
    assert response.returncode == 0, response.stderr
    assert json.loads(response.stdout)[0]["state"] == "copy"
    assert not (tmp_path / "new-cache").exists() and not (tmp_path / "new-logs").exists()


def test_storage_parent_error_is_actionable(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("keep")
    monkeypatch.setenv("CACHE_PATH", str(blocker / "cache"))
    with pytest.raises(OSError, match="无法创建运行数据目录"):
        cache_manager.save_cache({"sample": 1})
    assert blocker.read_text() == "keep"


def test_alias_and_parser_memory_caches_follow_path_changes(tmp_path, monkeypatch):
    from core import processor_search, search_enhancer, parser_manager
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    (first / "tmdb_aliases.json").write_text('{"sample":{"id":1}}')
    monkeypatch.setenv("CACHE_PATH", str(first))
    assert processor_search._load_aliases()["sample"]["id"] == 1
    assert search_enhancer.load_aliases()["sample"]["id"] == 1
    parser_manager._save_parse_result("sample", {"media_type":"movie", "title": "first"})
    monkeypatch.setenv("CACHE_PATH", str(second))
    assert processor_search._load_aliases() == {}
    assert search_enhancer.load_aliases() == {}
    parser_manager._ensure_persistent_cache()
    assert parser_manager.AI_CACHE == {} and parser_manager._ai_parse_persistent_cache == {}


def test_new_process_reads_persistent_data_from_another_cwd(tmp_path, monkeypatch):
    config = tmp_path / "persistent-config" / "custom.json"
    cache = tmp_path / "persistent-cache"
    logs = tmp_path / "persistent-logs"
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("CACHE_PATH", str(cache))
    monkeypatch.setenv("LOG_PATH", str(logs))
    config_manager.save_config({"max_workers": 7})
    cache_manager.save_cache({"temporary-sample": {"media_type": "failed"}})
    other = tmp_path / "different-cwd"
    other.mkdir()
    root = Path(__file__).resolve().parents[1]
    code = ("import json; from core import load_config, load_cache; "
            "from core.logger import get_logger; get_logger().warning('restart-marker'); "
            "print(json.dumps({'workers':load_config()['max_workers'],'cache':load_cache()}))")
    result = subprocess.run([sys.executable, "-c", code], cwd=other,
                            env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1"),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["workers"] == 7
    assert "temporary-sample" in json.loads(result.stdout)["cache"]
    assert "restart-marker" in (logs / "auto_processor_errors.log").read_text()
    assert list(other.iterdir()) == []


def test_migration_rejects_destination_symlink(tmp_path, monkeypatch):
    from core.runtime_paths import migrate_legacy
    legacy, destination = tmp_path / "old", tmp_path / "new"
    legacy.mkdir()
    destination.mkdir()
    source = legacy / "auto_processed_cache.json"
    source.write_text('{"old":1}')
    (destination / source.name).symlink_to(source)
    monkeypatch.setenv("CACHE_PATH", str(destination))
    with pytest.raises(ValueError, match="符号链接"):
        migrate_legacy(legacy, apply=True)
    assert source.read_text() == '{"old":1}'


def test_auxiliary_tmdb_lookup_uses_explicit_effective_config(monkeypatch):
    from core import search_enhancer
    import requests
    captured = []
    def get(url, **kwargs):
        captured.append(kwargs["params"]["api_key"])
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"tv_results":[{"id":123}]}'
        return response
    monkeypatch.setattr(requests, "get", get)
    assert search_enhancer.find_tmdb_by_imdb("dummy-imdb-id", config={"tmdb_api": {"api_key": "explicit-dummy-key"}}) == 123
    assert captured == ["explicit-dummy-key"]


@pytest.mark.parametrize("name,loader,filename", [
    ("core.processor_search", "_load_aliases", "tmdb_aliases.json"),
    ("core.search_enhancer", "load_aliases", "tmdb_aliases.json"),
    ("core.tmdb_cache", "get_cached_result", "tmdb_search_cache.json"),
])
def test_cache_permission_failure_does_not_become_a_cached_empty_result(name, loader, filename, tmp_path, monkeypatch):
    root = tmp_path / "restricted"
    root.mkdir()
    path = root / filename
    path.write_text('{}')
    module = importlib.import_module(name)
    monkeypatch.setenv("CACHE_PATH", str(root))
    real_open = Path.open
    def deny_read(current, *args, **kwargs):
        if current == path:
            raise PermissionError("simulated read failure")
        return real_open(current, *args, **kwargs)
    # The loaders use builtins.open, so intercept it with the same path check.
    import builtins
    real_builtin_open = builtins.open
    def deny_builtin(current, *args, **kwargs):
        if Path(current) == path:
            raise PermissionError("simulated read failure")
        return real_builtin_open(current, *args, **kwargs)
    monkeypatch.setattr(Path, "open", deny_read)
    monkeypatch.setattr(builtins, "open", deny_builtin)
    for _ in range(2):
        with pytest.raises(PermissionError):
            getattr(module, loader)("sample", "tv") if name.endswith("tmdb_cache") else getattr(module, loader)()
