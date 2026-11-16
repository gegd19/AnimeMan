"""Directory-entry paths for links and conservative removal boundaries."""

import os
from pathlib import Path


class UnsafePathError(ValueError):
    """The record cannot safely identify a removable library entry."""


def absolute_link_path(path):
    """Resolve parents, but keep the final directory entry (even a broken link)."""
    path = Path(os.path.abspath(os.fspath(path)))
    return path.parent.resolve() / path.name


def _roots(values):
    roots = []
    for value in values:
        if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
            continue
        root = Path(value).resolve()
        if root != root.parent:
            roots.append(root)
    return roots


def _inside(path, roots):
    return any(path != root and root in path.parents for root in roots)


def source_roots(config):
    values = list(config.get("source_folders", []))
    values.append(config.get("subtitle_center", {}).get("default_source_folder", ""))
    return _roots(values)


def target_roots(config, media_type):
    fields = {"movie": ["movie_target_folder"], "tv": ["tv_target_folder"],
              "subtitle": ["movie_target_folder", "tv_target_folder"]}.get(media_type, [])
    return _roots([config.get(field, "") for field in fields])


def validate_target_path(src, target, config, media_type):
    if not isinstance(target, (str, os.PathLike)) or not str(target).strip():
        raise UnsafePathError("目标路径为空，需要重建记录")
    path = absolute_link_path(target)
    source = absolute_link_path(src)
    if path == source or path == Path(src).resolve():
        raise UnsafePathError("目标路径与源路径相同，需要重建记录")
    if not _inside(path, target_roots(config, media_type)):
        raise UnsafePathError("目标不在配置的媒体库范围内，需要重建记录")
    if _inside(path, source_roots(config)):
        raise UnsafePathError("目标位于源目录，禁止清理")
    if path.is_dir() and not path.is_symlink():
        raise UnsafePathError("目标是目录，禁止按文件删除")
    return path


def validate_cached_target(src, entry, config):
    if not isinstance(entry, dict) or entry.get("needs_reindex"):
        raise UnsafePathError("记录需要重建，禁止清理")
    if entry.get("source_path") and absolute_link_path(entry["source_path"]) != absolute_link_path(src):
        raise UnsafePathError("缓存源路径不一致")
    return validate_target_path(src, entry.get("target"), config, entry.get("media_type"))


def validate_source_path(src, config):
    path = absolute_link_path(src)
    if not _inside(path, source_roots(config)):
        raise UnsafePathError("源路径不在配置的源目录范围内")
    if path.is_dir() and not path.is_symlink():
        raise UnsafePathError("源路径是目录，禁止按文件删除")
    return path
