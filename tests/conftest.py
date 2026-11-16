"""Keep collection-time imports and test writes away from user data."""

import json
import logging
from pathlib import Path
import socket
import tempfile

import pytest
import requests


def _no_network(*args, **kwargs):
    raise AssertionError("Network disabled in tests; mock the AI/TMDB response")


def pytest_sessionstart(session):
    # Fixtures run after collection. The application currently reads caches and
    # opens a log file during import, so isolate the cwd before collection too.
    session._sandbox = tempfile.TemporaryDirectory(prefix="animeman-pytest-")
    session._isolation = patch = pytest.MonkeyPatch()
    patch.chdir(session._sandbox.name)
    for key in ("CONFIG_PATH", "CACHE_PATH", "LOG_PATH"):
        patch.setenv(key, str(Path(session._sandbox.name) / key.lower()))
    for key in ("SOURCE_FOLDERS", "TV_TARGET_FOLDER", "MOVIE_TARGET_FOLDER",
                "OPENAI_API_KEY", "TMDB_API_KEY", "DEEPSEEK_API_KEY"):
        patch.delenv(key, raising=False)
    patch.setenv("SECRET_KEY", "test-only-secret")
    patch.setattr(requests.sessions.Session, "request", _no_network)
    patch.setattr(socket.socket, "connect", _no_network)
    patch.setattr(socket.socket, "connect_ex", _no_network)
    patch.setattr(socket, "create_connection", _no_network)


def pytest_sessionfinish(session, exitstatus):
    # Close only the application's handlers before deleting their sandbox.
    logger = logging.getLogger("emby_auto")
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    session._isolation.undo()
    session._sandbox.cleanup()


@pytest.fixture(autouse=True)
def isolated_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Runtime paths now honor the environment: isolate it per test as well as
    # before collection, instead of sharing the session cache between cases.
    monkeypatch.setenv("CONFIG_PATH", str(tmp_path / "auto_config.json"))
    monkeypatch.setenv("CACHE_PATH", str(tmp_path))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "logs"))
    from core.logger import setup_logging
    setup_logging()


@pytest.fixture
def config_file(tmp_path):
    """Dummy credentials deliberately differ from the application's defaults."""
    path = tmp_path / "test-config.json"
    path.write_text(json.dumps({
        "auth": {"enabled": True, "username": "test-user", "password": "test-pass"},
        "source_folders": [], "special_mappings": [],
        "tv_target_folder": str(tmp_path / "tv"),
        "movie_target_folder": str(tmp_path / "movies"),
        "tmdb_api": {"api_key": "dummy-tmdb-key"},
        "ai_parser": {"enabled": False, "api_key": ""},
    }), encoding="utf-8")
    return path


@pytest.fixture
def app(config_file):
    from web import create_app
    app = create_app(config_path=config_file)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()
