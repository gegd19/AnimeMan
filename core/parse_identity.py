"""Rule/config/content identities; file heads are read once per task scope."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass,field
from functools import wraps
import hashlib
import json
from pathlib import Path
import threading

from .cancellation import check_cancelled
from .processor_utils import is_video_file,should_skip_path

class ParseInputChanged(OSError):
    pass


RULE_VERSION='e01b-v1'
_memo=ContextVar('animeman_parse_identity',default=None)


@dataclass
class IdentityMemo:
    lock: object=field(default_factory=threading.RLock)
    values: dict=field(default_factory=dict)
    completed: dict=field(default_factory=dict)


@contextmanager
def identity_scope():
    if _memo.get() is not None:
        yield _memo.get();return
    memo=IdentityMemo();token=_memo.set(memo)
    try:yield memo
    finally:_memo.reset(token)


def with_identity_scope(function):
    @wraps(function)
    def wrapped(*a,**k):
        with identity_scope():return function(*a,**k)
    return wrapped


def current_memo():return _memo.get()


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def policy_key(config):
    fields=['ai_parser','anime_parser','video_extensions','ignore_patterns','scan_policy','special_mappings','source_folders','parse_rules_version','parse_context','identity_hints']
    return digest([RULE_VERSION,{field:config.get(field) for field in fields}])


def file_signature(path):
    check_cancelled();path=Path(path)
    before=path.stat()
    with path.open('rb') as stream:head=hashlib.sha256(stream.read(1024*1024)).hexdigest()
    after=path.stat()
    signature=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if signature(before)!=signature(after):raise OSError(f'解析时源文件发生变化：{path}')
    return [*signature(after),head]


def folder_files(folder,config,max_depth=2):
    folder=Path(folder).absolute()
    if not folder.is_dir():return []
    if 'source_folders' in config:
        roots=[Path(p).resolve() for p in config['source_folders']]
        if not any(folder.resolve()==root or root in folder.resolve().parents for root in roots):return []
    effective=dict(config,video_extensions=config.get('video_extensions',['.mkv','.mp4']),ignore_patterns=config.get('ignore_patterns',[]))
    files=[]
    def walk(path,depth):
        check_cancelled()
        for item in sorted(path.iterdir()):
            check_cancelled()
            if item.is_symlink() or should_skip_path(item,folder,effective):continue
            if item.is_dir() and depth<max_depth:walk(item,depth+1)
            elif item.is_file() and is_video_file(item,effective):files.append(item)
    walk(folder,1)
    return files


def folder_snapshot(folder,config):
    folder=Path(folder).absolute();key=('folder',str(folder),policy_key(config))
    def compute():
        files=folder_files(folder,config)
        identity=digest([RULE_VERSION,str(folder),policy_key(config),[(p.relative_to(folder).as_posix(),_signature(p)) for p in files]])
        return identity,files
    memo=_memo.get()
    if memo is None:return compute()
    with memo.lock:
        if key not in memo.values:memo.values[key]=compute()
        return memo.values[key]


def folder_identity(folder,config):return folder_snapshot(folder,config)[0]


def _signature(path):
    path=Path(path).absolute();memo=_memo.get();key=('file',str(path))
    if memo is None:return file_signature(path)
    with memo.lock:
        if key not in memo.values:memo.values[key]=file_signature(path)
        return memo.values[key]


def assert_file_current(path):
    signature=_signature(path);stat=Path(path).stat()
    if tuple(signature[:5])!=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns):
        raise ParseInputChanged(f'解析期间源文件发生变化：{path}')


@with_identity_scope
def file_key(path,config):
    path=Path(path).absolute()
    assert_file_current(path)
    return RULE_VERSION+':'+digest([str(path),_signature(path),folder_identity(path.parent,config),policy_key(config)])



def tmdb_scope(folder,config):
    from .runtime_paths import cache_file
    return (str(cache_file('auto_processed_cache.json')),folder_identity(folder,config),
            digest([config.get('tmdb_api',{}),config.get('force_chinese_name'),config.get('image_base_url')]))


def assert_snapshot_current(folder,config):
    """Check names and stat versions again without reading file heads a second time."""
    _,original=folder_snapshot(folder,config)
    current=folder_files(folder,config)
    if current!=original:raise ParseInputChanged(f'AI 请求期间文件清单发生变化：{folder}')
    for path in original:
        signature=_signature(path)
        stat=path.stat()
        if tuple(signature[:5])!=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns):
            raise ParseInputChanged(f'AI 请求期间源文件发生变化：{path}')
