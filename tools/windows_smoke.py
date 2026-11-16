"""Fail visibly on unsupported Windows behavior; synthetic temporary files only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.file_linker import create_link, get_long_path
from core.process_lock import process_guard
from core.json_store import read_json, write_json

assert os.name=='nt','This probe requires Windows; never report a Linux run as Windows coverage'
with tempfile.TemporaryDirectory(prefix='animeman-windows-') as directory:
    root=Path(directory)
    source=root/'源 [1] & test.mkv';source.write_bytes(b'synthetic media')
    hard=root/'hard.mkv';soft=root/'soft.mkv'
    assert create_link(source,hard,'hard') and os.path.samefile(source,hard)
    assert create_link(source,soft,'symlink') and soft.is_symlink()
    hard.unlink();soft.unlink();assert source.read_bytes()==b'synthetic media'
    deep=root/('a'*90)/('b'*90)/('c'*90)/'媒体.json'
    deep.parent.mkdir(parents=True)
    write_json(deep,{'path':str(source),'unicode':'中文'})
    assert read_json(deep)['path']==str(source)
    assert get_long_path(deep).startswith('\\\\?\\')
    lock=root/'owner.lock'
    with process_guard(lock):
        code='from core.process_lock import process_guard; import sys;\nwith process_guard(sys.argv[1]): pass'
        child=subprocess.run([sys.executable,'-c',code,str(lock)],text=True,capture_output=True)
        assert child.returncode!=0 and 'ProcessAlreadyRunning' in child.stderr
    with process_guard(lock):pass
print('Windows: hard/symbolic links, source retention, long/Unicode paths, atomic JSON and process ownership PASS')
