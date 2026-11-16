"""OS-owned single-writer process guard; never unlink a live lock inode."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat

HEADER=b'AnimeMan process lock v1\n'


class ProcessAlreadyRunning(OSError):
    pass


@contextmanager
def process_guard(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():
        raise OSError('进程锁不能为符号链接')
    flags=os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
    fd=os.open(path,flags,0o600)
    locked=False
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError('进程锁必须为普通文件')
        if os.name=='nt':
            import msvcrt
            if os.fstat(fd).st_size==0:os.write(fd,b'\0')
            os.lseek(fd,0,os.SEEK_SET)
            try:msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            except OSError as error:raise ProcessAlreadyRunning('另一个 AnimeMan 写进程占用此 CACHE_PATH') from error
        else:
            import fcntl
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as error:raise ProcessAlreadyRunning('另一个 AnimeMan 写进程占用此 CACHE_PATH') from error
        locked=True
        os.lseek(fd,0,os.SEEK_SET);previous=os.read(fd,8193)
        if previous not in (b'',b'\0') and (not previous.startswith(HEADER) or len(previous)>8192):
            raise OSError('进程锁路径已有未知内容，拒绝覆盖')
        data=HEADER+f'pid={os.getpid()}\n'.encode('ascii')
        os.lseek(fd,0,os.SEEK_SET);os.write(fd,data);os.ftruncate(fd,len(data));os.fsync(fd)
        yield
    finally:
        if locked:
            if os.name=='nt':
                os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else:fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)
