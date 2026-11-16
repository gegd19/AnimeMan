"""Test-only process: real HTTP/server/runner/transactions, no external APIs."""
import json
import logging
import os
from pathlib import Path
import socket
import time

import requests


def no_api(*args, **kwargs):
    raise AssertionError('AI/TMDB/network requests must be mocked')


requests.sessions.Session.request = no_api
original_connect = socket.socket.connect


def loopback_only(self, address):
    if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1'):
        raise AssertionError('Deployment probes only permit loopback connections')
    return original_connect(self, address)


socket.socket.connect = loopback_only
socket.socket.connect_ex = no_api

from core import processor_runner
from core.cancellation import check_cancelled
from core.file_linker import create_link
from core.library_transaction import transactional_media
from server_runtime import serve

control = Path(os.environ['PROBE_CONTROL'])
source = Path(os.environ['PROBE_SOURCE'])


@transactional_media
def fake_process(src, config, cache, callback):
    if src.name == 'second.mkv':
        (control / 'waiting').write_text('writer waiting', encoding='utf-8')
        while not (control / 'release').exists():
            if os.environ.get('PROBE_MODE') != 'stubborn':
                check_cancelled()
            time.sleep(0.02)
        check_cancelled()
    target = Path(config['movie_target_folder']) / 'Probe' / src.name
    assert create_link(src, target, 'symlink')
    cache[str(src.resolve())] = {'media_type':'movie', 'tmdb_id':1,
        'title':'Probe', 'target':str(target)}
    return True


processor_runner.process_video = fake_process
# Stable scan order is necessary to prove the first commit precedes cancellation.
original_scan = processor_runner._scan_video_files
processor_runner._scan_video_files = lambda root, cfg: sorted(original_scan(root, cfg))


def ready(server):
    try:
        with (source / 'first.mkv').open('r+b'):
            readonly = False
    except PermissionError:
        readonly = True
    except OSError as error:
        import errno
        if error.errno != errno.EROFS:
            raise
        readonly = True
    (control / 'ready').write_text(json.dumps({'port':int(server.effective_port),
        'pid':os.getpid(), 'source_readonly':readonly}), encoding='utf-8')


logging.basicConfig(level=logging.INFO)
raise SystemExit(serve(on_ready=ready))
