#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕处理模块（完整版·含目录信息辅助匹配）
包含扫描、匹配、时间轴同步、整理、AI解析、批量重命名、缓存记录等功能
"""

import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from . import cache_manager
from .file_linker import create_link
from .logger import get_logger

logger = get_logger(__name__)

try:
    from thefuzz import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False

try:
    import ffsubsync
    FFSUBSYNC_AVAILABLE = True
except ImportError:
    FFSUBSYNC_AVAILABLE = False

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_WARNING = "warning"
LOG_ERROR = "error"


# ========== 辅助函数 ==========
def _get_subtitle_fingerprint(sub_path: Path) -> str:
    """计算字幕文件指纹（基于修改时间）"""
    try:
        stat = sub_path.stat()
        return f"{sub_path.resolve()}|{stat.st_mtime}"
    except:
        return ""


# ========== 媒体库获取（增强容错，即使目标文件暂时缺失也保留剧集信息） ==========
def get_media_library_from_cache(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    从处理缓存中提取已入库媒体的详细信息，按剧集分组，返回结构化数据。
    即使目标文件暂时不存在，也尽可能保留剧集/电影的基础信息，避免前端展示丢失。
    """
    cache = cache_manager.load_cache()
    movies = []
    tv_shows = {}

    for src_str, entry in cache.items():
        if entry.get("media_type") == "failed":
            continue

        target_path = Path(entry.get("target", ""))
        media_type = entry.get("media_type")
        title = entry.get("title", "")
        year = entry.get("year", "")
        tmdb_id = entry.get("tmdb_id")
        alt_titles = entry.get("alternative_titles", [title] if title else [])

        target_exists = target_path.exists() if target_path else False
        if not target_exists and media_type:
            if target_path and str(target_path) != ".":
                logger.debug(f"目标文件缺失: {target_path}")

        if media_type == "movie":
            movies.append({
                "cache_key": src_str,
                "media_type": "movie",
                "title": title,
                "year": year,
                "target_path": str(target_path) if target_path else "",
                "target_dir": str(target_path.parent) if target_path else "",
                "tmdb_id": tmdb_id,
                "alternative_titles": alt_titles,
                "target_exists": target_exists,
                "processed_time": entry.get("processed_time", 0)
            })
        elif media_type == "tv":
            season = entry.get("season", 1)
            episode = entry.get("episode", 1)
            if tmdb_id not in tv_shows:
                show_dir = None
                poster_url = None
                if target_path and target_path.exists():
                    show_dir = target_path.parent.parent
                else:
                    for other_src, other_entry in cache.items():
                        if other_entry.get("tmdb_id") == tmdb_id and other_entry.get("media_type") == "tv":
                            other_target = Path(other_entry.get("target", ""))
                            if other_target.exists():
                                show_dir = other_target.parent.parent
                                break
                if show_dir:
                    fanart = show_dir / "fanart.jpg"
                    poster = show_dir / "poster.jpg"
                    if fanart.exists() or poster.exists():
                        poster_url = f"/media_poster/{tmdb_id}"
                tv_shows[tmdb_id] = {
                    "tmdb_id": tmdb_id,
                    "title": title,
                    "year": year,
                    "poster_url": poster_url,
                    "seasons": {},
                    "alternative_titles": alt_titles,
                }
            show = tv_shows[tmdb_id]
            if season not in show["seasons"]:
                show["seasons"][season] = {
                    "season_number": season,
                    "episodes": []
                }
            show["seasons"][season]["episodes"].append({
                "episode": episode,
                "title": entry.get("episode_title") or f"第 {episode} 集",
                "target_path": str(target_path) if target_path else "",
                "target_dir": str(target_path.parent) if target_path else "",
                "cache_key": src_str,
                "target_exists": target_exists,
                "processed_time": entry.get("processed_time", 0)
            })

    for show in tv_shows.values():
        for season_data in show["seasons"].values():
            season_data["episodes"].sort(key=lambda x: x["episode"])
        show["seasons"] = dict(sorted(show["seasons"].items()))

    return {
        "movies": movies,
        "tv_shows": list(tv_shows.values())
    }


