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

