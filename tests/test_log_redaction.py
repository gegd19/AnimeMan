import pytest

@pytest.mark.parametrize('message', [
    'https://api.example/3/tv/1?api_key=SENTINEL_KEY&language=zh-CN&API_KEY=SENTINEL_KEY',
    'https://api.example/3/tv/1?api%5Fkey=SENTINEL_KEY&access_token=SENTINEL_KEY',
    'Authorization: Bearer SENTINEL_KEY',
    'proxy http://user:SENTINEL_KEY@127.0.0.1:7890',
    'https://user:SENTINEL_KEY@api.example/v1?token=SENTINEL_KEY',
])
def test_secret_formatter(message):
    from core.log_redaction import redact
    result = redact(message)
    assert 'SENTINEL_KEY' not in result
    assert 'REDACTED' in result


def test_secret_formatter_preserves_diagnostics():
    from core.log_redaction import redact
    result = redact('SSLError https://api.example/3/tv/1?api_key=SENTINEL_KEY&language=zh-CN HTTP 429')
    assert all(item in result for item in ('SSLError', 'api.example', '/3/tv/1', 'language=zh-CN', '429'))



def test_tmdb_error_and_proxy_do_not_leak(monkeypatch, capsys):
    import requests
    from core import tmdb_client
    seen = []
    session = tmdb_client.create_session('http://u:SENTINEL_KEY@127.0.0.1:7890')
    assert session.proxies['https'].endswith('@127.0.0.1:7890')
    assert 'SENTINEL_KEY' not in capsys.readouterr().out
    def fail(*args, **kwargs):
        assert kwargs['params']['api_key'] == 'SENTINEL_KEY'
        raise requests.exceptions.SSLError('SSLError https://api.example/tv/1?api_key=SENTINEL_KEY')
    monkeypatch.setattr(session, 'get', fail)
    monkeypatch.setattr(tmdb_client, 'create_session', lambda *a, **k: session)
    monkeypatch.setattr(tmdb_client._tmdb_limiter, 'wait', lambda: None)
    assert tmdb_client.get_tmdb_details('tv', 1, 'SENTINEL_KEY', log_func=lambda msg, level: seen.append(msg)) is None
    assert seen and 'SENTINEL_KEY' not in str(seen)
    assert 'SSLError' in str(seen)


def test_traceback_and_cached_reason_are_redacted(tmp_path):
    from core.logger import get_logger
    from core.failure_policy import make_failure
    from core.runtime_paths import log_file
    src = tmp_path / 'synthetic.mkv'
    src.write_bytes(b'test')
    logger = get_logger()
    try:
        raise ValueError('https://api.example/tv?api_key=SENTINEL_KEY')
    except ValueError:
        logger.exception('request failed')
    for handler in logger.handlers:
        handler.flush()
    assert 'SENTINEL_KEY' not in log_file().read_text()
    entry = make_failure(src, 'request https://api.example?api_key=SENTINEL_KEY', {})
    assert 'SENTINEL_KEY' not in str(entry)


def test_authorization_json_and_encoded_secret():
    from core.log_redaction import redact
    for text in ['{"Authorization": "Bearer SENTINEL_KEY"}',
                 'https://example.test?access%5Ftoken=SENTINEL%5FKEY&x=1']:
        result = redact(text)
        assert 'SENTINEL' not in result
        assert 'REDACTED' in result


def test_ai_callback_hides_error(monkeypatch):
    import requests
    from core import ai_client
    class Session:
        def post(self, *a, **kw):
            assert kw['headers']['Authorization'] == 'Bearer SENTINEL_KEY'
            raise requests.exceptions.SSLError('failed Authorization: Bearer SENTINEL_KEY')
    monkeypatch.setattr(ai_client, 'create_session', lambda: Session())
    messages = []
    assert ai_client.call_ai_api('test', {'provider': 'openai', 'api_key': 'SENTINEL_KEY'}, lambda msg, level: messages.append(msg)) is None
    assert 'SENTINEL_KEY' not in str(messages)
    assert 'SSLError' in str(messages) or 'failed' in str(messages)
