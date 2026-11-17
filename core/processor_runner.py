#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器批量运行入口
扫描源文件夹、过滤文件、多线程处理
优化：跳过特典/CD/SP等无关目录，每成功处理10个文件或任务结束时保存缓存
"""

from pathlib import Path
from contextvars import copy_context
from .execution_mode import execution_scope, is_preview
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from .cancellation import ProcessingCancelled
from .json_store import CacheCorruptionError
from .parse_identity import with_identity_scope
from .failure_policy import failure_scope, should_retry, make_failure, note_error
from typing import Callable, List

from . import config_manager
from . import cache_manager
from . import tmdb_client
from .processor_core import process_video, stop_processing as core_stop
from .processor_utils import should_skip_file, is_video_file, wrap_progress_callback, should_skip_path
from .processor_repair import repair_missing_metadata
from .logger import get_logger

logger = get_logger(__name__)

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"

def _scan_video_files(root: Path, config: dict) -> List[Path]:
    """
    递归扫描视频文件，自动跳过特典/无关目录
    """
    video_files = []

    def _walk(current: Path):
        try:
            for item in current.iterdir():
                if core_stop.is_set():
                    return
                if item.name.startswith('.'):
                    continue
                if item.is_symlink():
                    continue

                if should_skip_path(item, root, config):
                    continue

                if item.is_dir():
                    _walk(item)
                elif item.is_file():
                    # 与离线预解析共用同一套过滤规则（整词匹配 ignore_patterns），
                    # 避免两处扫描结果不一致
                    if not is_video_file(item, config):
                        continue
                    abs_path = str(item.resolve())
                    if abs_path.startswith("\\\\?\\"):
                        abs_path = abs_path[4:]
                    video_files.append(Path(abs_path))
        except PermissionError:
            pass

    _walk(root)
    return video_files


def run_processor_with_callback(
    config_path: str,
    progress_callback: Callable,
    repair_mode: bool = False,
    *, config_overrides=None, effective_config=None
):
    """处理器批量运行入口（供命令行和 Web 调用）"""
    try:
        overrides = dict(config_overrides or {})
        config = deepcopy(effective_config) if effective_config is not None else config_manager.load_config(config_path, create_if_missing=not overrides.get("dry_run", False))
        config.update(overrides)
    except Exception as e:
        logger.error(f"加载配置失败: {e}", exc_info=True)
        raise

    return _run_with_config(config, progress_callback, repair_mode)


@execution_scope
@with_identity_scope
def _run_with_config(config, progress_callback, repair_mode):
    if is_preview(config):
        config = dict(config, dry_run=True)
    if config.get("user_rules", {}).get("enabled") is True:
        from .user_recognition_rules import revision
        config = dict(config, recognition_rule_revision=revision(config))
    tmdb_client._tmdb_limiter = tmdb_client.RateLimiter(min_interval=config.get("tmdb_rate_limit", 0.05))
    from . import anime_db
    anime_db.reset_run()

    with cache_manager.cache_lock:
        cache = cache_manager.load_cache()
    new_cache = deepcopy(cache)
    persisted = deepcopy(cache)

    wrapped_log = wrap_progress_callback(progress_callback)
    if not is_preview(config) and anime_db.maybe_refresh(config):
        wrapped_log("📚 番剧数据库超过更新周期，正在后台更新（本次运行仍使用现有数据）", LOG_INFO)

    if repair_mode:
        return repair_missing_metadata(config, cache, wrapped_log)

    # 扫描视频文件
    video_files = []
    for folder in config["source_folders"]:
        if core_stop.is_set():
            break
        p = Path(folder)
        if p.exists():
            try:
                video_files.extend(_scan_video_files(p, config))
            except Exception as e:
                logger.error(f"扫描源文件夹失败 {folder}: {e}")
                wrapped_log(f"扫描源文件夹失败 {folder}: {e}", "error")

    total_files = len(video_files)
    wrapped_log(f"🔍 扫描完成，共 {total_files} 个视频文件", LOG_SUCCESS)

    # Build bounded evidence only from this run's existing scan inventory.
    from .folder_evidence import collect_folder_evidence
    scanned_by_folder = {}
    for item in video_files:
        scanned_by_folder.setdefault(item.parent, []).append(item)
    folder_evidence = {}
    for folder, files in scanned_by_folder.items():
        if core_stop.is_set():
            break
        try:
            folder_evidence[folder] = collect_folder_evidence(folder, files, config)
        except ProcessingCancelled:
            if not core_stop.is_set():
                raise
            break

    # 增量过滤
    to_process = []
    for src in video_files:
        if core_stop.is_set():
            break
        src_str = str(src.resolve())
        entry = cache.get(src_str, {})
        prior_failure = entry if entry.get("media_type") == "failed" else entry.get("last_failure", {})
        if prior_failure.get("no_retry") is True:
            wrapped_log(f"🚫 保留人工禁止重试项: {src.name}", LOG_WARNING)
            continue
        if config.get("incremental") and src_str in cache:
            with cache_manager.cache_lock:
                entry = cache.get(src_str)
                if entry and entry.get("media_type") != "failed":
                    if cache_manager.is_already_processed(src, entry, config):
                        wrapped_log(f"⏭️ 跳过已处理: {src.name}", LOG_INFO)
                        continue
                    if entry.get("last_failure") and not should_retry(src, entry["last_failure"], config):
                        wrapped_log(f"🚫 保留旧产物，暂不重试上次失败: {src.name}", LOG_WARNING)
                        continue
                if entry and entry.get("media_type") == "failed" and not should_retry(src, entry, config):
                    wrapped_log(f"🚫 跳过失败缓存: {src.name}", LOG_WARNING)
                    continue
        to_process.append(src)

    cache_manager.backup_legacy_failures(to_process)
    total = len(to_process)
    wrapped_log(f"📝 待处理 {total} 个文件", LOG_INFO)

    success = failed = completed = 0
    errors = []
    workers = max(1, int(config.get("max_workers", 3)))
    pending = {}
    remaining = iter(to_process)
    executor = ThreadPoolExecutor(max_workers=workers)

    def flush_changes(keys=None):
        if is_preview(config):
            return
        with cache_manager.cache_lock:
            candidates = new_cache if keys is None else keys
            changes = {key:deepcopy(new_cache[key]) for key in candidates if key in new_cache
                       and (key not in persisted or new_cache[key] != persisted[key])}
            if changes:
                cache_manager.update_records(changes)
                persisted.update(deepcopy(changes))

    def process_one(src):
        key = str(src.resolve())
        previous = deepcopy(cache.get(key, {}))
        previous_failure = previous.get("last_failure", previous)
        with failure_scope(config, previous_failure) as failure:
            effective = dict(config, _folder_evidence=folder_evidence.get(src.parent))
            if not is_preview(config):
                # A publication is not successful until its record is durable.
                effective['_commit_entry'] = lambda entry: cache_manager.update_records({key:entry})
            try:
                success = process_video(src, effective, new_cache, wrapped_log)
            except (ProcessingCancelled, CacheCorruptionError):
                raise
            except Exception as exc:
                note_error(exc)
                success = False
                reason = str(exc)
                logger.error(f"处理文件异常 {src}: {exc}", exc_info=True)
            else:
                observed = new_cache.get(key, {})
                reason = observed.get('failed_reason', '未找到匹配结果') if observed != previous else '未找到匹配结果'
            if not success and not is_preview(config):
                with cache_manager.cache_lock:
                    entry = new_cache.get(key, {})
                    observed = entry if entry != previous else {}
                    replacement = make_failure(src, reason, config, previous=previous_failure,
                        category=observed.get('failure_category') or failure.category,
                        error=failure.error or observed.get('last_error'))
                    if observed.get('recognition_pending'):
                        replacement['recognition_pending'] = deepcopy(observed['recognition_pending'])
                    if observed.get('error_code'):
                        replacement['error_code'] = observed['error_code']
                    if entry.get('target') and entry.get('media_type') != 'failed':
                        new_cache[key] = dict(entry, last_failure=replacement)
                    else:
                        new_cache[key] = replacement
            return success

    def fill_window():
        while len(pending) < workers * 2 and not core_stop.is_set():
            src = next(remaining, None)
            if src is None:
                break
            pending[executor.submit(copy_context().run, process_one, src)] = src

    def consume(future):
        nonlocal success, failed, completed
        src = pending.pop(future)
        if future.cancelled():
            return
        try:
            if future.result():
                success += 1
            else:
                failed += 1
                if len(errors) < 10:
                    entry = new_cache.get(str(src), {})
                    diagnostic = entry.get("last_failure", entry)
                    errors.append({"file":src.name, "error":diagnostic.get("last_error", diagnostic.get("failed_reason", "整理失败"))})
        except CacheCorruptionError:
            raise
        except ProcessingCancelled:
            pass
        except Exception as exc:
            failed += 1
            if len(errors) < 10:
                errors.append({"file":src.name, "error":str(exc)})
            logger.error(f"处理文件异常 {src}: {exc}", exc_info=True)
            wrapped_log(f"任务异常: {exc}", "error")
        completed += 1
        flush_changes([str(src.resolve())])
        if progress_callback:
            progress_callback(completed, total, f"进度 {completed}/{total}", "progress")

    try:
        fill_window()
        while pending:
            if core_stop.is_set():
                for future in pending:
                    future.cancel()
            done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                consume(future)
            fill_window()
    except KeyboardInterrupt:
        core_stop.set()
        for future in pending:
            future.cancel()
    finally:
        # Drain every started worker before the last cache save or lease release.
        executor.shutdown(wait=True, cancel_futures=True)
        for future in list(pending):
            consume(future)
        flush_changes()

    cancelled = core_stop.is_set()
    message = "任务已取消" if cancelled else "模拟完成" if config.get("dry_run") else "任务完成"
    wrapped_log(f"{message}：成功 {success}/{total}，失败 {failed}", LOG_WARNING if cancelled else LOG_INFO)
    return {"success":success, "failed":failed, "completed":completed, "total":total, "cancelled":cancelled, "errors":errors}
