"""T06 deterministic scheduling: Events/Barriers, never random sleeps."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading

import pytest

AUTH = ('test-user', 'test-pass')


def test_atomic_start_has_one_winner():
    from web import task_state
    gate = threading.Barrier(2)
    def reserve(_):
        gate.wait(timeout=5)
        return task_state.try_start_task('test')
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = list(pool.map(reserve, range(2)))
        assert sum(token is not None for token in tokens) == 1
    finally:
        task_state.force_reset()


def test_force_reset_cannot_release_a_live_worker(client, monkeypatch):
    from web import routes_task, task_state
    started, release = threading.Event(), threading.Event()
    def processor(*args, **kwargs):
        started.set()
        assert release.wait(5)
    monkeypatch.setattr(routes_task.media_processor, 'run_processor_with_callback', processor)
    try:
        first = client.post('/api/run', auth=AUTH)
        assert first.status_code == 200 and started.wait(5)
        reset = client.post('/api/stop?force=1', auth=AUTH)
        assert reset.status_code == 409
        assert task_state.get_task_status()['status'] == 'stopping'
        assert client.post('/api/run', auth=AUTH).status_code == 409
    finally:
        release.set()
        task_state.wait_current_task(5)
        task_state.force_reset()


def test_stale_callbacks_and_completion_do_not_change_new_task():
    from web import task_state
    old = task_state.try_start_task('old')
    try:
        callback = task_state.callback_for(old.task_id)
        task_state.finish_task(old.task_id)
        new = task_state.try_start_task('new')
        assert new is not None
        callback(5, 5, 'obsolete result', 'success')
        task_state.finish_task(old.task_id)
        status = task_state.get_task_status()
        assert status['task_id'] == new.task_id and status['running']
        assert 'obsolete result' not in str(status)
    finally:
        task_state.force_reset()


def test_worker_uses_request_time_config_snapshot(client, config_file, monkeypatch):
    from web import routes_task, task_state
    workers, captured = [], []
    class QueuedThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            workers.append(self.target)
    monkeypatch.setattr(routes_task.threading, 'Thread', QueuedThread)
    monkeypatch.setattr(routes_task.media_processor, 'run_processor_with_callback',
                        lambda *a, **k: captured.append(k['effective_config']['max_workers']))
    try:
        assert client.post('/api/run', auth=AUTH).status_code == 200
        saved = json.loads(config_file.read_text())
        saved['max_workers'] = 9
        config_file.write_text(json.dumps(saved))
        workers[0]()
        assert captured == [3]
    finally:
        task_state.force_reset()


@pytest.mark.parametrize('endpoint,payload', [
    ('/api/media/delete', {'src_path':'dummy'}),
    ('/api/media/batch_delete', {'src_paths':['dummy']}),
    ('/api/processed_cache/clear', {}),
    ('/api/processed_cache/delete', {'src_path':'dummy'}),
    ('/api/processed_cache/batch_delete', {'src_paths':['dummy']}),
    ('/api/failed_cache/clear', {}),
    ('/api/subtitle/execute', {'items':[]}),
    ('/api/subtitle/batch_rename', {'renames':[]}),
    ('/api/offline/scan', {}),
    ('/api/offline/parse', {}),
    ('/api/media/refresh_poster_cache', {}),
])
def test_mutating_requests_conflict_with_reserved_task(endpoint, payload, client):
    from web import task_state
    token = task_state.try_start_task('reserved')
    try:
        assert token is not None
        response = client.post(endpoint, json=payload, auth=AUTH)
        assert response.status_code == 409
        assert client.get('/api/status', auth=AUTH).status_code == 200
        assert client.post('/api/config', json={'max_workers':2}, auth=AUTH).status_code == 200
    finally:
        task_state.force_reset()


def test_cancel_during_scan_does_not_submit_work(config_file, tmp_path, monkeypatch):
    from core import processor_runner, config_manager
    from core.cancellation import cancellation_scope
    config = config_manager.load_config(config_file)
    config['source_folders'] = [str(tmp_path)]
    config_manager.save_config(config, config_file)
    stopped = threading.Event()
    def scan(*args):
        stopped.set()
        return [tmp_path / 'dummy.mkv']
    monkeypatch.setattr(processor_runner, '_scan_video_files', scan)
    monkeypatch.setattr(processor_runner, 'process_video', lambda *a: pytest.fail('submitted after scan cancellation'))
    with cancellation_scope(stopped):
        result = processor_runner.run_processor_with_callback(str(config_file), lambda *a: None)
    assert result['cancelled'] is True and result['success'] == 0


@pytest.mark.parametrize('stop_point', ['stage', 'publish'])
def test_cancel_before_publication_keeps_old_target_and_cache(stop_point, config_file, tmp_path, monkeypatch):
    from core import config_manager, cache_manager, nfo_writer, tmdb_client
    from core.cancellation import cancellation_scope, ProcessingCancelled
    from core.library_transaction import reprocess_safely
    from core.processor_manual import process_video_with_manual_correction
    config = config_manager.load_config(config_file)
    config.update(download_images=False)
    config['subtitle'] = {'enabled':False}
    src = tmp_path / 'source' / 'input.mkv'
    src.parent.mkdir()
    src.write_bytes(b'original')
    config['source_folders'] = [str(src.parent)]
    old = Path(config['movie_target_folder']) / 'Old' / 'Old.mkv'
    old.parent.mkdir(parents=True)
    old.hardlink_to(src)
    cache_manager.save_cache({str(src):{'target':str(old),'media_type':'movie'}})
    original = Path(cache_manager.CACHE_FILE).read_bytes()
    stopped = threading.Event()
    monkeypatch.setattr(tmdb_client, 'get_tmdb_details', lambda *a, **k:{'title':'New'})
    actual = nfo_writer.write_movie_nfo
    def stage_then_stop(*a, **k):
        actual(*a, **k)
        stopped.set()
    if stop_point == 'stage':
        monkeypatch.setattr(nfo_writer, 'write_movie_nfo', stage_then_stop)
    else:
        import os
        actual_link = os.link
        def publish_then_stop(src, dst, *a, **k):
            actual_link(src, dst, *a, **k)
            if '.animeman-stage-' not in str(dst):
                stopped.set()
        monkeypatch.setattr(os, 'link', publish_then_stop)
    with cancellation_scope(stopped), pytest.raises(ProcessingCancelled):
        reprocess_safely(src, config, lambda c, d: process_video_with_manual_correction(src,c,d,1,'movie',1,1))
    assert old.read_bytes() == b'original'
    assert Path(cache_manager.CACHE_FILE).read_bytes() == original
    assert not (Path(config['movie_target_folder'])/'New'/'New.mkv').exists()


def test_runner_drains_completed_results_and_limits_queue(config_file, tmp_path, monkeypatch):
    from core import processor_runner, config_manager, cache_manager
    from core.cancellation import cancellation_scope
    config = config_manager.load_config(config_file)
    config.update(source_folders=[str(tmp_path)], max_workers=1)
    config_manager.save_config(config, config_file)
    files = [tmp_path/f'episode-{i}.mkv' for i in range(20)]
    stopped = threading.Event()
    submitted = []
    actual_executor = processor_runner.ThreadPoolExecutor
    class RecordingExecutor(actual_executor):
        def submit(self, *a, **k):
            submitted.append(1)
            return super().submit(*a, **k)
    monkeypatch.setattr(processor_runner, 'ThreadPoolExecutor', RecordingExecutor)
    monkeypatch.setattr(processor_runner, '_scan_video_files', lambda *a: files)
    def process(src, cfg, result, log):
        result[str(src)] = {'target':'temporary-target','media_type':'movie'}
        stopped.set()
        return True
    monkeypatch.setattr(processor_runner, 'process_video', process)
    with cancellation_scope(stopped):
        result = processor_runner.run_processor_with_callback(str(config_file), lambda *a:None)
    assert len(submitted) <= 2
    assert result['cancelled'] is True and result['success'] >= 1
    assert cache_manager.load_cache()


@pytest.mark.parametrize('endpoint,module_name,operation', [
    ('/api/offline/scan', 'routes_offline', 'scan_source_folders'),
    ('/api/offline/parse', 'routes_offline', 'run_ai_preparse'),
    ('/api/media/refresh_poster_cache', 'routes_config', '_scan_all_posters'),
])
def test_background_writers_own_lease_until_exit(endpoint, module_name, operation, client, config_file, monkeypatch):
    import importlib
    from web import task_state
    from core.cancellation import check_cancelled
    module = importlib.import_module('web.' + module_name)
    cfg = json.loads(config_file.read_text())
    cfg['ai_parser'].update(enabled=True, api_key='dummy-ai-key')
    config_file.write_text(json.dumps(cfg))
    started, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(5)
        check_cancelled()
        return {}
    monkeypatch.setattr(module, operation, blocked)
    try:
        response = client.post(endpoint, auth=AUTH)
        assert response.status_code == 200 and started.wait(5)
        assert response.json['task_id']
        assert client.post('/api/run', auth=AUTH).status_code == 409
        assert client.post('/api/stop', auth=AUTH).json['status'] == 'stopping'
        assert task_state.get_task_status()['running']
    finally:
        release.set()
        task_state.wait_current_task(5)
        status = task_state.get_task_status()
        task_state.force_reset()
    assert status['status'] == 'cancelled'
    if module_name == 'routes_offline':
        assert not module._scan_status['running'] and not module._parse_status['running']
    else:
        assert not module._refresh_running


def test_failed_worker_retains_error_and_releases_lease():
    from web import task_state
    def failure(*args):
        raise RuntimeError('isolated failure')
    try:
        task_state.launch_task('failure', {}, failure)
        assert task_state.wait_current_task(5)
        state = task_state.get_task_status()
        assert not state['running'] and state['status'] == 'failed'
        assert 'isolated failure' in state['message']
        assert task_state.try_start_task('next')
    finally:
        task_state.force_reset()


def test_thread_start_failure_releases_reservation():
    from web import task_state
    class BrokenThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError('start failed')
        def is_alive(self):
            return False
    try:
        with pytest.raises(RuntimeError, match='start failed'):
            task_state.launch_task('broken', {}, lambda *a:None, thread_factory=BrokenThread)
        assert task_state.get_task_status()['status'] == 'failed'
        assert task_state.try_start_task('next')
    finally:
        task_state.force_reset()


def test_stale_stop_identity_cannot_reset_or_cancel_new_task(client):
    from web import task_state
    old = task_state.try_start_task('old')
    task_state.finish_task(old.task_id)
    new = task_state.try_start_task('new')
    try:
        response = client.post('/api/stop?force=1&task_id='+old.task_id, auth=AUTH)
        assert response.status_code == 409
        assert task_state.get_task_status()['task_id'] == new.task_id
        assert not new.stop_event.is_set()
    finally:
        task_state.force_reset()


def test_synchronous_writer_holds_lease_while_stopping(app, config_file, tmp_path, monkeypatch):
    from web import routes_subtitle, task_state
    started, release = threading.Event(), threading.Event()
    def blocked(*a, **k):
        started.set()
        assert release.wait(5)
        return {'success':0,'failed':0}
    monkeypatch.setattr(routes_subtitle.subtitle_handler, 'batch_rename_subtitles', blocked)
    config = json.loads(config_file.read_text())
    config['source_folders'] = [str(tmp_path)]
    config_file.write_text(json.dumps(config))
    def request_write():
        return app.test_client().post('/api/subtitle/batch_rename', json={'renames':[{'old_path':str(tmp_path/'a.srt'), 'new_path':str(tmp_path/'b.srt')}]}, auth=AUTH)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(request_write)
            try:
                assert started.wait(5)
                assert app.test_client().post('/api/stop?force=1', auth=AUTH).status_code == 409
                assert app.test_client().post('/api/run', auth=AUTH).status_code == 409
            finally:
                release.set()
            assert future.result().status_code == 200
        assert task_state.get_task_status()['status'] == 'cancelled'
    finally:
        task_state.force_reset()


def test_cancel_interrupts_folder_wait_without_losing_other_owner(tmp_path, monkeypatch):
    from core import parser_manager
    from core.cancellation import cancellation_scope, ProcessingCancelled
    owner, stopped = threading.Event(), threading.Event()
    key = str(tmp_path.resolve())
    monkeypatch.setitem(parser_manager._ongoing_folder_parses, key, owner)
    stopped.set()
    with cancellation_scope(stopped), pytest.raises(ProcessingCancelled):
        parser_manager._get_or_wait_folder_parse(tmp_path, {}, None)
    assert parser_manager._ongoing_folder_parses[key] is owner


def test_http_run_race_has_one_winner(app, monkeypatch):
    from web import routes_task, task_state
    gate = threading.Barrier(2)
    release = threading.Event()
    monkeypatch.setattr(routes_task.media_processor, 'run_processor_with_callback', lambda *a, **k:release.wait(5))
    def run(_):
        gate.wait(timeout=5)
        return app.test_client().post('/api/run', json={}, auth=AUTH).status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(run, range(2))) == [200,409]
    finally:
        release.set()
        task_state.wait_current_task(5)
        task_state.force_reset()


def test_done_flag_does_not_release_a_thread_still_in_finally(monkeypatch):
    from web import task_state
    finished, release = threading.Event(), threading.Event()
    original = task_state.finish_task
    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        finished.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(task_state, 'finish_task', delayed)
    try:
        task_state.launch_task('test', {}, lambda *a:{'success':1,'failed':0})
        assert finished.wait(5)
        assert task_state.get_task_status()['running']
        assert task_state.try_start_task('too early') is None
        assert not task_state.force_reset()
    finally:
        release.set()
        task_state.wait_current_task(5)
        task_state.force_reset()


def test_cancel_after_one_batch_delete_saves_that_change(client, config_file, tmp_path, monkeypatch):
    from core import cache_manager
    from core.cancellation import current_event
    from web import routes_media, task_state
    config = json.loads(config_file.read_text())
    config['source_folders'] = [str(tmp_path/'source')]
    config_file.write_text(json.dumps(config))
    entries = {}
    targets = []
    for i in range(2):
        src = tmp_path/'source'/f'{i}.mkv'
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(b'original')
        dst = Path(config['movie_target_folder'])/str(i)/src.name
        dst.parent.mkdir(parents=True)
        dst.hardlink_to(src)
        targets.append(dst)
        entries[str(src)] = {'target':str(dst),'media_type':'movie'}
    cache_manager.save_cache(entries)
    actual = routes_media._remove
    def remove_then_stop(*a, **k):
        actual(*a, **k)
        current_event().set()
    monkeypatch.setattr(routes_media, '_remove', remove_then_stop)
    try:
        response = client.post('/api/media/batch_delete', json={'src_paths':list(entries)}, auth=AUTH)
        remaining = cache_manager.load_cache()
        assert list(remaining) == [list(entries)[1]]
        assert not targets[0].exists() and targets[1].exists()
        assert all(Path(src).read_bytes() == b'original' for src in entries)
        assert response.json['status'] == 'cancelled'
        assert response.json['success'] == 1
    finally:
        task_state.force_reset()


def test_old_stop_event_cannot_be_cleared_or_affect_new_task():
    from web import task_state
    from core.cancellation import cancellation_scope, stop_processing
    old = task_state.try_start_task('old')
    task_state.request_stop(old.task_id)
    task_state.finish_task(old.task_id)
    try:
        new = task_state.try_start_task('new')
        with cancellation_scope(old.stop_event):
            stop_processing.clear()
        assert old.stop_event.is_set() and not new.stop_event.is_set()
        assert not task_state.request_stop(old.task_id)
        assert not task_state.force_reset(old.task_id)
        assert task_state.get_task_status()['task_id'] == new.task_id
    finally:
        task_state.force_reset()


def test_batch_correction_keeps_counts_when_next_item_is_cancelled(client, config_file, tmp_path, monkeypatch):
    from web import routes_failed, task_state
    from core.cancellation import ProcessingCancelled, current_event
    config = json.loads(config_file.read_text())
    config['source_folders'] = [str(tmp_path)]
    config_file.write_text(json.dumps(config))
    files = [tmp_path/f'{i}.mkv' for i in range(2)]
    for file in files:
        file.write_bytes(b'original')
    calls = []
    def reprocess(*a):
        calls.append(1)
        if len(calls) == 2:
            current_event().set()
            raise ProcessingCancelled('cancel second')
        return True, None
    monkeypatch.setattr(routes_failed, 'reprocess_safely', reprocess)
    try:
        response = client.post('/api/failed_cache/batch_correct', json={'src_paths':list(map(str,files)),
                                'tmdb_id':1,'media_type':'movie','season':1}, auth=AUTH)
        assert response.status_code == 200
        assert task_state.wait_current_task(5)
        state = task_state.get_task_status()
        assert state['status'] == 'cancelled'
        assert state['result']['success'] == 1 and state['result']['failed'] == 0
        assert state['result']['completed'] == 1
    finally:
        task_state.force_reset()


def test_cancelled_ai_call_never_starts_a_network_request(monkeypatch):
    from core import ai_client
    from core.cancellation import cancellation_scope, ProcessingCancelled
    class Session:
        def post(self, *a, **k):
            pytest.fail('AI request started after cancellation')
    monkeypatch.setattr(ai_client, 'create_session', lambda:Session())
    stopped = threading.Event()
    stopped.set()
    with cancellation_scope(stopped), pytest.raises(ProcessingCancelled):
        ai_client.call_ai_api_with_messages([], {'api_key':'dummy-ai-key'}, None)
