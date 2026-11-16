"""One process-local writer lease, task identities and owned cancellation."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
import threading
import time
import uuid

from core.parse_identity import identity_scope
from core.cancellation import cancellation_scope, ProcessingCancelled
from core.logger import get_logger

task_lock = threading.RLock()
_task_id = ContextVar('animeman_task_id', default=None)
_active = None
_shutting_down = False
_shutdown_timed_out = False
_ANY_TASK = object()
current_task = {'running':False, 'status':'idle', 'task_id':None,
                'progress':0, 'total':0, 'message':'', 'log':[]}


@dataclass
class Task:
    kind: str
    config: dict = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: object = None
    done: bool = False
    synchronous: bool = False
    final_state: str = 'completed'
    result: dict = field(default_factory=dict)


def _busy():
    if _active is None:
        return False
    if not _active.done:
        return True
    return (not _active.synchronous and _active.thread is not None
            and getattr(_active.thread, 'is_alive', lambda:False)())


def try_start_task(kind, config=None, *, synchronous=False):
    global _active
    with task_lock:
        if _shutting_down or _busy():
            return None
        _active = Task(kind, deepcopy(config or {}), synchronous=synchronous)
        current_task.update(running=True, status='running', task_id=_active.task_id,
                            kind=kind, progress=0, total=0, message='准备中...', log=[], result={})
        return _active


def finish_task(task_id, *, result=None, error=None):
    with task_lock:
        if _active is None or _active.task_id != task_id:
            return False
        _active.done = True
        _active.result = result if isinstance(result, dict) else {}
        _active.final_state = ('cancelled' if _active.stop_event.is_set() else
                              'failed' if error is not None or _active.result.get('failed', 0) else 'completed')
        if error is not None:
            _active.result['error'] = str(error)
        if _active.stop_event.is_set():
            _active.result['cancelled'] = True
        current_task['result'] = deepcopy(_active.result)
        if error:
            current_task['message'] = str(error)
        elif current_task['message'] == '准备中...':
            current_task['message'] = {'completed':'操作完成','cancelled':'任务已取消','failed':'任务失败'}[_active.final_state]
        return True


@contextmanager
def task_execution(task):
    with task_lock:
        if _active is not task or task.done:
            raise ProcessingCancelled('任务身份已失效')
    token = _task_id.set(task.task_id)
    try:
        with cancellation_scope(task.stop_event), identity_scope():
            yield
    finally:
        _task_id.reset(token)


def callback_for(task_id):
    return lambda current, total, message, level='info': progress_callback(
        current, total, message, level, task_id=task_id)


def progress_callback(current, total, message, level='info', *, task_id=None):
    identity = task_id or _task_id.get()
    with task_lock:
        if _active is None or identity != _active.task_id or _active.done:
            return False
        logger = get_logger(__name__)
        getattr(logger, 'error' if level == 'error' else 'warning' if level == 'warning' else 'info')(message)
        if total > 0:
            current_task['progress'], current_task['total'] = current, total
        current_task['message'] = message
        current_task['log'].append({'msg':message, 'level':level, 'time':time.time()})
        current_task['log'] = current_task['log'][-100:]
        return True


def get_task_status():
    with task_lock:
        running = _busy()
        status = ('stopping' if _active and _active.stop_event.is_set() else 'running') if running else (_active.final_state if _active else 'idle')
        return {**deepcopy(current_task), 'running':running, 'status':status,
                'shutting_down':_shutting_down, 'shutdown_timed_out':_shutdown_timed_out,
                'log':deepcopy(current_task['log'][-30:])}


def is_task_running():
    with task_lock:
        return _busy()


def request_stop(task_id=None):
    with task_lock:
        if not _busy() or (task_id and task_id != _active.task_id):
            return False
        _active.stop_event.set()
        current_task['status'] = 'stopping'
        current_task['message'] = '正在停止，等待工作线程退出...'
        return True


def should_stop():
    with task_lock:
        identity = _task_id.get()
        return bool(_active and (identity is None or identity == _active.task_id) and _active.stop_event.is_set())


def force_reset(task_id=_ANY_TASK):
    global _active
    with task_lock:
        if task_id is not _ANY_TASK and task_id != (_active.task_id if _active else None):
            return False
        # A reserved task with no attached worker has no work to stop; launch
        # checks its identity again under this same lock before starting.
        if _active and _active.thread is not None and getattr(_active.thread, 'is_alive', lambda:not _active.done)():
            _active.stop_event.set()
            return False
        if _active and _active.synchronous and not _active.done:
            _active.stop_event.set()
            return False
        _active = None
        current_task.update(running=False, status='idle', task_id=None, kind=None,
                            progress=0, total=0, message='', result={})
        return True


def launch_task(kind, config, operation, thread_factory=threading.Thread):
    task = try_start_task(kind, config)
    if task is None:
        return None
    callback = callback_for(task.task_id)
    def worker():
        result, error = None, None
        try:
            with task_execution(task):
                if task.stop_event.is_set():
                    raise ProcessingCancelled('任务启动前已取消')
                result = operation(task.config, callback)
        except ProcessingCancelled:
            task.stop_event.set()
        except Exception as exc:
            error = str(exc)
            callback(0, 0, f'任务异常: {exc}', 'error')
        finally:
            finish_task(task.task_id, result=result, error=error)
    try:
        with task_lock:
            if _active is not task:
                return None
            task.thread = thread_factory(target=worker, daemon=False)
            task.thread.start()
    except Exception as exc:
        finish_task(task.task_id, error=exc)
        raise
    return task


def begin_shutdown():
    global _shutting_down
    with task_lock:
        _shutting_down = True
        if _busy():
            _active.stop_event.set()
            current_task['message'] = '服务停止中，等待任务退出...'


def is_shutting_down():
    with task_lock:
        return _shutting_down


def mark_shutdown_timeout():
    global _shutdown_timed_out
    with task_lock:
        _shutdown_timed_out = True


def wait_current_task(timeout=5):
    with task_lock:
        thread = _active.thread if _active else None
    if thread is not None and hasattr(thread, 'join') and thread is not threading.current_thread():
        thread.join(timeout)
        return not thread.is_alive()
    return not is_task_running()


# Legacy helpers cannot clear a live task or its stop event.
def reset_task_state():
    identity = _task_id.get()
    return finish_task(identity) if identity else force_reset()


def set_task_running():
    return try_start_task('legacy')


def clear_stop_flag():
    return None


def request_config(config_path):
    from flask import g, has_request_context
    from core import config_manager
    if has_request_context() and hasattr(g, 'request_config'):
        return deepcopy(g.request_config)
    return config_manager.load_config(config_path)