# ========== 字幕扫描（带缓存过滤，附加目录信息） ==========
def scan_subtitle_folder(folder_path: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """扫描指定文件夹内的所有字幕文件，已处理的字幕会标记 processed_info，不再跳过。"""
    folder = Path(folder_path)
    if not folder.exists():
        return []

    sub_exts = ['.ass', '.ssa', '.srt', '.vtt']
    subtitle_files = []
    processed_cache = cache_manager.load_cache()

    for ext in sub_exts:
        try:
            for sub_path in folder.rglob(f'*{ext}'):
                src_str = str(sub_path.resolve())
                parent_dir = sub_path.parent.name
                grandparent_dir = sub_path.parent.parent.name if sub_path.parent.parent else ""

                item = {
                    "path": str(sub_path),
                    "name": sub_path.name,
                    "size": sub_path.stat().st_size,
                    "modified": sub_path.stat().st_mtime,
                    "parent_dir": parent_dir,
                    "grandparent_dir": grandparent_dir,
                }

                # 检查是否已处理
                if src_str in processed_cache:
                    entry = processed_cache[src_str]
                    if entry.get("media_type") != "failed":
                        target_path = Path(entry.get("target", ""))
                        item["processed_info"] = {
                            "target": str(target_path),
                            "title": entry.get("title", ""),
                            "season": entry.get("season"),
                            "episode": entry.get("episode"),
                            "media_type": entry.get("media_type"),
                            "target_exists": target_path.exists()
                        }
                subtitle_files.append(item)
        except PermissionError:
            continue

    # 排序：已处理优先？还是按集号？保持原有集号+语言排序
    def sort_key(item):
        name = item["name"]
        match = re.search(r'[-_\s]+(\d{1,3})(?:\.|$)', name)
        ep_num = int(match.group(1)) if match else 9999
        lower_name = name.lower()
        if 'zh-hans' in lower_name or '.chs' in lower_name or '简体' in lower_name:
            lang_priority = 0
        elif 'zh-hant' in lower_name or '.cht' in lower_name or '繁体' in lower_name:
            lang_priority = 1
        else:
            lang_priority = 2
        return (ep_num, lang_priority, name)

    subtitle_files.sort(key=sort_key)
    return subtitle_files


def match_subtitle_to_media(
    subtitle_name: str,
    media_library: Dict[str, Any],
    threshold: int = 60,
    context_dirs: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    MIN_SHOW_TITLE_RATIO = 50  # 剧集标题原始相似度阈值

    # ---------- 预处理查询字符串 ----------
    context_parts = [subtitle_name]
    if context_dirs:
        context_parts.extend(context_dirs)
    raw_query = " ".join(context_parts)

    clean_query = raw_query
    clean_query = re.sub(r'\.[^.]+$', '', clean_query)
    clean_query = re.sub(r'[\[\]\(\)_,.-]', ' ', clean_query)
    clean_query = re.sub(r'\b(1080p|720p|4k|hdr|hevc|x264|x265|aac|flac|web-dl|bluray|bdrip|danmu)\b', '', clean_query, flags=re.I)
    clean_query = re.sub(r'\s+', ' ', clean_query).strip().lower()

    # ---------- 提取季号和集号 ----------
    ep_match = re.search(r'[Ss](\d{1,2})[Ee](\d{1,2})', subtitle_name)
    season, episode = None, None
    if ep_match:
        season = int(ep_match.group(1))
        episode = int(ep_match.group(2))
    else:
        cn_match = re.search(r'第\s*(\d{1,3})\s*[集話话]', subtitle_name)
        if cn_match:
            episode = int(cn_match.group(1))
        else:
            num_match = re.search(r'\b(\d{1,3})\b', subtitle_name)
            if num_match:
                episode = int(num_match.group(1))

    candidates = []

    # ---------- 电影匹配（应用缩放） ----------
    movies = media_library.get("movies", [])
    for movie in movies:
        media_titles = movie.get("alternative_titles", [])
        if not media_titles:
            media_titles = [movie.get("title", "")]
        media_titles = [t for t in media_titles if t]

        best_title_ratio = 0
        for media_title in media_titles:
            media_title_clean = re.sub(r'[^\w\s]', ' ', media_title).strip().lower()
            if FUZZY_AVAILABLE:
                ratio = fuzz.partial_ratio(clean_query, media_title_clean)
            else:
                ratio = 100 if (media_title_clean in clean_query or clean_query in media_title_clean) else 0
            if ratio > best_title_ratio:
                best_title_ratio = ratio

        # 基础置信度 = 标题相似度 * 0.8（最高80）
        base_confidence = min(int(best_title_ratio * 0.8), 80)
        score = min(base_confidence, 100)  # 电影暂无额外奖惩
        if score >= threshold:
            candidates.append({
                "media": movie,
                "score": score,
                "match_type": "auto",
                "extracted_season": None,
                "extracted_episode": None,
            })

    # ---------- 剧集匹配 ----------
    tv_shows = media_library.get("tv_shows", [])
    if tv_shows:
        # 1. 找出标题匹配度最高的剧集
        best_show = None
        best_show_ratio = 0
        for show in tv_shows:
            show_titles = show.get("alternative_titles", [])
            if not show_titles:
                show_titles = [show.get("title", "")]
            show_titles = [t for t in show_titles if t]

            max_ratio = 0
            for title in show_titles:
                title_clean = re.sub(r'[^\w\s]', ' ', title).strip().lower()
                if FUZZY_AVAILABLE:
                    ratio = fuzz.partial_ratio(clean_query, title_clean)
                else:
                    ratio = 100 if (title_clean in clean_query or clean_query in title_clean) else 0
                if ratio > max_ratio:
                    max_ratio = ratio
            if max_ratio > best_show_ratio:
                best_show_ratio = max_ratio
                best_show = show

        # 2. 在最佳剧集内匹配单集
        if best_show and best_show_ratio >= MIN_SHOW_TITLE_RATIO:
            # 基础置信度 = 标题相似度 * 0.8（最高80）
            base_confidence = min(int(best_show_ratio * 0.8), 80)

            for season_num, season_data in best_show.get("seasons", {}).items():
                for ep in season_data.get("episodes", []):
                    ep_media = {
                        "media_type": "tv",
                        "title": best_show.get("title", ""),
                        "year": best_show.get("year", ""),
                        "season": season_num,
                        "episode": ep.get("episode"),
                        "target_path": ep.get("target_path", ""),
                        "target_dir": ep.get("target_dir", ""),
                        "cache_key": ep.get("cache_key", ""),
                        "tmdb_id": best_show.get("tmdb_id"),
                        "alternative_titles": best_show.get("alternative_titles", []),
                        "target_exists": ep.get("target_exists", True),
                    }

                    score = base_confidence

                    # 季号奖惩（±10）
                    if season is not None:
                        if season_num == season:
                            score += 10
                        else:
                            score -= 10

                    # 集号奖惩（±10）
                    if episode is not None:
                        if ep.get("episode") == episode:
                            score += 10
                        else:
                            score -= 10

                    score = max(0, min(score, 100))

                    if score >= threshold:
                        candidates.append({
                            "media": ep_media,
                            "score": score,
                            "match_type": "auto",
                            "extracted_season": season,
                            "extracted_episode": episode,
                        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates
# ========== 获取视频时长（秒） ==========
def _get_video_duration_seconds(video_path: Path) -> Optional[float]:
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(video_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return float(data['format'].get('duration', 0))
    except Exception:
        pass
    return None


# ========== ASS 字幕颜色代码修复 ==========
def _fix_ass_color_code(content: str) -> str:
    return re.sub(r'(&H[0-9A-Fa-f]+)&', r'\1', content)


# ========== 字幕时间轴同步 ==========
def sync_subtitle_with_ffsubsync(
    video_path: Path,
    subtitle_path: Path,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[Path]:
    """使用 ffsubsync 同步字幕时间轴，对大视频创建临时片段并自动清理"""
    if not FFSUBSYNC_AVAILABLE:
        if log_func:
            log_func(f"⚠️ ffsubsync 未安装，跳过字幕同步", LOG_WARNING)
        return None

    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5, check=True)
    except Exception as e:
        if log_func:
            log_func(f"❌ FFmpeg 不可用，无法进行字幕同步: {e}", LOG_ERROR)
        return None

    try:
        file_size_gb = video_path.stat().st_size / (1024 * 1024 * 1024)
        if file_size_gb > 20:
            if log_func:
                log_func(f"⚠️ 视频文件过大 ({file_size_gb:.1f} GB)，跳过自动调轴", LOG_WARNING)
            return None
    except Exception:
        pass

    # ASS 颜色代码修复（保持不变）
    if subtitle_path.suffix.lower() in ['.ass', '.ssa']:
        try:
            import pysubs2
            import chardet

            with open(subtitle_path, 'rb') as f:
                raw_data = f.read()
            detected = chardet.detect(raw_data)
            encoding = detected.get('encoding', 'utf-8')

            content = None
            try:
                content = raw_data.decode(encoding)
            except Exception:
                for enc in ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be', 'gbk', 'shift-jis', 'cp932', 'latin-1']:
                    try:
                        content = raw_data.decode(enc)
                        encoding = enc
                        break
                    except Exception:
                        continue
                if content is None:
                    raise ValueError("所有编码均无法解码该字幕文件")

            try:
                pysubs2.SSAFile.from_string(content)
            except ValueError as e:
                if "invalid literal for int() with base 16" in str(e):
                    if log_func:
                        log_func(f"⚠️ ASS 字幕颜色代码格式异常，尝试自动修复...", LOG_WARNING)

                    fixed_content = _fix_ass_color_code(content)
                    if fixed_content != content:
                        backup_path = subtitle_path.with_suffix(subtitle_path.suffix + '.bak')
                        shutil.copy2(subtitle_path, backup_path)
                        with open(subtitle_path, 'w', encoding=encoding) as f:
                            f.write(fixed_content)
                        if log_func:
                            log_func(f"🔧 已修复 ASS 字幕颜色代码格式并保存", LOG_INFO)

                        try:
                            pysubs2.load(str(subtitle_path))
                        except Exception as ex:
                            if log_func:
                                log_func(f"⚠️ 修复后仍无法加载 ASS 字幕，跳过调轴: {ex}", LOG_WARNING)
                            return None
                    else:
                        return None
                else:
                    return None
        except Exception:
            return None

    duration_sec = _get_video_duration_seconds(video_path)
    use_temp_video = False
    temp_video = None

    sync_timeout = config.get("subtitle", {}).get("sync_timeout", 300)
    synced_path = subtitle_path.with_suffix(f".synced{subtitle_path.suffix}")

    try:
        if duration_sec and duration_sec > 1800:
            if log_func:
                log_func(f"⏱️ 视频时长 {duration_sec/60:.1f} 分钟，创建前30分钟临时文件用于对齐", LOG_INFO)

            # ========== 优化项12：使用 NamedTemporaryFile 替代 mktemp ==========
            import tempfile
            temp_video = tempfile.NamedTemporaryFile(suffix='.mkv', delete=True)
            temp_video_path = Path(temp_video.name)
            cmd_ffmpeg = [
                'ffmpeg', '-y', '-i', str(video_path), '-t', '1800',
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                str(temp_video_path)
            ]
            result_ffmpeg = subprocess.run(cmd_ffmpeg, capture_output=True, text=True, timeout=120)
            if result_ffmpeg.returncode == 0 and temp_video_path.exists():
                use_temp_video = True
            else:
                temp_video.close()
                temp_video = None

        video_to_use = temp_video_path if use_temp_video else video_path
        cmd = ['ffs', str(video_to_use), '-i', str(subtitle_path), '-o', str(synced_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=sync_timeout)

        if result.returncode == 0 and synced_path.exists():
            if log_func:
                log_func(f"✅ 字幕同步完成: {synced_path.name}", LOG_SUCCESS)
            return synced_path
        else:
            return None

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None
    finally:
        # ========== NamedTemporaryFile 在 close 时自动删除，无需手动 unlink ==========
        if use_temp_video and temp_video:
            try:
                temp_video.close()
            except Exception:
                pass


# ========== 字幕整理执行（带缓存写入） ==========
def execute_subtitle_organization(
    subtitle_path: str,
    target_media: Dict[str, Any],
    config: Dict[str, Any],
    auto_sync: bool = False,
    log_func: Optional[Callable] = None
) -> bool:
    sub_path = Path(subtitle_path)
    if not sub_path.exists():
        return False

    target_dir = Path(target_media["target_dir"])
    target_video_path = Path(target_media["target_path"])
    video_stem = target_video_path.stem

    working_sub_path = sub_path
    if auto_sync:
        synced = sync_subtitle_with_ffsubsync(target_video_path, sub_path, config, log_func)
        if synced:
            working_sub_path = synced

    lang_suffix = ""
    name_without_ext = working_sub_path.stem
    lang_match = re.search(r'\.(chs|cht|en|eng|jp|jpn|sc|tc|gb|big5)$', name_without_ext, re.I)
    if lang_match:
        lang_suffix = f".{lang_match.group(1).lower()}"

    target_sub_name = f"{video_stem}{lang_suffix}{working_sub_path.suffix}"
    target_sub_path = target_dir / target_sub_name

    if target_sub_path.exists() and not config.get("subtitle_center", {}).get("overwrite_existing", False):
        if log_func:
            log_func(f"⏭️ 字幕已存在，跳过: {target_sub_name}", LOG_INFO)
        return False

    try:
        target_sub_path.parent.mkdir(parents=True, exist_ok=True)
        link_mode = config.get("subtitle_center", {}).get("link_mode", "hard")
        if link_mode == "copy":
            shutil.copy2(working_sub_path, target_sub_path)
            if log_func:
                log_func(f"📋 字幕已复制: {target_sub_name}", LOG_SUCCESS)
        else:
            if not create_link(working_sub_path, target_sub_path, link_mode, log_func):
                shutil.copy2(working_sub_path, target_sub_path)
                if log_func:
                    log_func(f"📋 链接失败，已复制: {target_sub_name}", LOG_INFO)

        try:
            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                src_str = str(sub_path.resolve())
                cache[src_str] = {
                    "target": str(target_sub_path.resolve()),
                    "fingerprint": _get_subtitle_fingerprint(sub_path),
                    "media_type": "subtitle",
                    "title": target_media.get("title", ""),
                    "season": target_media.get("season"),
                    "episode": target_media.get("episode"),
                    "confidence": 100,
                    "processed_time": time.time()
                }
                cache_manager.save_cache(cache)
        except Exception as e:
            logger.warning(f"写入字幕缓存失败: {e}")
            if log_func:
                log_func(f"⚠️ 写入字幕缓存失败: {e}", "warning")

        return True
    except Exception as e:
        logger.error(f"字幕整理失败 {sub_path.name}: {e}")
        if log_func:
            log_func(f"❌ 字幕整理失败 {sub_path.name}: {e}", LOG_ERROR)
        return False


# ========== 视频处理时的自动字幕匹配 ==========
def find_subtitle_files(video_path: Path, config: Dict[str, Any]) -> List[Path]:
    subtitle_exts = ['.ass', '.ssa', '.srt', '.vtt']
    base_name = video_path.stem
    parent = video_path.parent

    found_subs = []
    for ext in subtitle_exts:
        sub_path = parent / f"{base_name}{ext}"
        if sub_path.exists():
            found_subs.append(sub_path)

    for ext in subtitle_exts:
        pattern = f"{base_name}.*{ext}"
        for sub_path in parent.glob(pattern):
            if sub_path not in found_subs:
                found_subs.append(sub_path)

    sub_dirs = ['Subs', 'subs', '字幕', 'Subtitles', 'subtitle']
    for sub_dir_name in sub_dirs:
        sub_dir = parent / sub_dir_name
        if sub_dir.exists():
            for ext in subtitle_exts:
                pattern = f"{base_name}*{ext}"
                for sub_path in sub_dir.glob(pattern):
                    if sub_path not in found_subs:
                        found_subs.append(sub_path)
    return found_subs


def process_subtitles_for_video(
    video_src: Path,
    video_target: Path,
    target_dir: Path,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> int:
    if not config.get("subtitle", {}).get("enabled", True):
        return 0

    sub_files = find_subtitle_files(video_src, config)
    if not sub_files:
        return 0

    if log_func:
        log_func(f"📝 发现 {len(sub_files)} 个字幕文件", LOG_INFO)

    processed = 0
    video_stem = video_target.stem

    for sub_path in sub_files:
        lang_suffix = ""
        name_without_ext = sub_path.stem
        lang_match = re.search(r'\.(chs|cht|en|eng|jp|jpn|sc|tc|gb|big5)$', name_without_ext, re.I)
        if lang_match:
            lang_suffix = f".{lang_match.group(1).lower()}"

        final_sub_path = sub_path
        if config.get("subtitle", {}).get("auto_sync", False):
            synced = sync_subtitle_with_ffsubsync(video_src, sub_path, config, log_func)
            if synced:
                final_sub_path = synced

        target_sub_name = f"{video_stem}{lang_suffix}{final_sub_path.suffix}"
        target_sub_path = target_dir / target_sub_name

        try:
            if target_sub_path.exists():
                target_sub_path.unlink()
            if config.get("subtitle", {}).get("link_subtitles", True):
                if not create_link(final_sub_path, target_sub_path, config["link_type"], log_func):
                    shutil.copy2(final_sub_path, target_sub_path)
                    if log_func:
                        log_func(f"📋 链接失败，已复制: {target_sub_name}", LOG_INFO)
                else:
                    if log_func:
                        log_func(f"🔗 字幕链接成功: {target_sub_name}", LOG_SUCCESS)
            else:
                shutil.copy2(final_sub_path, target_sub_path)
                if log_func:
                    log_func(f"📋 字幕已复制: {target_sub_name}", LOG_INFO)
            processed += 1
        except Exception as e:
            logger.error(f"字幕处理失败 {sub_path.name}: {e}")
            if log_func:
                log_func(f"❌ 字幕处理失败 {sub_path.name}: {e}", LOG_ERROR)

    return processed


# ========== 本地正则解析字幕文件名 ==========
def local_parse_subtitle_files(
    subtitle_files: List[Dict[str, Any]],
    config: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    results = []
    for f in subtitle_files:
        name = f["name"]
        base = Path(name).stem
        original_ext = Path(name).suffix

        lang_match = re.search(r'\.(zh-Hans|chs|简体|zh-CN|zh-Hant|cht|繁体|eng|en|ja|jp)(?:\.|$)', base, re.I)
        lang = "chs"
        year = None
        if lang_match:
            lang_raw = lang_match.group(1).lower()
            if lang_raw in ('zh-hans', 'chs', '简体', 'zh-cn'):
                lang = "chs"
            elif lang_raw in ('zh-hant', 'cht', '繁体'):
                lang = "cht"
            elif lang_raw in ('eng', 'en'):
                lang = "eng"
            elif lang_raw in ('ja', 'jp'):
                lang = "jpn"
            base = re.sub(r'\.' + re.escape(lang_match.group(1)) + r'(?:\.|$)', '.', base, flags=re.I).strip('.')

        episode = None
        season = 1
        match = re.search(r'[-_\s]+(\d{1,3})(?:\.|$)', base)
        if match:
            episode = int(match.group(1))
            title = re.sub(r'[-_\s]+\d{1,3}(?:\.|$)', '', base).strip()
        else:
            match = re.search(r'(?:^|\s)(\d{1,3})(?:\.|$)', base)
            if match:
                episode = int(match.group(1))
                title = re.sub(r'\s*\d{1,3}(?:\.|$)', '', base).strip()
            else:
                episode = None
                title = base.strip()

        title = re.sub(r'\s+', ' ', title).strip()
        if not title:
            title = Path(name).stem.split('.')[0]

        media_type = "tv" if episode is not None else "movie"
        confidence = 85 if episode is not None else 60

        if media_type == "tv":
            suggested = f"{title} - S{season:02d}E{episode:02d}.{lang}{original_ext}"
        else:
            year_match = re.search(r'\b(19|20)\d{2}\b', title)
            year = year_match.group(0) if year_match else ""
            if year:
                suggested = f"{title} ({year}).{lang}{original_ext}"
            else:
                suggested = f"{title}.{lang}{original_ext}"

        results.append({
            "original_name": name,
            "path": f["path"],
            "title": title,
            "media_type": media_type,
            "season": season if media_type == "tv" else None,
            "episode": episode,
            "episode_title": "",
            "language": lang,
            "year": year if media_type == "movie" else None,
            "suggested_name": suggested,
            "confidence": confidence,
            "_parser": "local_regex"
        })

    return results


# ========== AI 解析字幕文件名（带本地回退） ==========
def ai_parse_subtitle_files(
    subtitle_files: List[Dict[str, Any]],
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> List[Dict[str, Any]]:
    from . import ai_client
    import json

    if not subtitle_files:
        return []

    ai_cfg = config.get("ai_parser", {})
    if not ai_cfg.get("enabled"):
        if log_func:
            log_func("ℹ️ AI 解析未启用，使用本地规则解析", "info")
        results = local_parse_subtitle_files(subtitle_files, config)
        for item in results:
            item["_parser"] = "local_regex"
        return results

    # 构建带目录上下文的文件列表（包含祖父目录和父目录）
    file_lines = []
    for f in subtitle_files[:100]:
        name = f["name"]
        parent = f.get("parent_dir", "")
        grandparent = f.get("grandparent_dir", "")
        if grandparent and grandparent != parent:
            context = f"[目录: {grandparent}/{parent}]"
        elif parent:
            context = f"[目录: {parent}]"
        else:
            context = ""
        file_lines.append(f"  - {name} {context}".strip())
    file_list_str = "\n".join(file_lines)
    if len(subtitle_files) > 100:
        file_list_str += f"\n  ... 等共 {len(subtitle_files)} 个文件"

    prompt = f"""你是一个专业的字幕文件命名专家。请分析以下字幕文件列表，推断每个文件对应的剧集/电影及正确的命名格式。

**核心规则**：
1. 如果文件名本身已经包含清晰的剧集标题（如 "暗杀教室 - S01E01.ass"），请直接提取。
2. 如果文件名不包含剧集标题（例如只有 "S01E01.ass" 或 "第01集.ass"），**必须结合方括号内的目录信息进行推断**。目录名通常就是剧集名称。
3. 对于目录信息，如果显示为 "暗杀教室/Season 1"，则剧集标题为 "暗杀教室"，季号为 1。
4. 如果文件名和目录名都无法判断，请尽量根据已有信息合理推测，并降低 confidence。

字幕文件列表：
{file_list_str}

**重要规则**：
- 季号如未明确标注，默认为 1。OVA/特辑/SP 等请设为 season=0。
- 语言后缀：`.zh-Hans` 或 `.chs` 表示简体中文（语言代码 `chs`），`.zh-Hant` 或 `.cht` 表示繁体中文（`cht`），`.eng` 表示英文（`eng`），`.jp` 或 `.jpn` 表示日文（`jpn`）。
- 输出格式必须是 JSON，每个文件包含以下字段：
  - `original_name`：原始文件名（必须与输入一致）
  - `title`：剧集/电影标题（字符串，不可为空）
  - `media_type`：`tv` 或 `movie`
  - `season`：整数，默认为 1
  - `episode`：整数
  - `episode_title`：单集标题，若无可留空字符串
  - `language`：`chs`、`cht`、`eng`、`jpn` 之一
  - `year`：发行年份，若可为 null
  - `suggested_name`：建议的完整新文件名（如 `暗杀教室 - S01E01.chs.ass`）
  - `confidence`：0-100 的整数，表示解析可信度（若依赖目录信息推断，请适当降低 confidence）

返回示例：
{{
  "files": [
    {{
      "original_name": "S01E01.jp.ass",
      "title": "暗杀教室",
      "media_type": "tv",
      "season": 1,
      "episode": 1,
      "episode_title": "",
      "language": "jpn",
      "year": null,
      "suggested_name": "暗杀教室 - S01E01.jpn.ass",
      "confidence": 85
    }}
  ]
}}

只返回合法 JSON，不要任何额外解释。"""

    if log_func:
        log_func(f"🤖 调用 AI 解析 {len(subtitle_files)} 个字幕文件", "info")

    resp = ai_client.call_ai_api(prompt, ai_cfg, log_func)
    if not resp:
        if log_func:
            log_func("⚠️ AI 无响应，回退到本地规则解析", "warning")
        results = local_parse_subtitle_files(subtitle_files, config)
        for item in results:
            item["_parser"] = "local_regex_fallback"
        return results

    def extract_json(text: str) -> Optional[dict]:
        try:
            return json.loads(text)
        except:
            pass
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except:
                pass
        try:
            import ast
            return ast.literal_eval(text)
        except:
            pass
        return None

    data = extract_json(resp)
    if not data:
        if log_func:
            log_func("⚠️ AI 响应无法解析为 JSON，回退到本地规则解析", "warning")
        results = local_parse_subtitle_files(subtitle_files, config)
        for item in results:
            item["_parser"] = "local_regex_fallback"
        return results

    files = data.get("files", [])
    if not files:
        if log_func:
            log_func("⚠️ AI 返回了 JSON 但 files 字段为空，回退到本地规则解析", "warning")
        results = local_parse_subtitle_files(subtitle_files, config)
        for item in results:
            item["_parser"] = "local_regex_fallback"
        return results

    for item in files:
        orig = item.get("original_name")
        matched = next((f for f in subtitle_files if f["name"] == orig), None)
        if matched:
            item["path"] = matched["path"]
        else:
            matched = next((f for f in subtitle_files if orig and orig in f["name"]), None)
            if matched:
                item["path"] = matched["path"]
                item["original_name"] = matched["name"]
            else:
                if log_func:
                    log_func(f"⚠️ 无法匹配原始文件: {orig}", "warning")

    valid_files = [item for item in files if "path" in item]
    if not valid_files:
        if log_func:
            log_func("⚠️ AI 解析无有效结果，回退到本地规则解析", "warning")
        results = local_parse_subtitle_files(subtitle_files, config)
        for item in results:
            item["_parser"] = "local_regex_fallback"
        return results

    for item in valid_files:
        item["_parser"] = "ai"

    if log_func:
        log_func(f"✅ AI 解析成功，有效结果 {len(valid_files)} 个", "success")

    return valid_files

# ========== AI 匹配字幕到指定剧集 ==========
def ai_match_subtitles_to_show(
    subtitle_files: List[Dict[str, Any]],
    show_info: Dict[str, Any],
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> List[Dict[str, Any]]:
    from . import ai_client
    import json
    from pathlib import Path

    if not subtitle_files:
        return []

    ai_cfg = config.get("ai_parser", {})
    if not ai_cfg.get("enabled"):
        if log_func:
            log_func("❌ AI 解析未启用", "error")
        return []

    show_title = show_info.get("title", "")
    show_year = show_info.get("year", "")
    seasons = show_info.get("seasons", {})

    episode_targets = {}
    episode_details = []
    for season_num, season_data in seasons.items():
        for ep in season_data.get("episodes", []):
            target_path = Path(ep.get("target_path", ""))
            target_stem = target_path.stem
            key = (int(season_num), int(ep["episode"]))
            episode_targets[key] = target_stem
            episode_details.append({
                "season": int(season_num),
                "episode": int(ep["episode"]),
                "title": ep.get("title", ""),
                "target_stem": target_stem
            })

    table_lines = []
    for ep in episode_details[:20]:
        table_lines.append(f"S{ep['season']:02d}E{ep['episode']:02d}: '{ep['target_stem']}'")
    episode_table = "\n".join(table_lines)
    if len(episode_details) > 20:
        episode_table += f"\n... 等共 {len(episode_details)} 集"

    file_names = [f["name"] for f in subtitle_files]
    file_list_str = "\n".join([f"  - {name}" for name in file_names[:50]])
    if len(file_names) > 50:
        file_list_str += f"\n  ... 等共 {len(file_names)} 个文件"

    prompt = f"""你是一个字幕文件匹配专家。请将以下字幕文件匹配到指定剧集的正确集数，并直接使用对应视频的目标文件名（仅更改语言后缀和扩展名）。

目标剧集：{show_title} ({show_year})
TMDB ID: {show_info.get('tmdb_id')}
剧集文件命名对照（部分）：
{episode_table}

字幕文件列表：
{file_list_str}

**任务**：
1. 分析每个字幕文件名，判断它属于哪一季哪一集。集号从文件名中提取（如 "04" 表示第 4 集）。
2. 从上面对照表中找到对应 SXXEXX 的目标文件名（target_stem）。
3. 语言从字幕文件名后缀判断：zh-Hans/简体/chs → 语言代码 'chs'，zh-Hant/繁体/cht → 'cht'，en/eng → 'eng'。
4. 新文件名格式为：`{{target_stem}}.{{lang}}.扩展名`。

返回 JSON 格式：
{{
  "matches": [
    {{
      "original_name": "Ragna Crimson - 04.zh-Hans.srt",
      "season": 1,
      "episode": 4,
      "episode_title": "执行",
      "language": "chs",
      "suggested_name": "狩龙人拉格纳 (2023) - S01E04 - 执行.chs.ass",
      "confidence": 95
    }}
  ]
}}

只返回合法 JSON，不要任何额外解释。"""

    if log_func:
        log_func(f"🤖 调用 AI 匹配字幕到剧集: {show_title}", "info")

    resp = ai_client.call_ai_api(prompt, ai_cfg, log_func)
    if not resp:
        if log_func:
            log_func("❌ AI 无响应", "error")
        return []

    def extract_json(text: str) -> Optional[dict]:
        try:
            return json.loads(text)
        except:
            pass
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except:
                pass
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except:
                pass
        return None

    data = extract_json(resp)
    if not data:
        if log_func:
            log_func("❌ AI 响应无法解析为 JSON", "error")
        return []

    matches = data.get("matches", [])
    if not matches:
        if log_func:
            log_func("⚠️ AI 返回了 JSON 但 matches 字段为空", "warning")
        return []

    for item in matches:
        orig = item.get("original_name")
        matched = next((f for f in subtitle_files if f["name"] == orig), None)
        if matched:
            item["path"] = matched["path"]
        else:
            matched = next((f for f in subtitle_files if orig and orig in f["name"]), None)
            if matched:
                item["path"] = matched["path"]
                item["original_name"] = matched["name"]

        season = int(item.get("season", 1))
        episode = int(item.get("episode", 1))
        target_stem = episode_targets.get((season, episode))
        if target_stem:
            lang = item.get("language", "chs")
            if "path" in item:
                ext = Path(item["path"]).suffix
            else:
                ext = ".ass"
            item["suggested_name"] = f"{target_stem}.{lang}{ext}"
            matched_ep = next((ep for ep in episode_details if ep["season"]==season and ep["episode"]==episode), None)
            if matched_ep:
                item["episode_title"] = matched_ep["title"]

    valid_matches = [item for item in matches if "path" in item]
    if log_func:
        log_func(f"✅ AI 匹配成功，有效结果 {len(valid_matches)} 个", "success")

    return valid_matches


def batch_rename_subtitles(renames: List[Dict[str, str]], log_func: Optional[Callable] = None) -> Dict[str, int]:
    success = 0
    failed = 0
    for item in renames:
        old = Path(item["old_path"])
        new = Path(item["new_path"])
        if not old.exists():
            failed += 1
            continue
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            success += 1
            if log_func:
                log_func(f"✅ 重命名: {old.name} -> {new.name}", "success")
        except Exception as e:
            logger.error(f"重命名失败 {old.name}: {e}")
            failed += 1
            if log_func:
                log_func(f"❌ 重命名失败 {old.name}: {e}", "error")
    return {"success": success, "failed": failed}
