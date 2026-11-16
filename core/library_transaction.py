"""Stage media artifacts, publish without clobbering, then commit the cache.

The lock coordinates this process only; multi-process deployment remains a
separate task. No existing file is replaced by this implementation.
"""

from .metadata_io import is_valid_nfo, is_valid_image, InvalidMetadataError
from .json_store import CacheCorruptionError, path_lock
from .cancellation import check_cancelled, ProcessingCancelled
from contextlib import ExitStack
from functools import wraps
import os
from pathlib import Path
import tempfile
import threading
import time

from . import cache_manager
from .failure_policy import make_failure, failure_scope, note_error
from .execution_mode import is_preview, preview_mode
from .path_safety import UnsafePathError, absolute_link_path, validate_cached_target, validate_target_path

library_lock = threading.RLock()


class TargetConflictError(ValueError):
    pass


def _same_file(src, dst):
    try:
        return os.path.samefile(src, dst)
    except OSError:
        return False


def _validate_existing_artifact(src, destination, target):
    if destination == target:
        if not _same_file(src, destination):
            raise TargetConflictError(f'target_conflict: {destination}')
    elif destination.suffix.lower() == '.nfo':
        expected = {'movie.nfo':'movie','tvshow.nfo':'tvshow','season.nfo':'season'}.get(destination.name.lower(),'episodedetails')
        if not is_valid_nfo(destination, expected):
            raise InvalidMetadataError(f'已有 NFO 无效，请先运行 --repair：{destination}')
    elif destination.suffix.lower() in {'.jpg','.jpeg','.png','.webp'} and not is_valid_image(destination):
        raise InvalidMetadataError(f'已有图片无效，请先运行 --repair：{destination}')


def preview_target(src, target, config, media_type):
    """Evaluate the same destination boundaries/conflicts without creating it."""
    target = validate_target_path(src, target, config, media_type)
    if os.path.lexists(target) and not _same_file(src, target):
        if "_preview_diagnostics" in config:
            config["_preview_diagnostics"].append({"code": "target_conflict", "target": str(target)})
        raise TargetConflictError(f"target_conflict: 目标已有不同文件: {target}")
    return target


def _failure(src, cache, reason, code, config):
    key = str(src.resolve())
    # A failed attempt must not erase an existing successful record.
    with cache_manager.cache_lock:
        if cache.get(key, {}).get("media_type") not in (None, "failed"):
            return
        cache[key] = make_failure(src, reason, config, category='conflict' if code == 'target_conflict' else None)
        cache[key]['error_code'] = code


def transactional_media(function):
    @wraps(function)
    def wrapped(src, config, cache_dict, *args, **kwargs):
        check_cancelled()
        src = Path(src).resolve()
        if is_preview(config):
            with preview_mode(True):
                return function(src, dict(config, dry_run=True), {}, *args, **kwargs)
        local_cache = {}
        created = []
        try:
            with ExitStack() as stack:
                staged_config = dict(config)
                mappings = []
                for field in ("movie_target_folder", "tv_target_folder"):
                    root = Path(config[field]).resolve()
                    # Staging on the target filesystem allows exclusive link publication.
                    root.mkdir(parents=True, exist_ok=True)
                    stage = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=".animeman-stage-", dir=root)))
                    staged_config[field] = str(stage)
                    mappings.append((stage, root))

                def final_path(path):
                    path = absolute_link_path(path)
                    for stage, root in mappings:
                        if path.is_relative_to(stage):
                            return root / path.relative_to(stage)
                    raise ValueError("处理器返回了暂存区外的路径")

                check_cancelled()
                success = function(src, staged_config, local_cache, *args, **kwargs)
                check_cancelled()
                if not success:
                    error = local_cache.get(str(src.resolve()), {})
                    _failure(src, cache_dict, error.get("failed_reason", "整理失败"), error.get("error_code", "processing_failed"), config)
                    return False
                if config.get("dry_run"):
                    return True
                entry = local_cache[str(src.resolve())].copy()
                target = validate_target_path(src, final_path(entry["target"]), config, entry["media_type"])
                staged_files = [(path, validate_target_path(src, final_path(path), config, entry["media_type"]))
                                for stage, root in mappings for path in stage.rglob("*")
                                if path.is_file() or path.is_symlink()]
                with library_lock:
                    check_cancelled()
                    if os.path.lexists(target) and not _same_file(src, target):
                        raise TargetConflictError(f"target_conflict: 目标已有不同文件: {target}")
                    # Publish video first. os.link/symlink fail exclusively if a path
                    # appears between preflight and publication (no replace/overwrite).
                    staged_files.sort(key=lambda item: item[1] != target)
                    try:
                        for stage_path, destination in staged_files:
                            check_cancelled()
                            with path_lock(destination):
                                if os.path.lexists(destination):
                                    _validate_existing_artifact(src, destination, target)
                                    continue
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                try:
                                    if stage_path.is_symlink():
                                        os.symlink(os.readlink(stage_path), destination)
                                    else:
                                        os.link(stage_path, destination)
                                except FileExistsError:
                                    _validate_existing_artifact(src, destination, target)
                                    continue
                                created.append(destination)
                        entry["target"] = str(target)
                        previous = config.get("_previous_entry") or cache_dict.get(str(src.resolve()), {})
                        owned = previous.get("artifacts", []) if previous.get("target") == str(target) else []
                        entry["artifacts"] = list(dict.fromkeys(owned + [str(p) for p in created if p != target]))
                        if previous.get("pending_cleanup"):
                            entry["pending_cleanup"] = previous["pending_cleanup"]
                        check_cancelled()
                        commit = config.get("_commit_entry")
                        if commit is not None:
                            commit(entry)
                        with cache_manager.cache_lock:
                            cache_dict[str(src.resolve())] = entry
                    except Exception:
                        for path in reversed(created):
                            path.unlink(missing_ok=True)
                        raise
            return True
        except ProcessingCancelled:
            raise
        except CacheCorruptionError:
            raise
        except Exception as exc:
            note_error(exc)
            code = "target_conflict" if isinstance(exc, TargetConflictError) else "processing_failed"
            _failure(src, cache_dict, str(exc), code, config)
            return False
    return wrapped


