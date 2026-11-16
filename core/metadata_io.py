"""Validated metadata publication, with per-file locks and invalid-file backups."""
import os
from pathlib import Path
import stat
import uuid
import warnings
from xml.etree import ElementTree as ET

from PIL import Image, UnidentifiedImageError

from .cancellation import check_cancelled
from .execution_mode import is_preview
from .json_store import path_lock, backup_json
from .path_safety import UnsafePathError


class InvalidMetadataError(ValueError):
    pass


def is_valid_nfo(path, root_tag=None):
    try:
        root = ET.parse(path).getroot()
        return root_tag is None or root.tag == root_tag
    except (FileNotFoundError, ET.ParseError, UnicodeError):
        return False


def is_valid_image(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                image.verify()
            # Identification/verification alone does not decode the pixel data.
            with Image.open(path) as image:
                image.load()
        return True
    except PermissionError:
        raise
    except (FileNotFoundError, UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False


def write_metadata(path, data, validator):
    """Return True only for a newly published, validated file."""
    if is_preview():
        return False
    path = Path(path)
    with path_lock(path):
        check_cancelled()
        if validator(path):
            return False
        if path.is_symlink():
            raise UnsafePathError(f'损坏元数据是符号链接，拒绝自动替换：{path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                if path.exists():
                    os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if not validator(temporary):
                raise InvalidMetadataError(f'元数据验证失败，未发布：{path}')
            check_cancelled()
            if validator(path):
                return False
            if path.is_symlink():
                raise UnsafePathError(f'元数据写入期间出现符号链接，拒绝替换：{path}')
            if path.exists():
                backup_json(path, tag='t08')
            check_cancelled()
            os.replace(temporary, path)
            return True
        finally:
            temporary.unlink(missing_ok=True)
