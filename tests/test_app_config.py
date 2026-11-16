"""Regression coverage for per-application configuration injection."""

import json


AUTH = ("test-user", "test-pass")


def test_factory_uses_explicit_config_without_creating_default(client, config_file):
    response = client.get("/api/config", auth=AUTH)
    assert response.status_code == 200
    assert response.json["tmdb_api"]["api_key_configured"] is True
    assert json.loads(config_file.read_text())["tmdb_api"]["api_key"] == "dummy-tmdb-key"
    assert not config_file.with_name("auto_config.json").exists()


def test_auth_and_config_save_use_same_explicit_path(client, config_file):
    assert client.post("/api/config", json={}, auth=("admin", "admin")).status_code == 401
    response = client.post("/api/config", json={"max_workers": 2}, auth=AUTH)
    assert response.status_code == 200
    assert json.loads(config_file.read_text())["max_workers"] == 2
    assert not config_file.with_name("auto_config.json").exists()


def test_mapping_route_uses_injected_config(client):
    response = client.get("/api/special_mappings", auth=AUTH)
    assert response.status_code == 200
    assert response.json == {"mappings": []}


def test_multiple_apps_keep_their_own_config(config_file, tmp_path):
    from web import create_app
    first = create_app(config_path=config_file).test_client()
    other_path = tmp_path / "other.json"
    other_path.write_text(json.dumps({
        "auth": {"enabled": True, "username": "other", "password": "other-pass"},
        "tmdb_api": {"api_key": "other-dummy-key", "language": "ja-JP"},
    }), encoding="utf-8")
    second = create_app(config_path=other_path).test_client()
    assert first.get("/api/config", auth=AUTH).json["tmdb_api"]["language"] == "zh-CN"
    assert second.get("/api/config", auth=("other", "other-pass")).json["tmdb_api"]["language"] == "ja-JP"
    assert first.get("/api/special_mappings", auth=AUTH).status_code == 200
    assert second.get("/api/special_mappings", auth=AUTH).status_code == 401


def test_task_worker_receives_config_outside_request(client, config_file, monkeypatch):
    from web import routes_task, task_state
    workers = []
    calls = []

    class QueuedThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            workers.append(self.target)

    monkeypatch.setattr(routes_task.threading, "Thread", QueuedThread)
    monkeypatch.setattr(routes_task.media_processor, "run_processor_with_callback",
                        lambda path, callback, **kwargs: calls.append(path))
    try:
        assert client.post("/api/run", auth=AUTH).status_code == 200
        workers[0]()  # Flask request context has already exited.
        assert calls == [str(config_file)]
    finally:
        task_state.reset_task_state()
        routes_task.media_processor.stop_processing.clear()


def test_factory_default_remains_compatible(tmp_path):
    from web import create_app
    response = create_app().test_client().get("/api/config")
    assert response.status_code == 200
    assert (tmp_path / "auto_config.json").is_file()


def test_explicit_relative_config_survives_workdir_change(config_file, tmp_path, monkeypatch):
    from web import create_app
    app = create_app(config_path=config_file.name)
    other_dir = tmp_path / "different-cwd"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)
    response = app.test_client().get("/api/config", auth=AUTH)
    assert response.status_code == 200
    assert response.json["tmdb_api"]["api_key_configured"] is True
    assert json.loads(config_file.read_text())["tmdb_api"]["api_key"] == "dummy-tmdb-key"
    assert not (other_dir / "auto_config.json").exists()
