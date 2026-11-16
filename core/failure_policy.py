"""Failure provenance and bounded retries across runs, without sleeping workers."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import time

import requests
from . import cache_manager

_current = ContextVar('animeman_failure', default=None)
_CATEGORIES = {'transient', 'no_match', 'invalid_input', 'conflict'}
_IRRELEVANT = {'auth', 'max_workers', 'incremental', 'dry_run', 'tmdb_rate_limit'}


def config_fingerprint(config):
    selected = {key: value for key, value in config.items() if key not in _IRRELEVANT and not key.startswith('_')}
    from .parse_identity import RULE_VERSION
    return hashlib.sha256(json.dumps([RULE_VERSION, selected], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _same_inputs(src, entry, config):
    return (entry.get('file_fingerprint') == cache_manager.get_file_fingerprint_strong(src)
            and entry.get('config_fingerprint') == config_fingerprint(config))


def _retry_limits(config):
    policy = config.get('failure_retry', {})
    attempts = policy.get('max_attempts', 3)
    delay = policy.get('backoff_seconds', 60)
    if type(attempts) is not int or not 1 <= attempts <= 10:
        raise ValueError('failure_retry.max_attempts 必须是 1–10 的整数')
    if type(delay) not in (int, float) or not 1 <= delay <= 3600:
        raise ValueError('failure_retry.backoff_seconds 必须是 1–3600 的秒数')
    return attempts, delay


def category_for_error(error):
    if isinstance(error, (requests.Timeout, requests.ConnectionError)):
        return 'transient'
    if isinstance(error, requests.HTTPError):
        code = getattr(error.response, 'status_code', None)
        return 'transient' if code == 429 or (code is not None and code >= 500) else 'invalid_input'
    if isinstance(error, (ValueError, TypeError, FileNotFoundError, PermissionError)):
        return 'invalid_input'
    return 'transient' if isinstance(error, OSError) else 'invalid_input'


def error_summary(error):
    if isinstance(error, requests.RequestException):
        code = getattr(getattr(error, 'response', None), 'status_code', None)
        return f'{type(error).__name__}: HTTP {code}' if code is not None else f'{type(error).__name__}: 网络请求失败'
    return str(error)[:500]


@dataclass
class FailureContext:
    config: dict
    previous: dict
    category: str = None
    error: str = None


@contextmanager
def failure_scope(config, previous=None):
    state = FailureContext(config, previous or {})
    token = _current.set(state)
    try:
        yield state
    finally:
        _current.reset(token)


def note_error(error):
    state = _current.get()
    if state is not None:
        state.category = category_for_error(error)
        state.error = error_summary(error)


def make_failure(src, reason, config=None, *, previous=None, category=None, error=None, now=None):
    state = _current.get()
    config = config if config is not None else (state.config if state else {})
    previous = previous if previous is not None else (state.previous if state else {})
    category = category or (state.category if state else None) or 'no_match'
    if category not in _CATEGORIES:
        raise ValueError(f'未知失败分类: {category}')
    now = time.time() if now is None else now
    attempts = (previous.get('attempt_count', 0) if _same_inputs(src, previous, config) else 0) + 1
    maximum, delay = _retry_limits(config)
    diagnostic = error or (state.error if state else None) or reason
    safe_reason = (state.error if state else None) or reason
    return {'target':'', 'source_path':str(src.resolve()), 'media_type':'failed', 'title':src.name,
            'fingerprint':cache_manager.get_file_fingerprint(src),
            'file_fingerprint':cache_manager.get_file_fingerprint_strong(src),
            'config_fingerprint':config_fingerprint(config), 'failure_category':category,
            'attempt_count':attempts, 'failed_reason':safe_reason, 'failed_time':now,
            'last_error':diagnostic,
            'retry_after':now + min(3600, delay * 2 ** min(attempts - 1, 10)) if category == 'transient' and attempts < maximum else None,
            **({'no_retry':True} if previous.get('no_retry') is True else {})}


def should_retry(src, entry, config, *, now=None):
    if entry.get('no_retry') is True:
        return False
    if not _same_inputs(src, entry, config):
        return True
    maximum, _ = _retry_limits(config)
    after = entry.get('retry_after')
    return (entry.get('failure_category') == 'transient' and entry.get('attempt_count', 0) < maximum
            and isinstance(after, (int, float)) and (time.time() if now is None else now) >= after)
