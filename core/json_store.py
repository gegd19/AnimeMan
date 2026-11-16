"""Process-local JSON transactions; preserve corrupt input and never truncate it."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

from .execution_mode import is_preview
from .runtime_paths import writable

_locks = {}
_registry_lock = threading.Lock()


class CacheCorruptionError(OSError):
    pass


def path_lock(path):
    path = Path(path)
    key = str(path.parent.resolve() / path.name)
    with _registry_lock:
        return _locks.setdefault(key, threading.RLock())


def _backup(path, raw, tag):
    backup = path.with_name(path.name + '.' + tag + '-' + hashlib.sha256(raw).hexdigest() + '.bak')
    try:
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if backup.read_bytes() != raw:
            raise CacheCorruptionError(f'缓存备份存在冲突，拒绝写入：{backup}')
    return backup


def backup_json(path, tag='t07'):
    if is_preview():
        return None
    path = Path(path)
    with path_lock(path):
        return _backup(path, path.read_bytes(), tag)


def _corrupt(path, raw, reason):
    # Content-addressed backups avoid another copy on every failed status poll.
    backup = _backup(path, raw, 'corrupt') if not is_preview() else None
    raise CacheCorruptionError(f'缓存损坏 {path}：{reason}；' + (f'原文件保留，备份 {backup}' if backup else '模拟模式保留原文件，不创建备份'))


def read_json(path):
    path = Path(path)
    with path_lock(path):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return {}
        try:
            def reject_constant(value):
                raise ValueError(f'不支持非有限 JSON 数字: {value}')
            data = json.loads(raw, parse_constant=reject_constant)
        except (ValueError, UnicodeError) as exc:
            _corrupt(path, raw, str(exc))
        if not isinstance(data, dict):
            _corrupt(path, raw, '顶层必须是 JSON 对象')
        return data


def _write(path, data):
    if not isinstance(data, dict):
        raise TypeError('缓存顶层必须是 JSON 对象')
    if is_preview():
        return
    writable(path)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            if path.exists():
                mode = stat.S_IMODE(path.stat().st_mode)
                if hasattr(os, 'fchmod'):
                    os.fchmod(stream.fileno(), mode)
                else:
                    os.chmod(temporary, mode)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, data):
    path = Path(path)
    if is_preview():
        return
    with path_lock(path):
        writable(path)
        read_json(path)  # Refuse to overwrite a corrupt existing document.
        _write(path, data)


def update_json(path, mutate):
    path = Path(path)
    with path_lock(path):
        data = read_json(path)
        original = deepcopy(data)
        mutate(data)
        if data != original:
            _write(path, data)
        return data
