"""T15: process ownership and graceful draining, using only temporary state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
import subprocess
import sys

import pytest


def test_live_production_http_lifecycle():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'tools/deployment_smoke.py')],
        cwd=root,text=True,capture_output=True,timeout=60)
    assert result.returncode==0, result.stdout+'\n'+result.stderr


@pytest.mark.parametrize('key,value', [('WEB_CONCURRENCY','2'),('ANIMEMAN_WORKERS','2'),
    ('ANIMEMAN_THREADS','0'),('ANIMEMAN_THREADS','65'),('ANIMEMAN_PORT','-1'),
    ('ANIMEMAN_PORT','abc'),('ANIMEMAN_SHUTDOWN_GRACE','0')])
def test_invalid_runtime_settings_refuse_startup(key,value):
    from server_runtime import ServerOptions
    with pytest.raises(ValueError):ServerOptions.from_environment({key:value})


def test_runtime_defaults_are_single_process_and_threaded():
    from server_runtime import ServerOptions
    options=ServerOptions.from_environment({})
    assert options.host=='127.0.0.1' and options.port==8000
    assert options.threads==8 and options.shutdown_grace==30


def test_process_guard_is_exclusive_and_never_truncates_other_owner(tmp_path):
    from core.process_lock import process_guard, ProcessAlreadyRunning
    path=tmp_path/'owner.lock'
    with process_guard(path):
        before=path.read_bytes()
        with pytest.raises(ProcessAlreadyRunning):
            with process_guard(path):pytest.fail('second owner admitted')
        assert path.read_bytes()==before
    with process_guard(path):pass
    assert path.exists()  # Retaining the lock inode avoids an unlink/reopen race.


def test_process_guard_does_not_overwrite_an_unknown_file(tmp_path):
    from core.process_lock import process_guard
    path=tmp_path/'owner.lock';path.write_bytes(b'keep original data')
    with pytest.raises(OSError):
        with process_guard(path):pytest.fail('unknown owner file overwritten')
    assert path.read_bytes()==b'keep original data'


def test_process_guard_refuses_symlinks(tmp_path):
    from core.process_lock import process_guard
    source=tmp_path/'original';source.write_bytes(b'protected')
    lock=tmp_path/'owner.lock';lock.symlink_to(source)
    with pytest.raises(OSError):
        with process_guard(lock):pytest.fail('followed an owner-lock symlink')
    assert source.read_bytes()==b'protected' and lock.is_symlink()


def test_cli_acquires_guard_before_any_config_creation(tmp_path,monkeypatch):
    import main
    from core.process_lock import process_guard, ProcessAlreadyRunning
    from core.runtime_paths import cache_file
    touched=[]
    def load(*args,**kwargs):
        touched.append(True)
        return {'tmdb_api':{'api_key':''}}
    monkeypatch.setattr(main,'load_config',load)
    monkeypatch.setattr(sys,'argv',['main.py','--test-tmdb','--config',str(tmp_path/'missing.json')])
    with process_guard(cache_file('.animeman-server.lock',check_legacy=False)):
        with pytest.raises(ProcessAlreadyRunning):main.main()
    assert touched==[] and not (tmp_path/'missing.json').exists()


def test_shutdown_latch_blocks_new_writes_even_after_force_reset(client,config_file,monkeypatch):
    from web import task_state
    monkeypatch.setattr(task_state,'_shutting_down',False,raising=False)
    monkeypatch.setattr(task_state,'_shutdown_timed_out',False,raising=False)
    task=task_state.try_start_task('held',synchronous=True)
    before=config_file.read_bytes()
    try:
        task_state.begin_shutdown()
        assert task.stop_event.is_set()
        assert client.post('/api/config',auth=('test-user','test-pass'),json={'max_workers':2}).status_code==503
        assert config_file.read_bytes()==before
        assert client.get('/healthz').status_code==200
        assert task_state.try_start_task('new') is None
        task_state.finish_task(task.task_id)
        assert task_state.force_reset()
        assert task_state.try_start_task('new') is None
    finally:
        task_state.finish_task(task.task_id)
        task_state.force_reset()


def test_grace_expiry_reports_then_waits_for_writer_and_keeps_committed_data(tmp_path,monkeypatch):
    from server_runtime import drain_server
    from web import task_state
    from core import cache_manager
    from core.cancellation import check_cancelled
    monkeypatch.setattr(task_state,'_shutting_down',False,raising=False)
    monkeypatch.setattr(task_state,'_shutdown_timed_out',False,raising=False)
    started=threading.Event();release=threading.Event()
    def work(cfg,callback):
        cache_manager.update_records({'committed':{'media_type':'movie','title':'saved'}})
        started.set()
        assert release.wait(5)
        check_cancelled()
    class Dispatcher:
        threads=set()
        def shutdown(self,**kwargs):pass
    class Server:
        task_dispatcher=Dispatcher()
        def close(self):pass
    task=task_state.launch_task('probe',{},work)
    try:
        assert started.wait(3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(drain_server,Server(),{},0.05)
            deadline=time.monotonic()+3
            while not task_state.get_task_status().get('shutdown_timed_out') and time.monotonic()<deadline:
                threading.Event().wait(0.01)
            assert task_state.get_task_status()['shutdown_timed_out'] is True
            assert not result.done()  # Grace expiry must not kill the writer.
            assert cache_manager.load_cache()['committed']['title']=='saved'
            release.set()
            assert result.result(timeout=3)==1
    finally:
        release.set();task_state.wait_current_task(3);task_state.force_reset()
