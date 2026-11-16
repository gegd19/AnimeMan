"""One-process Waitress lifecycle. Grace expiry reports; it never kills writers."""
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import signal
import tempfile
import threading
import time

from core.process_lock import process_guard
from core.runtime_paths import cache_file
from core.validation import MAX_JSON_BYTES, query_integer, number, string

logger=logging.getLogger('animeman.server')


@dataclass(frozen=True)
class ServerOptions:
    host:str='127.0.0.1'
    port:int=8000
    threads:int=8
    shutdown_grace:float=30
    work_dir:str|None=None

    @classmethod
    def from_environment(cls,environ=None):
        env=os.environ if environ is None else environ
        for key in ('WEB_CONCURRENCY','ANIMEMAN_WORKERS'):
            if env.get(key,'1')!='1':raise ValueError('仅支持一个应用进程；禁止多个 worker')
        host=string(env.get('ANIMEMAN_HOST','127.0.0.1'),'ANIMEMAN_HOST',maximum=255)
        port=query_integer(env.get('ANIMEMAN_PORT','8000'),'ANIMEMAN_PORT',0,65535)
        threads=query_integer(env.get('ANIMEMAN_THREADS','8'),'ANIMEMAN_THREADS',1,64)
        try:grace=float(env.get('ANIMEMAN_SHUTDOWN_GRACE','30'))
        except ValueError as error:raise ValueError('ANIMEMAN_SHUTDOWN_GRACE 必须为秒数') from error
        number(grace,'ANIMEMAN_SHUTDOWN_GRACE',0.01,3600)
        work=env.get('ANIMEMAN_WORK_PATH') or env.get('TMPDIR')
        if work:string(work,'ANIMEMAN_WORK_PATH')
        return cls(host,port,threads,grace,work)


def drain_server(server,socket_map,grace):
    from waitress import wasyncore
    from web import task_state
    task_state.begin_shutdown()
    deadline=time.monotonic()+grace
    listeners=[value for value in list(socket_map.values()) if getattr(value,'accepting',False)]
    for listener in listeners:listener.close()
    if not listeners:server.close()
    dispatcher=server.task_dispatcher
    dispatcher.shutdown(cancel_pending=True,timeout=grace)
    timed_out=False
    try:
        while task_state.is_task_running() or bool(dispatcher.threads):
            if not timed_out and time.monotonic()>=deadline:
                timed_out=True;task_state.mark_shutdown_timeout()
                logger.error('shutdown_timeout: 超过停机宽限，继续等待写线程，不强制退出')
            if socket_map:wasyncore.loop(timeout=0.05,map=socket_map,count=1)
            task_state.wait_current_task(0.05)
            if not socket_map:threading.Event().wait(0.01)
    finally:
        wasyncore.close_all(socket_map)
    logger.info('shutdown_complete: 所有任务与 HTTP 线程已退出')
    return 1 if timed_out else 0


def serve(app=None,options=None,*,on_ready=None):
    from waitress.server import create_server
    from waitress import wasyncore
    options=options or ServerOptions.from_environment()
    socket_map={};stop=threading.Event();previous={}
    lock=cache_file('.animeman-server.lock',check_legacy=False)
    with process_guard(lock):
        work=Path(options.work_dir) if options.work_dir else cache_file('work',check_legacy=False)
        work.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=work):pass
        tempfile.tempdir=str(work)
        if app is None:
            from web import create_app
            app=create_app()
        app.debug=False
        server=create_server(app,map=socket_map,host=options.host,port=options.port,threads=options.threads,
            asyncore_loop_timeout=0.1,max_request_body_size=MAX_JSON_BYTES,clear_untrusted_proxy_headers=True)
        def request_shutdown(signum,frame):stop.set()
        for signum in (signal.SIGINT,signal.SIGTERM):
            previous[signum]=signal.signal(signum,request_shutdown)
        try:
            port=getattr(server,'effective_port',options.port)
            logger.info('Serving one application process pid=%s threads=%s at %s:%s',os.getpid(),options.threads,options.host,port)
            if on_ready:on_ready(server)
            while not stop.is_set():wasyncore.loop(timeout=0.1,map=socket_map,count=1)
        finally:
            try:code=drain_server(server,socket_map,options.shutdown_grace)
            finally:
                for signum,handler in previous.items():signal.signal(signum,handler)
        return code


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try:return serve()
    except (OSError,ValueError):
        logger.exception('服务启动/运行失败')
        return 1
