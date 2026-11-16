"""Exercise the test harness with dummy data only."""

import os
import logging
from pathlib import Path
import socket

import pytest
import requests
from core.logger import setup_logging

setup_logging()
COLLECTION_LOG_DIRECTORY = Path(os.environ["LOG_PATH"])
COLLECTION_LOG_FILES = [Path(handler.baseFilename) for handler in logging.getLogger("emby_auto").handlers
                        if hasattr(handler, 'baseFilename')]


def test_network_requires_mock():
    with pytest.raises(AssertionError, match="Network disabled"):
        requests.get("https://example.invalid")
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="Network disabled"):
            connection.connect(("127.0.0.1", 9))


def test_fake_http_response_can_be_injected(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"results": []}'
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: response)
    assert requests.get("https://example.invalid").json() == {"results": []}


def test_config_and_cache_writes_stay_in_temporary_directory(tmp_path):
    from core import cache_manager, config_manager
    config_manager.load_config()
    cache_manager.save_cache({"dummy-source": {"media_type": "failed"}})
    assert cache_manager.load_cache()["dummy-source"]["media_type"] == "failed"
    assert Path.cwd() == tmp_path
    assert (tmp_path / "auto_config.json").is_file()
    assert (tmp_path / cache_manager.CACHE_FILE).is_file()
    assert Path(os.environ["CONFIG_PATH"]).parent == tmp_path


def test_collection_time_log_is_also_in_sandbox():
    assert COLLECTION_LOG_DIRECTORY.parent.name.startswith("animeman-pytest-")
    assert len(COLLECTION_LOG_FILES) == 1
    assert COLLECTION_LOG_FILES[0].parent == COLLECTION_LOG_DIRECTORY
