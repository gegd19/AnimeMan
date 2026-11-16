"""Bound recognition AI calls per file or standalone folder operation."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import threading


class AIBudgetExceeded(Exception):
    pass


_current = ContextVar('recognition_ai_budget', default=None)


@contextmanager
def recognition_budget_scope(limit=3):
    existing = _current.get()
    if existing is not None:
        yield existing
        return
    if type(limit) is not int or limit < 1:
        raise ValueError('AI budget must be a positive integer')
    state = {'remaining': limit, 'lock': threading.Lock()}
    token = _current.set(state)
    try:
        yield state
    finally:
        _current.reset(token)


def consume_recognition_call():
    state = _current.get()
    if state is None:
        return
    with state['lock']:
        if state['remaining'] <= 0:
            raise AIBudgetExceeded('AI 调用预算已耗尽，需要人工确认')
        state['remaining'] -= 1


def with_recognition_budget(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with recognition_budget_scope():
            return function(*args, **kwargs)
    return wrapped