def reprocess_safely(src, config, operation):
    """Preserve the old record/artifacts until the new record is durable."""
    from .processor_cache_ops import remove_cached_artifacts

    check_cancelled()
    key = str(src.resolve())
    if is_preview(config):
        with preview_mode(True):
            old = cache_manager.load_cache().get(key)
            if old and old.get("media_type") != "failed":
                validate_cached_target(src, old, config)
            diagnostics = []
            success = bool(operation(dict(config, dry_run=True, _preview_diagnostics=diagnostics), {}))
            return success, None if success else (diagnostics[-1]["code"] if diagnostics else "processing_failed")
    with library_lock:
        with cache_manager.cache_lock:
            cache = cache_manager.prepare_cache_for_removal(config, sources={key})
            old = cache.get(key)
            if old and old.get("media_type") != "failed":
                validate_cached_target(src, old, config)
        committed = False

        def commit(entry):
            nonlocal committed
            check_cancelled()
            if old and old.get("media_type") != "failed" and old.get("target") != entry.get("target"):
                # Save a receipt before old-file cleanup. Even a later failure
                # persisting the cleanup warning cannot lose the old location.
                entry["previous_artifacts"] = {
                    field: value for field, value in old.items()
                    if field not in ("previous_artifacts", "pending_cleanup")
                }
            with cache_manager.cache_lock:
                current = cache_manager.load_cache()
                current[key] = entry
                cache_manager.save_cache(current)
            committed = True

        effective = dict(config, _commit_entry=commit, _previous_entry=old)
        result = {}
        with failure_scope(config, old):
            succeeded = operation(effective, result)
        if not succeeded:
            return False, result.get(key, {}).get("error_code", "processing_failed")
        if config.get("dry_run"):
            return True, None
        if not committed:
            validate_cached_target(src, result[key], config)
            if not Path(result[key]["target"]).exists():
                raise OSError("新目标不存在，拒绝提交缓存")
            commit(result[key])
        new = result[key]
        if old and old.get("media_type") != "failed" and old.get("target") != new.get("target"):
            try:
                remove_cached_artifacts(src, old, config, previous=True,
                                        references=cache_manager.load_cache())
            except (OSError, UnsafePathError) as exc:
                # Commit succeeded: retain a cleanup job rather than discard the
                # only description of old artifacts or falsely roll back success.
                with cache_manager.cache_lock:
                    current = cache_manager.load_cache()
                    pending = current[key].get("pending_cleanup", [])
                    current[key]["pending_cleanup"] = pending + [{"entry": old, "error": str(exc)}]
                    cache_manager.save_cache(current)
        return True, None
