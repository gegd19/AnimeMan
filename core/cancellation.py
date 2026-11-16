"""Per-operation cooperative cancellation with a legacy CLI signal facade."""

from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time

_current_event = ContextVar('animeman_stop_event', default=None)
_legacy_event = threading.Event()


class ProcessingCancelled(Exception):
    pass


def current_event():
    return _current_event.get() or _legacy_event


def check_cancelled():
    if current_event().is_set():
        raise ProcessingCancelled('任务已请求停止')


@contextmanager
def cancellation_scope(event):
    token = _current_event.set(event)
    try:
        yield
    finally:
        _current_event.reset(token)


def wait_for(event, timeout):
    deadline = time.monotonic() + timeout
    while not event.is_set():
        check_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        event.wait(min(0.1, remaining))
    check_cancelled()
    return True


class StopSignal:
    def set(self):
        current_event().set()
    def clear(self):
        # Managed task events cannot be revoked by nested or obsolete callers.
        if _current_event.get() is None:
            _legacy_event.clear()
    def is_set(self):
        return current_event().is_set()
    def wait(self, timeout=None):
        return current_event().wait(timeout)


stop_processing = StopSignal()
