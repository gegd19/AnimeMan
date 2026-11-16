"""A scoped preview flag; worker contexts must be propagated explicitly."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import signature

_preview = ContextVar("animeman_preview", default=False)


def is_preview(config=None):
    return _preview.get() or bool(config and config.get("dry_run"))


@contextmanager
def preview_mode(enabled):
    token = _preview.set(_preview.get() or bool(enabled))
    try:
        yield
    finally:
        _preview.reset(token)


def execution_scope(function):
    parameters = signature(function)
    @wraps(function)
    def wrapped(*args, **kwargs):
        config = parameters.bind_partial(*args, **kwargs).arguments.get("config")
        with preview_mode(is_preview(config)):
            return function(*args, **kwargs)
    return wrapped


def skip_preview_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if is_preview():
            return None
        return function(*args, **kwargs)
    return wrapped
