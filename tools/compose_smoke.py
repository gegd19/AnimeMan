"""Verify the shipped Compose file against real Docker, with temporary binds."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('image')
    parser.add_argument('--uid',type=int,default=1000)
    parser.add_argument('--gid',type=int,default=1000)
    args=parser.parse_args()
    assert args.uid>0 and args.gid>0
    root=Path(__file__).resolve().parents[1]
    def docker(*argv):
        return subprocess.run(['docker',*argv],check=True,text=True,capture_output=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='animeman-compose-') as directory:
        data=Path(directory);data.chmod(0o755)
        for name in ('config','cache','logs','work','source','tv','movies'):
            (data/name).mkdir();(data/name).chmod(0o777)
        (data/'source/original.mkv').write_bytes(b'synthetic media')
        (data/'config/auto_config.json').write_text(json.dumps({
            'auth':{'enabled':True,'username':'test-user','password':'test-pass'},
            'source_folders':['/media/source'],'tv_target_folder':'/media/tv',
            'movie_target_folder':'/media/movies','ai_parser':{'enabled':False},
            'tmdb_api':{'api_key':'dummy-key'}}),encoding='utf-8')
        shutil.copyfile(root/'docker-compose.yml',data/'compose.yml')
        (data/'override.yml').write_text(json.dumps({'services':{'animeman':{'image':args.image,
            'healthcheck':{'interval':'1s','start_period':'0s'}}}}))
        env=dict(os.environ,SECRET_KEY='synthetic-only',PUID=str(args.uid),PGID=str(args.gid),PORT='0',BIND_IP='127.0.0.1',
            HTTP_THREADS='4',SHUTDOWN_GRACE='2',
            SOURCE_DIR=str(data/'source'),TV_DIR=str(data/'tv'),MOVIE_DIR=str(data/'movies'))
        command=['docker','compose','--project-name',f'animeman-t15-{os.getpid()}',
            '-f',str(data/'compose.yml'),'-f',str(data/'override.yml')]
        def compose(*argv):
            return subprocess.run([*command,*argv],env=env,cwd=data,text=True,check=True,capture_output=True).stdout.strip()
        container=None
        try:
            config=json.loads(compose('config','--format','json'))['services']['animeman']
            assert config['stop_grace_period']=='-1s' and config['user']==f'{args.uid}:{args.gid}'
            compose('up','-d','--no-build','--pull','never')
            container=compose('ps','-q','animeman')
            inspect=json.loads(docker('inspect',container))[0]
            assert inspect['Config']['StopTimeout']==-1
            assert inspect['Config']['Cmd']==['python','web_app.py']
            assert all(not m['RW'] for m in inspect['Mounts'] if m['Destination']=='/media/source')
            for _ in range(150):
                if docker('inspect',container,'--format','{{.State.Health.Status}}')=='healthy':break
                time.sleep(0.1)
            else:raise AssertionError('Compose production entry failed health check')
            assert docker('exec',container,'id','-u').strip()==str(args.uid)
            assert docker('exec',container,'id','-g').strip()==str(args.gid)
            docker('exec',container,'python','-c',
                "import errno; from pathlib import Path; "
                "p=Path('/media/source/original.mkv'); "
                "exec(\"try:\\n p.open('r+b')\\nexcept OSError as e:\\n assert e.errno in (errno.EROFS,errno.EACCES)\\nelse:\\n raise AssertionError('source writable')\")")
            print(f'Compose: production CMD, UID:GID={args.uid}:{args.gid}, healthy, source RO, separate work, StopTimeout=-1 PASS')
        except BaseException:
            if container:
                result=subprocess.run(['docker','logs',container],text=True,capture_output=True)
                print(result.stdout+result.stderr)
            raise
        finally:
            compose('stop')  # Uses the verified -1 grace, never a forced kill.
            cleanup=['run','--rm','--user','0:0','--entrypoint','chown']
            for name in ('config','cache','logs','work'):
                cleanup+=['--mount',f'type=bind,src={data/name},dst=/cleanup/{name}']
            owner='0:0' if 'rootless' in docker('info','--format','{{json .SecurityOptions}}') else f'{os.getuid()}:{os.getgid()}'
            docker(*cleanup,args.image,'-hR',owner,*[f'/cleanup/{n}' for n in ('config','cache','logs','work')])
            compose('down','--remove-orphans')


if __name__=='__main__':main()
