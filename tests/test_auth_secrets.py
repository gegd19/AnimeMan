"""T03: access policy, redacted round trips and server-side credentials."""

import json
from pathlib import Path

import pytest

from core import config_manager

AUTH = ("test-user", "test-pass")


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("credentials", [None, ("wrong", "wrong"), AUTH])
@pytest.mark.parametrize("endpoint", ["/api/config", "/api/log", "/api/status", "/api/drives", "/api/special_mappings", "/"])
def test_auth_matrix(enabled, credentials, endpoint, client, config_file):
    config = config_manager.load_config(str(config_file))
    config["auth"]["enabled"] = enabled
    config_manager.save_config(config, str(config_file))
    response = client.get(endpoint, auth=credentials)
    assert response.status_code == (401 if enabled and credentials != AUTH else 200)


def test_health_is_public_and_does_not_load_business_config(client, monkeypatch):
    monkeypatch.setattr(config_manager, "load_config", lambda *a, **k: pytest.fail("health must not load config"))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_prefix_lookalike_is_not_public(app):
    app.add_url_rule("/api/status_private", "private_probe", lambda: "private")
    assert app.test_client().get("/api/status_private").status_code == 401


def test_config_never_returns_secrets_and_round_trip_preserves_them(client, config_file):
    config = config_manager.load_config(str(config_file))
    config["ai_parser"]["api_key"] = "parser-secret"
    config["ai_plot_enhance"]["api_key"] = "plot-secret"
    config_manager.save_config(config, str(config_file))
    response = client.get("/api/config", auth=AUTH)
    assert response.status_code == 200
    for secret in ("dummy-tmdb-key", "parser-secret", "plot-secret", "test-pass"):
        assert secret not in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"
    for section in ("tmdb_api", "ai_parser", "ai_plot_enhance"):
        assert response.json[section]["api_key"] == ""
        assert response.json[section]["api_key_configured"] is True
    assert response.json["auth"]["password_configured"] is True
    assert client.post("/api/config", auth=AUTH, json=response.json).status_code == 200
    saved = json.loads(config_file.read_text())
    for section in ("tmdb_api", "ai_parser", "ai_plot_enhance"):
        assert saved[section]["api_key"] == config[section]["api_key"]
        assert "api_key_configured" not in saved[section]
    assert saved["auth"]["password"] == "test-pass"


def test_explicit_clear_is_separate_from_blank_or_omitted(client, config_file):
    for payload in ({}, {"tmdb_api": {"api_key": ""}}):
        assert client.post("/api/config", auth=AUTH, json=payload).status_code == 200
        assert json.loads(config_file.read_text())["tmdb_api"]["api_key"] == "dummy-tmdb-key"
    assert client.post("/api/config", auth=AUTH, json={"clear_secrets": ["tmdb_api.api_key"]}).status_code == 200
    assert json.loads(config_file.read_text())["tmdb_api"]["api_key"] == ""
    assert client.get("/api/config", auth=AUTH).json["tmdb_api"]["api_key_configured"] is False


def test_invalid_clear_or_empty_auth_cannot_lock_user_out(client, config_file):
    original = config_file.read_bytes()
    for payload in ({"clear_secrets": ["unknown.secret"]}, {"clear_secrets": ["auth.password"]},
                    {"auth": {"enabled": "false"}}, {"auth": {"username": ["invalid"]}}):
        assert client.post("/api/config", auth=AUTH, json=payload).status_code == 400
        assert config_file.read_bytes() == original


def test_corrupt_config_does_not_disable_auth(client, config_file):
    config_file.write_text("{broken")
    assert client.get("/api/config").status_code == 503
    assert client.get("/healthz").status_code == 200


def test_stream_uses_saved_key_without_returning_it(client, config_file, monkeypatch):
    import requests
    config = config_manager.load_config(str(config_file))
    config["ai_parser"]["api_key"] = "saved-ai-secret"
    config_manager.save_config(config, str(config_file))
    captured = []

    class Reply:
        def raise_for_status(self):
            pass
        def iter_lines(self, **kwargs):
            yield 'data: {"choices":[{"delta":{"content":"sample"}}]}'
            yield 'data: [DONE]'
        def close(self):
            pass

    def post(session, url, **kwargs):
        captured.append((url, kwargs))
        return Reply()

    monkeypatch.setattr(requests.Session, "post", post)
    response = client.post("/api/ai/stream_enhance", auth=AUTH,
                           json={"title": "example", "original_plot": "plot", "ai_config": {"api_key": ""}})
    body = response.get_data(as_text=True)
    assert response.status_code == 200 and "sample" in body
    assert captured[0][1]["headers"]["Authorization"] == "Bearer saved-ai-secret"
    assert "saved-ai-secret" not in body


def test_saved_ai_key_cannot_be_redirected_to_another_host(client, config_file, monkeypatch):
    config = config_manager.load_config(str(config_file))
    config["ai_parser"]["api_key"] = "saved-ai-secret"
    config_manager.save_config(config, str(config_file))
    response = client.post("/api/ai/stream_enhance", auth=AUTH, json={
        "title": "test", "original_plot": "plot", "ai_config": {"base_url": "https://different.invalid"}})
    assert response.status_code == 400


def test_tmdb_test_error_does_not_echo_key(client, monkeypatch):
    from core import tmdb_client
    class Session:
        def get(self, *a, **k):
            raise OSError("request failed https://example.invalid/?api_key=dummy-tmdb-key")
    monkeypatch.setattr(tmdb_client, "create_session", lambda *a: Session())
    response = client.get("/api/tmdb/test", auth=AUTH)
    assert response.status_code == 500
    assert "dummy-tmdb-key" not in response.get_data(as_text=True)
