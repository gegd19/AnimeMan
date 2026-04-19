
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件夹级别的 AI 解析缓存
对于同一文件夹下的视频文件，一次性调用 AI 解析整个文件列表，
结果持久化存储，避免重复调用。
"""

import json
import hashlib
import time
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional

CACHE_FILE = "folder_ai_parse_cache.json"
DEFAULT_CACHE_TTL_DAYS = 90

_cache_lock = threading.RLock()


def _get_folder_fingerprint(folder_path: Path, video_extensions: List[str]) -> str:
    """
    计算文件夹指纹（仅基于视频文件，含一级子目录）
    移动文件夹后只要内部视频文件不变，指纹依然有效。
    """
    video_exts = {ext.lower() for ext in video_extensions}
    video_files = []

    def _collect(current: Path, depth: int):
        if depth > 2:
            return
        try:
            for item in current.iterdir():
                if item.is_file() and item.suffix.lower() in video_exts:
                    video_files.append(item)
                elif item.is_dir() and depth < 2 and not item.name.startswith('.'):
                    _collect(item, depth + 1)
        except PermissionError:
            pass

    _collect(folder_path, 1)

    # 基于文件名 + 大小 + 前1MB内容哈希
    features = []
    for f in sorted(video_files, key=lambda x: x.name):
        stat = f.stat()
        try:
            with open(f, 'rb') as fp:
                head = fp.read(1024 * 1024)
                content_hash = hashlib.md5(head).hexdigest()
        except Exception:
            content_hash = "unreadable"
        features.append(f"{f.name}|{stat.st_size}|{content_hash}")

    raw = "|".join(features) if features else str(folder_path.resolve())
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def load_folder_cache() -> Dict[str, Any]:
    """加载文件夹缓存"""
    with _cache_lock:
        path = Path(CACHE_FILE)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}


def save_folder_cache(cache: Dict[str, Any]):
    """保存文件夹缓存"""
    with _cache_lock:
        temp = CACHE_FILE + ".tmp"
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        Path(temp).replace(CACHE_FILE)


def get_cached_folder_parse(folder_path: Path, config: Dict, ttl_days: int = DEFAULT_CACHE_TTL_DAYS) -> Optional[Dict[str, Any]]:
    """
    获取文件夹的缓存解析结果（如果指纹匹配且未过期）
    """
    cache = load_folder_cache()
    folder_str = str(folder_path.resolve())
    video_exts = config.get("video_extensions", ['.mkv', '.mp4'])

    if folder_str in cache:
        entry = cache[folder_str]

        # 检查是否过期（优化项5）
        updated = entry.get("updated", 0)
        if updated and time.time() - updated > ttl_days * 86400:
            del cache[folder_str]
            save_folder_cache(cache)
            return None

        # 检查指纹是否匹配（优化项10）
        if entry.get("fingerprint") == _get_folder_fingerprint(folder_path, video_exts):
            raw = entry.get("parse_result")
            # 兼容新旧格式（优化项14的准备工作）
            return _parse_folder_result(raw)

    return None


def save_folder_parse_result(folder_path: Path, parse_result: Dict[str, Any], config: Dict):
    """
    保存文件夹的解析结果（自动压缩存储）
    """
    cache = load_folder_cache()
    folder_str = str(folder_path.resolve())
    video_exts = config.get("video_extensions", ['.mkv', '.mp4'])

    # 压缩存储（优化项14）
    compressed = _compress_folder_parse_result(parse_result)

    cache[folder_str] = {
        "fingerprint": _get_folder_fingerprint(folder_path, video_exts),
        "parse_result": compressed,
        "updated": time.time()
    }
    save_folder_cache(cache)


# ========== 压缩/解压辅助函数（为优化项14做准备） ==========

def _compress_folder_parse_result(raw: Dict) -> Dict:
    """压缩存储格式，减少冗余"""
    folder_defaults = {
        "media_type": raw.get("media_type"),
        "title": raw.get("folder_title"),
        "season": raw.get("season"),
        "year": raw.get("year")
    }
    compressed = {
        "folder_title": raw.get("folder_title"),
        "media_type": folder_defaults["media_type"],
        "season": folder_defaults["season"],
        "year": folder_defaults["year"],
        "files": {}
    }
    for fname, info in raw.get("files", {}).items():
        compressed["files"][fname] = {
            "ep": info.get("episode"),
            "ep_title": info.get("episode_title", "")[:50]
        }
        if info.get("season") != folder_defaults["season"]:
            compressed["files"][fname]["s"] = info.get("season")
    return compressed


def _decompress_folder_parse_result(compressed: Dict) -> Dict:
    """解压为原始格式供使用"""
    folder_title = compressed.get("folder_title")
    media_type = compressed.get("media_type")
    season = compressed.get("season")
    year = compressed.get("year")

    result = {
        "folder_title": folder_title,
        "media_type": media_type,
        "season": season,
        "year": year,
        "files": {}
    }
    for fname, info in compressed.get("files", {}).items():
        result["files"][fname] = {
            "media_type": media_type,
            "title": folder_title,
            "season": info.get("s", season),
            "episode": info.get("ep"),
            "episode_title": info.get("ep_title", ""),
            "year": year
        }
    return result


def _parse_folder_result(raw: Dict) -> Dict:
    """统一解析缓存数据，兼容新旧格式"""
    if "files" in raw:
        first_file = next(iter(raw["files"].values()), {})
        if "ep" in first_file and "media_type" not in first_file:
            return _decompress_folder_parse_result(raw)
        else:
            return raw
    return raw
