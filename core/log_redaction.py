"""Remove credential-bearing fields from diagnostic text, not requests."""
import re
from urllib.parse import unquote

_QUERY = re.compile(r'(?i)([?&;])([^=&#;\s]+)=([^&#;\s\'"<>]+)')
_USERINFO = re.compile(r'(?i)(\b(?:https?|socks5)://)[^\s/@]+@')
_AUTH = re.compile(r'''(?i)(\bauthorization[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s,;\"'}]+''')
_BEARER = re.compile(r'(?i)(\bbearer\s+)[^\s,;\'"}]+')
_SECRET_KEYS = {'api_key', 'apikey', 'token', 'access_token', 'authorization'}


def redact(value):
    text = str(value)
    def query(match):
        key = unquote(match.group(2)).casefold()
        if key in _SECRET_KEYS:
            return match.group(1) + match.group(2) + '=[REDACTED]'
        return match.group(0)
    text = _QUERY.sub(query, text)
    text = _USERINFO.sub(r'\1[REDACTED]@', text)
    text = _AUTH.sub(r'\1[REDACTED]', text)
    return _BEARER.sub(r'\1[REDACTED]', text)
