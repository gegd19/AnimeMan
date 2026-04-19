#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
处理器批量运行入口
扫描源文件夹、过滤文件、多线程处理
优化：跳过特典/CD/SP等无关目录，每成功处理10个文件或任务结束时保存缓存
"""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# 将停止标志绑定到核心模块
import core.processor_core as processor_core
processor_core.stop_processing = core_stop


def _scan_video_files(root: Path, config: dict) -> List[Path]:
    """
    递归扫描视频文件，自动跳过特典/无关目录
    """
    video_files = []
    video_exts = {ext.lower() for ext in config["video_extensions"]}
    ignore_patterns = [p.lower() for p in config.get("ignore_patterns", [])]

    def _walk(current: Path):
        try:
            for item in current.iterdir():
                if item.name.startswith('.'):
                    continue
                if item.is_symlink():
                    continue

                if should_skip_path(item):
                    continue

                if item.is_dir():
                    _walk(item)
                elif item.is_file():
                    ext = item.suffix.lower()
                    if ext not in video_exts:
                        continue
                    name_lower = item.name.lower()
                    if any(p in name_lower for p in ignore_patterns):
                        continue
                    min_mb = config.get("min_file_size_mb", 0)
                    if min_mb > 0:
                        try:
                            if item.stat().st_size / (1024 * 1024) < min_mb:
                                continue
                        except Exception:
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
    repair_mode: bool = False
) -> None:
    """处理器批量运行入口（供命令行和 Web 调用）"""
    try:
        config = config_manager.load_config(config_path)
    except Exception as e:
        logger.error(f"加载配置失败: {e}", exc_info=True)
        raise

    tmdb_client._tmdb_limiter = tmdb_client.RateLimiter(min_interval=config.get("tmdb_rate_limit", 0.05))

    with cache_manager.cache_lock:
        cache = cache_manager.load_cache() if config.get("incremental") else {}
    new_cache = cache.copy()

    wrapped_log = wrap_progress_callback(progress_callback)

    if repair_mode:
        repair_missing_metadata(config, cache, wrapped_log)
        return

    # 扫描视频文件
    video_files = []
    for folder in config["source_folders"]:
        p = Path(folder)
        if p.exists():
            try:
                video_files.extend(_scan_video_files(p, config))
            except Exception as e:
                logger.error(f"扫描源文件夹失败 {folder}: {e}")
                wrapped_log(f"扫描源文件夹失败 {folder}: {e}", "error")

    total_files = len(video_files)
    wrapped_log(f"🔍 扫描完成，共 {total_files} 个视频文件", LOG_SUCCESS)

    # 增量过滤
    to_process = []
    for src in video_files:
        src_str = str(src.resolve())
        if config.get("incremental") and src_str in cache:
            with cache_manager.cache_lock:
                entry = cache.get(src_str)
                if entry and entry.get("media_type") != "failed":
                    if cache_manager.is_already_processed(src, entry, config):
                        wrapped_log(f"⏭️ 跳过已处理: {src.name}", LOG_INFO)
                        continue
                if entry and entry.get("media_type") == "failed":
                    wrapped_log(f"🚫 跳过失败缓存: {src.name}", LOG_WARNING)
                    continue
        to_process.append(src)

    total = len(to_process)
    wrapped_log(f"📝 待处理 {total} 个文件", LOG_INFO)

    success = 0
    SAVE_INTERVAL = 10  # 每成功处理 10 个文件保存一次缓存
    core_stop.clear()

    with ThreadPoolExecutor(max_workers=config.get("max_workers", 3)) as executor:
        futures = {executor.submit(process_video, src, config, new_cache, wrapped_log): src for src in to_process}
        for i, future in enumerate(as_completed(futures), 1):
            if core_stop.is_set():
                for f in futures:
                    f.cancel()
                wrapped_log("⏹️ 收到停止信号，正在保存缓存...", LOG_WARNING)
                break
            try:
                if future.result():
                    success += 1
                    # 每 SAVE_INTERVAL 个成功或最后一个任务时保存缓存
                    if config.get("incremental") and not config.get("dry_run"):
                        if success % SAVE_INTERVAL == 0 or i == total:
                            with cache_manager.cache_lock:
                                cache_manager.save_cache(new_cache)
            except Exception as e:
                src = futures[future]
                logger.error(f"处理文件异常 {src}: {e}", exc_info=True)
                wrapped_log(f"任务异常: {e}", "error")
            if progress_callback:
                progress_callback(i, total, f"进度 {i}/{total}", "progress")

    # 最终保存缓存，确保所有成功记录落盘
    if config.get("incremental") and not config.get("dry_run"):
        with cache_manager.cache_lock:
            cache_manager.save_cache(new_cache)
        wrapped_log(f"💾 最终缓存已保存，共 {len(new_cache)} 条", LOG_SUCCESS)

    wrapped_log(f"🎉 全部完成！成功处理 {success}/{total} 个文件", LOG_SUCCESS)
