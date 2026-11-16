#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕处理模块（完整版·含目录信息辅助匹配）
包含扫描、匹配、时间轴同步、整理、AI解析、批量重命名、缓存记录等功能
"""

from .cancellation import check_cancelled, ProcessingCancelled
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from .execution_mode import execution_scope, is_preview
from .path_safety import absolute_link_path, validate_target_path, validate_source_path, source_roots
from typing import List, Dict, Any, Optional, Callable

from . import cache_manager
from .json_store import path_lock
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
    """Read a fresh complete projection, retaining explicit offline target state."""
    from .media_library_cache import get_media_library_cache
    frame = get_media_library_cache(config)
    return {key: frame[key] for key in ('movies', 'tv_shows', 'issues')}


# ========== 字幕扫描（带缓存过滤，附加目录信息） ==========
def scan_subtitle_folder(folder_path: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """扫描指定文件夹内的所有字幕文件，已处理的字幕会标记 processed_info，不再跳过。"""
    folder = Path(folder_path)
    if not folder.exists():
        return []

    sub_exts = ['.ass', '.ssa', '.srt', '.vtt']
    subtitle_files = []
    processed_cache = cache_manager.load_cache()
    allowed_roots = source_roots(config)

    for ext in sub_exts:
        try:
            for sub_path in folder.rglob(f'*{ext}'):
                if not any(sub_path.resolve().is_relative_to(root) for root in allowed_roots):
                    continue
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
        check_cancelled()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            return float(data['format'].get('duration', 0))
    except ProcessingCancelled:
        raise
    except Exception:
        pass
    return None


# ========== ASS 字幕颜色代码修复 ==========
def _fix_ass_color_code(content: str) -> str:
    return re.sub(r'(&H[0-9A-Fa-f]+)&', r'\1', content)


# ========== 字幕时间轴同步 ==========
SUBTITLE_EXTENSIONS = {'.ass', '.ssa', '.srt', '.vtt'}


def _language_suffix(path: Path) -> str:
    match = re.search(r'\.(chs|cht|en|eng|jp|jpn|sc|tc|gb|big5)$', path.stem, re.I)
    return f".{match.group(1).lower()}" if match else ""


@dataclass
class SyncedSubtitle:
    """Own the temporary result until its consumer has published a durable copy.

    Use as a context manager (or call close); path expires when closed.
    """
    path: Path
    original: Path
    language_suffix: str
    workspace: tempfile.TemporaryDirectory

    def __fspath__(self):
        return str(self.path)

    def close(self):
        self.workspace.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@execution_scope
def sync_subtitle_with_ffsubsync(
    video_path: Path,
    subtitle_path: Path,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[SyncedSubtitle]:
    """Prepare and sync a private copy. The returned object owns its workspace."""
    check_cancelled()
    if is_preview(config):
        if log_func:
            log_func(f"🔍 [模拟] 字幕调轴: {subtitle_path}", LOG_INFO)
        return None
    if not FFSUBSYNC_AVAILABLE:
        if log_func:
            log_func("⚠️ ffsubsync 未安装，跳过字幕同步", LOG_WARNING)
        return None

    workspace = None
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5, check=True)
        if video_path.stat().st_size > 20 * 1024 ** 3:
            if log_func:
                log_func("⚠️ 视频超过 20 GB，跳过自动调轴", LOG_WARNING)
            return None
        workspace = tempfile.TemporaryDirectory(prefix='animeman-subtitle-')
        folder = Path(workspace.name)
        working = folder / ('input' + subtitle_path.suffix)
        shutil.copyfile(subtitle_path, working)
        if subtitle_path.suffix.lower() in {'.ass', '.ssa'}:
            import pysubs2
            import chardet
            raw = working.read_bytes()
            detected = chardet.detect(raw).get('encoding')
            content = None
            for encoding in dict.fromkeys([detected, 'utf-8', 'utf-16', 'gbk', 'shift-jis', 'latin-1']):
                if not encoding:
                    continue
                try:
                    content = raw.decode(encoding)
                    break
                except (UnicodeError, LookupError):
                    continue
            if content is None:
                raise ValueError("无法解码字幕")
            try:
                pysubs2.SSAFile.from_string(content)
            except ValueError as exc:
                if "invalid literal for int() with base 16" not in str(exc):
                    raise
                fixed = _fix_ass_color_code(content)
                if fixed == content:
                    raise
                # Only the private copy is repaired. Never write or back up in source.
                working.write_text(fixed, encoding=encoding)
                pysubs2.load(str(working))

        duration = _get_video_duration_seconds(video_path)
        video_to_use = video_path
        if duration and duration > 1800:
            segment = folder / 'segment.mkv'
            check_cancelled()
            trimmed = subprocess.run([
                'ffmpeg', '-y', '-i', str(video_path), '-t', '1800',
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', str(segment)
            ], capture_output=True, text=True, timeout=120)
            if trimmed.returncode == 0 and segment.is_file():
                video_to_use = segment
        output = folder / ('synced' + subtitle_path.suffix)
        check_cancelled()
        result = subprocess.run(['ffs', str(video_to_use), '-i', str(working), '-o', str(output)],
                                capture_output=True, text=True,
                                timeout=config.get('subtitle', {}).get('sync_timeout', 300))
        check_cancelled()
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise ValueError("ffsubsync 未生成有效输出")
        owned = SyncedSubtitle(output, subtitle_path, _language_suffix(subtitle_path), workspace)
        workspace = None  # Transfer lifetime to the consumer.
        if log_func:
            log_func(f"✅ 字幕同步完成: {subtitle_path.name}", LOG_SUCCESS)
        return owned
    except ProcessingCancelled:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, ImportError) as exc:
        if log_func:
            log_func(f"⚠️ 字幕调轴失败，使用原字幕: {exc}", LOG_WARNING)
        return None
    finally:
        if workspace is not None:
            workspace.cleanup()


@contextmanager
def _working_subtitle(video, subtitle, config, auto_sync, log_func):
    result = sync_subtitle_with_ffsubsync(video, subtitle, config, log_func) if auto_sync else None
    if result is None:
        yield subtitle, False
    else:
        with result:
            yield result.path, True


def _publish_subtitle(source, target, mode, *, overwrite, temporary=False):
    """Stage a new directory entry, never copy into an existing hard/symbolic link."""
    with path_lock(target):
        if (target.exists() or target.is_symlink()) and not overwrite:
            return False
        check_cancelled()
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.subtitle-', dir=target.parent) as folder:
            staged = Path(folder) / target.name
            # A synced file must not become a symlink into an expiring workspace.
            if temporary or mode == 'copy':
                shutil.copy2(source, staged)
                with staged.open('rb') as stream:
                    os.fsync(stream.fileno())
            elif not create_link(source.resolve(), staged, mode):
                shutil.copy2(source, staged)
            check_cancelled()
            if overwrite:
                os.replace(staged, target)
            else:
                # Atomic no-clobber publication, including broken existing symlinks.
                try:
                    os.link(staged, target, follow_symlinks=False)
                except FileExistsError:
                    return False
        return True


# ========== 字幕整理执行（带缓存写入） ==========
@execution_scope
def execute_subtitle_organization(
    subtitle_path: str,
    target_media: Dict[str, Any],
    config: Dict[str, Any],
    auto_sync: bool = False,
    log_func: Optional[Callable] = None
) -> bool:
    check_cancelled()
    sub_path = Path(subtitle_path)
    if not sub_path.is_file():
        return False
    target_dir = Path(target_media['target_dir'])
    target_video = Path(target_media['target_path'])
    name = target_video.stem + _language_suffix(sub_path) + sub_path.suffix
    target = validate_target_path(sub_path, target_dir / name, config, 'subtitle')
    if is_preview(config):
        if log_func:
            log_func(f"🔍 [模拟] 字幕整理: {sub_path.name} -> {target}", LOG_INFO)
        return True
    overwrite = config.get('subtitle_center', {}).get('overwrite_existing', False)
    if (target.exists() or target.is_symlink()) and not overwrite:
        if log_func:
            log_func(f"⏭️ 字幕已存在，跳过: {target.name}", LOG_INFO)
        return False
    try:
        with _working_subtitle(target_video, sub_path, config, auto_sync, log_func) as (working, temporary):
            if not _publish_subtitle(working, target,
                    config.get('subtitle_center', {}).get('link_mode', 'hard'),
                    overwrite=overwrite, temporary=temporary):
                return False
        try:
            with cache_manager.cache_lock:
                cache = cache_manager.load_cache()
                src_str = str(sub_path.resolve())
                cache[src_str] = {
                    'target': str(absolute_link_path(target)), 'source_path': src_str,
                    'fingerprint': _get_subtitle_fingerprint(sub_path), 'media_type': 'subtitle',
                    'title': target_media.get('title', ''), 'season': target_media.get('season'),
                    'episode': target_media.get('episode'), 'confidence': 100,
                    'processed_time': time.time()
                }
                cache_manager.save_cache(cache)
        except ProcessingCancelled:
            raise
        except Exception as exc:
            logger.warning(f"写入字幕缓存失败: {exc}")
            if log_func:
                log_func(f"⚠️ 写入字幕缓存失败: {exc}", LOG_WARNING)
        if log_func:
            log_func(f"✅ 字幕已整理: {target.name}", LOG_SUCCESS)
        return True
    except ProcessingCancelled:
        raise
    except Exception as exc:
        logger.error(f"字幕整理失败 {sub_path.name}: {exc}")
        if log_func:
            log_func(f"❌ 字幕整理失败 {sub_path.name}: {exc}", LOG_ERROR)
        return False


# ========== 视频处理时的自动字幕匹配 ==========
def find_subtitle_files(video_path: Path, config: Dict[str, Any]) -> List[Path]:
    base = video_path.stem
    found = []
    for directory in [video_path.parent] + [video_path.parent / name for name in
                                           ['Subs', 'subs', '字幕', 'Subtitles', 'subtitle']]:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if (path.is_file() and path.suffix.lower() in SUBTITLE_EXTENSIONS
                    and (path.stem == base or path.stem.startswith(base + '.'))):
                found.append(path)
    return found


@execution_scope
def process_subtitles_for_video(
    video_src: Path, video_target: Path, target_dir: Path, config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> int:
    if not config.get('subtitle', {}).get('enabled', True):
        return 0
    sub_files = find_subtitle_files(video_src, config)
    if is_preview(config):
        if log_func:
            log_func(f"🔍 [模拟] 关联字幕 {len(sub_files)} 个 -> {target_dir}", LOG_INFO)
        return 0
    processed = 0
    for subtitle in sub_files:
        check_cancelled()
        try:
            name = video_target.stem + _language_suffix(subtitle) + subtitle.suffix
            target = validate_target_path(subtitle, target_dir / name, config, 'subtitle')
            with _working_subtitle(video_src, subtitle, config,
                    config.get('subtitle', {}).get('auto_sync', False), log_func) as (working, temporary):
                mode = config.get('link_type', 'hard') if config.get('subtitle', {}).get('link_subtitles', True) else 'copy'
                if _publish_subtitle(working, target, mode, overwrite=True, temporary=temporary):
                    processed += 1
                    if log_func:
                        log_func(f"✅ 字幕已整理: {target.name}", LOG_SUCCESS)
        except ProcessingCancelled:
            raise
        except Exception as exc:
            logger.error(f"字幕处理失败 {subtitle.name}: {exc}")
            if log_func:
                log_func(f"❌ 字幕处理失败 {subtitle.name}: {exc}", LOG_ERROR)
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


@execution_scope
def batch_rename_subtitles(renames: List[Dict[str, str]], log_func: Optional[Callable] = None, config=None) -> Dict[str, Any]:
    """Validate the entire batch first; dependent/cyclic moves are rejected.

    Exclusive link + unlink supports same-filesystem regular files without
    overwriting a concurrently created destination. A failed move keeps source.
    """
    check_cancelled()
    config = config or {}
    results = []
    paths = []
    for item in renames:
        row = {'old_path': item.get('old_path') if isinstance(item, dict) else None,
               'new_path': item.get('new_path') if isinstance(item, dict) else None,
               'status': 'failed', 'error': ''}
        results.append(row)
        try:
            old = validate_source_path(row['old_path'], config)
            new = validate_source_path(row['new_path'], config)
            paths.append((old, new))
            if old.suffix.lower() not in SUBTITLE_EXTENSIONS or new.suffix.lower() not in SUBTITLE_EXTENSIONS:
                raise ValueError('仅允许字幕扩展名 ass/ssa/srt/vtt')
            if old.is_symlink() or not old.is_file():
                raise ValueError('源字幕必须是普通文件，禁止符号链接')
            if old == new:
                raise ValueError('新旧路径相同')
            if new.exists() or new.is_symlink():
                raise ValueError('目标已存在；不覆盖文件，不支持依赖或循环改名')
        except (ValueError, TypeError, OSError) as exc:
            if len(paths) < len(results):
                paths.append(None)
            row['error'] = str(exc)
    for position in (0, 1):
        counts = {}
        for pair in paths:
            if pair:
                counts[pair[position]] = counts.get(pair[position], 0) + 1
        for row, pair in zip(results, paths):
            if pair and counts[pair[position]] > 1:
                row['error'] = '重复源路径' if position == 0 else '重复目标路径'
    if any(row['error'] for row in results):
        for row in results:
            row['error'] = row['error'] or '整批校验失败，未执行改名'
        return {'success': 0, 'failed': len(results), 'planned': 0, 'results': results}
    preview = is_preview(config)
    success = failed = 0
    for row, (old, new) in zip(results, paths):
        check_cancelled()
        if preview:
            row['status'] = 'planned'
            continue
        try:
            with path_lock(new):
                # Recheck resolved parent boundaries immediately before mutation.
                validate_source_path(old, config)
                validate_source_path(new, config)
                if old.is_symlink() or not old.is_file():
                    raise ValueError('源文件已改变')
                new.parent.mkdir(parents=True, exist_ok=True)
                os.link(old, new, follow_symlinks=False)
                try:
                    old.unlink()
                except OSError:
                    # Undo only our own newly created entry, preserving source.
                    if os.path.samefile(old, new):
                        new.unlink()
                    raise
            row['status'] = 'success'
            success += 1
            if log_func:
                log_func(f"✅ 重命名: {old.name} -> {new.name}", LOG_SUCCESS)
        except ProcessingCancelled:
            raise
        except (OSError, ValueError) as exc:
            row['error'] = str(exc)
            failed += 1
            if log_func:
                log_func(f"❌ 重命名失败 {old.name}: {exc}", LOG_ERROR)
    return {'success': success, 'failed': failed, 'planned': len(results) if preview else 0, 'results': results}
