#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件夹级AI批量解析逻辑
优化：
- 支持纯数字文件名触发批量解析
- 智能搜索 TMDB 获取剧集结构，若多结果则调用 AI 选择
- 缓存 TMDB 选择和结构信息，避免重复调用
- AI选择时仅发送标题、年份、首播日期，减少 token 消耗
- 当 anitopy 解析出英文缩写而文件夹名为中文时，也触发 TMDB 结构辅助
- 批量解析失败时，自动回退到单文件 AI 解析作为兜底
- 只将前5个候选交给 AI 选择
- 代理支持：所有 TMDB 请求均传递 proxy 参数
"""

import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List, Tuple

from . import folder_ai_cache, ai_client, tmdb_client
from .logger import get_logger

logger = get_logger(__name__)

# 缓存 TMDB 搜索结果，避免同一文件夹重复搜索
_tmdb_search_cache: Dict[str, Dict] = {}
# AI 选择时最多考虑的候选数量
MAX_CANDIDATES_FOR_AI_SELECTION = 5


def _search_tmdb_for_folder(
    folder_name: str,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[List[Dict]]:
    """
    使用清洗后的文件夹名搜索 TMDB 剧集。
    返回候选列表，失败返回 None。
    """
    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")

    # 清洗文件夹名
    clean_name = re.sub(r'[\[\(]?(19|20)\d{2}[\]\)]?', '', folder_name)
    clean_name = re.sub(r'\b(1080p|720p|4K|HDR|HEVC|x264|x265|AAC|WEB-DL|BluRay|BDRip|S\d{1,2})\b', '', clean_name, flags=re.I)
    clean_name = re.sub(r'[\[\]\(\)【】]', ' ', clean_name)
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    if not clean_name:
        return None

    try:
        results = tmdb_client.search_tmdb_multi("tv", clean_name, None, api_key, language, None, proxy=proxy)
        if not results:
            if log_func:
                log_func(f"⚠️ TMDB 搜索无结果: {clean_name}", "warning")
            return None
        return results
    except Exception as e:
        logger.warning(f"TMDB 搜索失败: {e}")
        if log_func:
            log_func(f"⚠️ TMDB 搜索失败: {e}", "warning")
        return None


def _ai_select_tmdb_series(
    folder_path: Path,
    candidates: List[Dict],
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[Dict]:
    """
    调用 AI 从多个 TMDB 候选剧集中选择最佳匹配。
    只发送标题、年份、首播日期等关键信息，减少 token。
    """
    ai_cfg = config.get("ai_parser", {})
    if not ai_cfg.get("enabled"):
        return None

    # 限制候选数量
    limited_candidates = candidates[:MAX_CANDIDATES_FOR_AI_SELECTION]

    if log_func:
        log_func(f"🤖 TMDB 搜索返回 {len(candidates)} 个候选，取前 {len(limited_candidates)} 个调用 AI 选择...", "info")

    # 构建精简候选描述（仅标题、年份、首播日期）
    candidates_desc = []
    for idx, item in enumerate(limited_candidates, 1):
        title = item.get("name") or item.get("title")
        first_air = item.get("first_air_date", "")
        year = first_air[:4] if first_air else "未知"
        candidates_desc.append(f"{idx}. {title} ({year})")

    candidates_text = "\n".join(candidates_desc)

    prompt = f"""你是影视文件识别专家。请从以下 TMDB 搜索结果中选择与文件夹最匹配的剧集。

文件夹路径：{folder_path}
文件夹名称：{folder_path.name}

候选列表：
{candidates_text}

**选择规则**：
1. 标题与文件夹名完全相同或高度相似的优先。
2. 若有年份信息，优先选择与文件夹名中的年份相符的。
3. 注意避免选择续作、外传、重制版，除非文件夹名明确包含对应关键词。

