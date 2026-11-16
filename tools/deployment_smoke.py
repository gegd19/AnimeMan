"""Exercise production entry/lifecycle with disposable, synthetic media only.

Run with the current Python, or --docker IMAGE. Docker mode requires an already
built image and never mounts any user configuration or media.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def eventually(check, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.04)
    raise AssertionError('timed out waiting for probe state')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--docker', metavar='IMAGE')
    args = parser.parse_args()
    docker = bool(args.docker)
    def dc(*argv, **kwargs):
        return subprocess.run(['docker', *argv], check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout.strip()
    if docker:
        assert dc('image', 'inspect', args.docker, '--format', '{{.Config.User}}') not in ('', '0', '0:0', 'root')
        dc('run', '--rm', '--entrypoint', 'python', args.docker, '-c',
            "from pathlib import Path; assert not any(Path('/app').glob('*.json')); "
            "assert not Path('/app/.git').exists(); assert not Path('/app/tests').exists(); "
            "assert not Path('/app/.env').exists(); assert not Path('/app/build-context-secret.txt').exists(); "
            "assert all(p.suffix in ('.py','.html','.js','.css') for p in Path('/app').rglob('*') if p.is_file())")
    for mode in ('cooperative', 'stubborn'):
        with tempfile.TemporaryDirectory(prefix='animeman-deploy-') as directory:
            root = Path(directory)
            root.chmod(0o755)
            for name in ('config','cache','logs','work','control','source','tv','movies'):
                (root/name).mkdir(); (root/name).chmod(0o777)
            for name in ('first.mkv','second.mkv'):
                (root/'source'/name).write_bytes(b'synthetic media, not a valid video\n')
                (root/'source'/name).chmod(0o444)
            original = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'source').iterdir()}
            base = Path('/probe-data') if docker else root
            config = {'auth':{'enabled':True,'username':'test-user','password':'test-pass'},
                'source_folders':[str(base/'source')], 'tv_target_folder':str(base/'tv'),
                'movie_target_folder':str(base/'movies'), 'video_extensions':['.mkv'],
                'ignore_patterns':[], 'special_mappings':[], 'max_workers':1,
                'download_images':False, 'incremental':True,
                'tmdb_api':{'api_key':'dummy-tmdb-key'}, 'ai_parser':{'enabled':False,'api_key':''},
                'subtitle':{'enabled':False}}
            (root/'config/auto_config.json').write_text(json.dumps(config), encoding='utf-8')
            (root/'config/auto_config.json').chmod(0o666)
            env = {'CONFIG_PATH':str(base/'config/auto_config.json'), 'CACHE_PATH':str(base/'cache'),
                'LOG_PATH':str(base/'logs'), 'ANIMEMAN_WORK_PATH':str(base/'work'),
                'TMPDIR':str(base/'work'), 'SECRET_KEY':'test-only-not-a-real-key',
                'ANIMEMAN_HOST':'0.0.0.0' if docker else '127.0.0.1',
                'ANIMEMAN_PORT':'8000' if docker else '0', 'ANIMEMAN_THREADS':'4',
                'ANIMEMAN_SHUTDOWN_GRACE':'0.2' if mode=='stubborn' else '4',
                'PROBE_CONTROL':str(base/'control'), 'PROBE_SOURCE':str(base/'source'),
                'PROBE_MODE':mode, 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH':'/app' if docker else str(ROOT)}
            process = None; container = None; stop_process = None
            logfile = (root/'server.log').open('w', encoding='utf-8')
            try:
                if docker:
                    command = ['run','-d','--stop-timeout','-1','--health-interval','1s',
                        '--health-start-period','0s','-p','127.0.0.1::8000']
                    for name in ('config','cache','logs','work','control','tv','movies'):
                        command += ['--mount',f'type=bind,src={root/name},dst={base/name}']
                    command += ['--mount',f'type=bind,src={root/"source"},dst={base/"source"},readonly',
                        '--mount',f'type=bind,src={ROOT/"tests/support/deployment_probe.py"},dst=/probe.py,readonly']
                    for key,value in env.items():command += ['-e',f'{key}={value}']
                    container = dc(*command,args.docker,'python','/probe.py')
                    assert dc('inspect',container,'--format','{{.Config.StopTimeout}}') == '-1'
                else:
                    clean = {k:v for k,v in os.environ.items() if k not in
                        ('SOURCE_FOLDERS','TV_TARGET_FOLDER','MOVIE_TARGET_FOLDER','WEB_CONCURRENCY','ANIMEMAN_WORKERS')
                        and 'API_KEY' not in k}
                    process = subprocess.Popen([sys.executable,str(ROOT/'tests/support/deployment_probe.py')],
                        cwd=root, env=dict(clean,**env), stdout=logfile, stderr=subprocess.STDOUT)
                def read(path):
                    if docker:
                        result = subprocess.run(['docker','exec',container,'cat',str(base/path)],
                            text=True,capture_output=True)
                        return result.stdout if result.returncode==0 else ''
                    p=root/path
                    return p.read_text(encoding='utf-8') if p.exists() else ''
                ready = json.loads(eventually(lambda:read('control/ready')))
                assert ready['source_readonly'], 'source unexpectedly writable'
                if docker:
                    port = dc('port',container,'8000/tcp').rsplit(':',1)[1]
                    assert int(dc('exec',container,'id','-u')) != 0
                else:port=ready['port']
                def http(path, data=None, auth=True):
                    headers={}
                    if auth:headers['Authorization']='Basic '+base64.b64encode(b'test-user:test-pass').decode()
                    payload = None if data is None else json.dumps(data).encode()
                    if payload is not None:headers['Content-Type']='application/json'
                    request=urllib.request.Request(f'http://127.0.0.1:{port}{path}',payload,headers)
                    # Never honor a user/system HTTP proxy for these loopback tests.
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    try:
                        with opener.open(request,timeout=3) as response:
                            body=response.read().decode()
                            return response.status,json.loads(body) if response.headers.get_content_type()=='application/json' else body
                    except urllib.error.HTTPError as error:
                        body=error.read().decode()
                        return error.code, json.loads(body) if error.headers.get_content_type()=='application/json' else body
                assert http('/healthz',auth=False)[0]==200
                if docker:eventually(lambda:dc('inspect',container,'--format','{{.State.Health.Status}}')=='healthy')
                assert http('/api/config',auth=False)[0]==401
                assert http('/')[0]==200 and http('/static/style.css')[0]==200
                status, public=http('/api/config'); assert status==200
                assert 'dummy-tmdb-key' not in json.dumps(public)
                assert http('/api/run',{})[0]==200
                eventually(lambda:read('control/waiting'))
                saved=json.loads(read('cache/auto_processed_cache.json'))
                assert len(saved)==1 and next(iter(saved)).endswith('first.mkv')
                assert http('/api/run',{})[0]==409
                assert http('/api/config',{'max_workers':2})[0]==200
                # A second OS process sharing CACHE_PATH must fail before binding.
                if docker:
                    duplicate=subprocess.run(['docker','exec',container,'python','web_app.py'],text=True,capture_output=True,timeout=8)
                else:
                    duplicate=subprocess.run([sys.executable,str(ROOT/'web_app.py')],cwd=root,
                        env=dict(clean,**env),text=True,capture_output=True,timeout=8)
                assert duplicate.returncode==1 and 'CACHE_PATH' in duplicate.stderr
                if docker:
                    stop_process=subprocess.Popen(['docker','stop','--timeout','-1',container],stdout=subprocess.DEVNULL)
                else:process.send_signal(signal.SIGTERM)
                if mode=='stubborn':
                    def logs():
                        if docker:return dc('logs',container)  # Docker logs can use stderr.
                        logfile.flush();return (root/'server.log').read_text(encoding='utf-8')
                    if docker:
                        def timeout_logged():
                            result=subprocess.run(['docker','logs',container],text=True,capture_output=True)
                            return 'shutdown_timeout:' in result.stdout+result.stderr
                        eventually(timeout_logged)
                        assert dc('inspect',container,'--format','{{.State.Running}}')=='true'
                    else:
                        eventually(lambda:'shutdown_timeout:' in logs()); assert process.poll() is None
                        process.send_signal(signal.SIGTERM)
                        assert process.poll() is None
                    (root/'control/release').write_text('release',encoding='utf-8')
                if docker:
                    stop_process.wait(timeout=15)
                    assert dc('inspect',container,'--format','{{.State.ExitCode}}')==('1' if mode=='stubborn' else '0')
                    # Restart a fresh container on the same bind volumes to verify persistence.
                    dc('rm',container)
                    container=dc(*command,args.docker,'python','/probe.py')
                    port=dc('port',container,'8000/tcp').rsplit(':',1)[1]
                    def healthy():
                        try:return http('/healthz',auth=False)[0]==200
                        except (urllib.error.URLError,ConnectionError):return False
                    eventually(healthy)
                else:
                    assert process.wait(timeout=15)==(1 if mode=='stubborn' else 0)
                    (root/'control/ready').unlink()
                    process=subprocess.Popen([sys.executable,str(ROOT/'tests/support/deployment_probe.py')],cwd=root,
                        env=dict(clean,**env),stdout=logfile,stderr=subprocess.STDOUT)
                    ready=json.loads(eventually(lambda:read('control/ready')));port=ready['port']
                assert http('/api/config')[1]['max_workers']==2
                assert len(json.loads(read('cache/auto_processed_cache.json')))==1
                verify="from pathlib import Path; root=Path(%r); assert (root/'Probe/first.mkv').read_bytes()==b'synthetic media, not a valid video\\n'; assert not (root/'Probe/second.mkv').exists(); assert not list(root.glob('.animeman-stage-*'))" % str(base/'movies')
                if docker:dc('exec',container,'python','-c',verify)
                else:exec(verify,{})
                assert original=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'source').iterdir()}
                if docker:
                    dc('stop','--timeout','-1',container)
                else:
                    process.send_signal(signal.SIGTERM);assert process.wait(timeout=10)==0
                print(f'{"Docker" if docker else "local"} {mode}: health/auth/single-writer/commit/SIGTERM/restart/source protection PASS',flush=True)
            except BaseException:
                if docker and container:
                    failure=subprocess.run(['docker','logs',container],text=True,capture_output=True)
                    print(failure.stdout+failure.stderr,file=sys.stderr)
                else:
                    logfile.flush();print((root/'server.log').read_text(encoding='utf-8'),file=sys.stderr)
                raise
            finally:
                # Release synthetic workers even when an assertion fails; never force-kill.
                (root/'control/release').touch()
                if process and process.poll() is None:
                    process.send_signal(signal.SIGTERM);process.wait(timeout=20)
                if container:
                    running=dc('inspect',container,'--format','{{.State.Running}}')=='true'
                    if running:dc('stop','--timeout','-1',container)
                    # Rootless UID mapping: give temporary output back to the host owner.
                    cleanup=['run','--rm','--user','0:0','--entrypoint','chown']
                    for name in ('config','cache','logs','work','control','tv','movies'):
                        cleanup+=['--mount',f'type=bind,src={root/name},dst={base/name}']
                    owner='0:0' if 'rootless' in dc('info','--format','{{json .SecurityOptions}}') else f'{os.getuid()}:{os.getgid()}'
                    dc(*cleanup,args.docker,'-hR',owner,*[str(base/name) for name in ('config','cache','logs','work','control','tv','movies')])
                    dc('rm',container)
                logfile.close()


if __name__=='__main__':main()
