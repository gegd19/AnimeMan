"""Check real Docker ignore matching using synthetic secret/media sentinels."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

root=Path(__file__).resolve().parents[1]
image=f'animeman-context-probe:{os.getpid()}'
with tempfile.TemporaryDirectory(prefix='animeman-context-') as directory:
    context=Path(directory)/'context';context.mkdir()
    shutil.copyfile(root/'.dockerignore',context/'.dockerignore')
    (context/'Dockerfile').write_text('FROM scratch\nCOPY . /\n')
    allowed=('core/allowed.py','web/allowed.py','templates/index.html',
        'templates/partials/modals/test.html','static/js/app.js','static/style.css',
        'main.py','web_app.py','server_runtime.py','requirements.lock')
    forbidden=('.env','auto_config.json','config/auto_config.json','cache/cache.json',
        'logs/private.log','.git/config','tests/secret.py','node_modules/private.js',
        'outputs/report.txt','source/video.mkv','core/private.json','templates/private.json',
        'static/private.key','build-context-secret.txt','core/nested/secret.json',
        'templates/partials/modals/private.json','static/js/private.key','core/__pycache__/secret.pyc')
    for name in (*allowed,*forbidden):
        path=context/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('SYNTHETIC TEST DATA\n')
    def docker(*args):
        return subprocess.run(['docker',*args],check=True,text=True,capture_output=True).stdout
    built=False
    try:
        docker('build','-t',image,str(context));built=True
        archive=Path(directory)/'image.tar'
        docker('save','--output',str(archive),image)
        paths=set()
        with tarfile.open(archive) as bundle:
            manifest=json.load(bundle.extractfile('manifest.json'))
            for layer in manifest[0]['Layers']:
                with tarfile.open(fileobj=io.BytesIO(bundle.extractfile(layer).read())) as contents:
                    paths.update(member.name.removeprefix('./').rstrip('/') for member in contents)
        assert set(allowed)<=paths, sorted(set(allowed)-paths)
        assert not set(forbidden)&paths, sorted(set(forbidden)&paths)
        print(f'Docker build context: {len(allowed)} allowed assets present, {len(forbidden)} synthetic secrets/media/output paths excluded PASS')
    finally:
        if built:docker('image','rm',image)