请直接返回候选编号（1-{len(limited_candidates)}），例如：3"""

    try:
        resp = ai_client.call_ai_api(prompt, ai_cfg, log_func)
        if resp:
            match = re.search(r'\b([1-9])\b', resp)  # 仅匹配1-9，因为最多5个候选
            if match:
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(limited_candidates):
                    selected = limited_candidates[idx]
                    if log_func:
                        title = selected.get("name") or selected.get("title")
                        log_func(f"✅ AI 选择剧集: {title} (ID: {selected.get('id')})", "success")
                    return selected
    except Exception as e:
        logger.warning(f"AI 选择 TMDB 剧集失败: {e}")
        if log_func:
            log_func(f"⚠️ AI 选择 TMDB 剧集失败: {e}", "warning")
    return None


def _get_tmdb_structure(
    tmdb_id: int,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[str]:
    """
    根据 TMDB ID 获取剧集的完整季集结构信息。
    返回格式化后的文本，若失败则返回 None。
    """
    api_key = config["tmdb_api"]["api_key"]
    language = config["tmdb_api"].get("language", "zh-CN")
    proxy = config.get("tmdb_api", {}).get("proxy")

    try:
        details = tmdb_client.get_tmdb_details("tv", tmdb_id, api_key, language, log_func, proxy=proxy)
        if not details:
            return None

        title = details.get("name") or details.get("original_name")
        seasons = details.get("seasons", [])
        structure_lines = []
        total_episodes = 0
        for s in seasons:
            sn = s.get("season_number", 0)
            if sn == 0:
                continue
            ep_count = s.get("episode_count", 0)
            total_episodes += ep_count
            structure_lines.append(f"第{sn}季: {ep_count}集")

        if not structure_lines:
            return None

        structure_text = f"剧集: {title}\n" + "\n".join(structure_lines) + f"\n总计: {len(structure_lines)}季, {total_episodes}集"
        return structure_text

    except Exception as e:
        logger.warning(f"获取 TMDB 结构失败: {e}")
        if log_func:
            log_func(f"⚠️ 获取 TMDB 结构失败: {e}", "warning")
        return None


def _should_use_tmdb_structure(
    info: Dict[str, Any],
    folder_path: Path
) -> bool:
    """
    判断是否需要获取 TMDB 结构来辅助解析。
    条件：
    1. anitopy 解析出的标题是纯英文/数字，而文件夹名包含中文。
    2. 或者解析出的标题长度过短（可能是缩写）。
    """
    title = info.get("title", "")
    folder_name = folder_path.name

    # 检查是否有中文
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', folder_name))
    title_has_chinese = bool(re.search(r'[\u4e00-\u9fff]', title))

    # 标题是纯英文/数字且文件夹有中文
    if has_chinese and not title_has_chinese:
        return True

    # 标题过短（可能为缩写）
    if len(title.strip()) <= 5 and len(folder_name) > 5:
        return True

    return False


def _get_tmdb_info_for_folder(
    folder_path: Path,
    config: Dict[str, Any],
    info: Optional[Dict[str, Any]] = None,
    log_func: Optional[Callable] = None
) -> Tuple[Optional[int], Optional[str]]:
    """
    获取文件夹对应的 TMDB 剧集 ID 和结构信息（带缓存）。
    如果 info 提供且标题疑似缩写，强制触发 TMDB 搜索。
    返回 (tmdb_id, structure_text)，失败返回 (None, None)。
    """
    folder_key = str(folder_path.resolve())

    # 检查缓存
    if folder_key in _tmdb_search_cache:
        cached = _tmdb_search_cache[folder_key]
        if log_func:
            log_func(f"📦 命中 TMDB 选择缓存: {cached.get('title')} (ID: {cached.get('tmdb_id')})", "info")
        return cached.get("tmdb_id"), cached.get("structure_text")

    # 决定是否搜索
    should_search = True
    if info and not _should_use_tmdb_structure(info, folder_path):
        # 不强制搜索，但为了结构信息，如果文件名异常还是搜索
        pass

    # 搜索 TMDB
    candidates = _search_tmdb_for_folder(folder_path.name, config, log_func)
    if not candidates:
        return None, None

    selected = None
    if len(candidates) == 1:
        selected = candidates[0]
        if log_func:
            title = selected.get("name") or selected.get("title")
            log_func(f"🎯 TMDB 唯一匹配: {title} (ID: {selected.get('id')})", "success")
    else:
        # 多结果，调用 AI 选择
        selected = _ai_select_tmdb_series(folder_path, candidates, config, log_func)
        if not selected:
            # AI 选择失败，回退到第一个结果
            selected = candidates[0]
            if log_func:
                title = selected.get("name") or selected.get("title")
                log_func(f"⚠️ AI 选择失败，回退到首个结果: {title}", "warning")

    tmdb_id = selected.get("id")
    title = selected.get("name") or selected.get("title")

    # 获取结构信息
    structure_text = _get_tmdb_structure(tmdb_id, config, log_func)

    # 写入缓存
    _tmdb_search_cache[folder_key] = {
        "tmdb_id": tmdb_id,
        "title": title,
        "structure_text": structure_text
    }

    return tmdb_id, structure_text


def try_folder_ai_batch(
    src: Path,
    config: Dict[str, Any],
    info: Dict[str, Any],
    force_tmdb_id: Optional[int],
    log_func: Optional[Callable] = None
) -> Optional[Dict[str, Any]]:
    """
    尝试使用文件夹级AI批量解析。
    返回更新后的 info 字典（如果成功），否则返回 None。
    如果批量解析失败，会尝试单文件 AI 解析作为兜底。
    """
    # 触发条件：anitopy 解析为 S01E01（典型的解析失败回退值）
    if not (info.get("_parser") == "anitopy"
            and info.get("season") == 1
            and info.get("episode") == 1
            and not force_tmdb_id
            and config.get("ai_parser", {}).get("enabled")):
        return None

    # 检查文件名是否值得触发批量解析：方括号数字 或 纯数字
    stem = src.stem
    is_bracket_number = bool(re.search(r'\[\d+\]', src.name))
    is_pure_number = bool(re.match(r'^\d+$', stem))

    # 或者 anitopy 解析出的标题疑似缩写（英文而文件夹为中文）
    title_suspect = _should_use_tmdb_structure(info, src.parent)

    if not (is_bracket_number or is_pure_number or title_suspect):
        return None

    if log_func:
        if is_bracket_number:
            trigger_type = "方括号数字"
        elif is_pure_number:
            trigger_type = "纯数字"
        else:
            trigger_type = "标题缩写/不匹配"
        log_func(f"🔍 检测到文件名异常（{trigger_type}）且解析为 S01E01，尝试文件夹 AI 批量解析...", "info")

    folder_path = src.parent

    # 获取 TMDB 结构信息（含 AI 辅助选择）
    tmdb_id, tmdb_structure = _get_tmdb_info_for_folder(folder_path, config, info, log_func)
    if tmdb_structure and log_func:
        log_func(f"📊 已获取 TMDB 结构信息，将辅助 AI 计算季集号", "info")

    # 检查文件夹 AI 缓存
    cached_batch = folder_ai_cache.get_cached_folder_parse(folder_path, config)
    batch_result = None

    if cached_batch:
        batch_result = cached_batch
        if log_func:
            log_func(f"📦 命中文件夹 AI 批量解析缓存: {folder_path.name}", "success")
    else:
        video_files = []
        for ext in config.get("video_extensions", [".mkv", ".mp4"]):
            for f in folder_path.glob(f"*{ext}"):
                if f.is_file():
                    video_files.append(f)
        if video_files:
            if log_func:
                log_func(f"🤖 调用 AI 批量解析文件夹: {folder_path.name} (共 {len(video_files)} 个文件)", "info")

            try:
                batch_result = ai_client.parse_folder_with_ai(
                    folder_path, video_files, config, log_func,
                    tmdb_structure=tmdb_structure or ""
                )
                if batch_result:
                    folder_ai_cache.save_folder_parse_result(folder_path, batch_result, config)
                else:
                    if log_func:
                        log_func(f"⚠️ AI 批量解析返回空结果", "warning")
            except Exception as e:
                logger.warning(f"AI 批量解析异常: {e}")
                if log_func:
                    log_func(f"⚠️ AI 批量解析异常: {e}", "warning")
        else:
            if log_func:
                log_func(f"⚠️ 文件夹内无视频文件，跳过批量解析", "warning")

    # 尝试从批量结果中获取当前文件信息
    if batch_result and "files" in batch_result:
        file_info = batch_result["files"].get(src.name)
        if file_info:
            info["season"] = file_info.get("season", info["season"])
            info["episode"] = file_info.get("episode", info["episode"])
            info["title"] = file_info.get("title") or batch_result.get("folder_title") or info["title"]
            info["_from_folder_ai_batch"] = True
            if log_func:
                log_func(f"✅ 从批量解析中获取集数: S{info['season']:02d}E{info['episode']:02d}", "success")
            return info

    # 批量解析失败或未覆盖当前文件，尝试单文件 AI 解析作为兜底
    if log_func:
        log_func(f"⚠️ 批量解析未覆盖当前文件，尝试单文件 AI 解析...", "warning")

    try:
        single_result = ai_client.parse_filename_with_ai(src, config, log_func)
        if single_result and single_result.get("media_type") in ("movie", "tv"):
            single_result["_from_ai"] = True
            if log_func:
                log_func(f"✅ 单文件 AI 解析成功", "success")
            return single_result
    except Exception as e:
        logger.warning(f"单文件 AI 解析失败: {e}")
        if log_func:
            log_func(f"❌ 单文件 AI 解析失败: {e}", "error")

    return None
