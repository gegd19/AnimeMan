#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 统一客户端
支持单文件解析和文件夹批量解析
使用 system + user 消息结构以启用上下文缓存
优化：
- 改进文件夹名清洗逻辑，避免过度清洗
- 增强 JSON 解析鲁棒性
"""

import json
from .ai_budget import consume_recognition_call, with_recognition_budget
from .cancellation import check_cancelled, ProcessingCancelled
from .parse_contract import normalize_media,normalize_folder,file_id
from .log_redaction import redact
from .failure_policy import note_error
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_ERROR = "error"
LOG_WARNING = "warning"


def create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session


def call_ai_api(
    prompt: str,
    ai_config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[str]:
    return call_ai_api_with_messages(
        messages=[{"role": "user", "content": prompt}],
        ai_config=ai_config,
        log_func=log_func
    )


def call_ai_api_with_messages(
    messages: List[Dict[str, str]],
    ai_config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Optional[str]:
    check_cancelled()
    provider = ai_config.get("provider", "deepseek")
    api_key = ai_config.get("api_key")
    model = ai_config.get("model", "deepseek-flash")
    base_url = ai_config.get("base_url", "https://api.deepseek.com")
    temperature = ai_config.get("temperature", 0.7)
    max_tokens = ai_config.get("max_tokens", 500)
    timeout = ai_config.get("timeout", 30)

    url_map = {
        "deepseek": f"{base_url}/v1/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    }
    url = url_map.get(provider)
    if not url:
        if log_func:
            log_func(f"❌ 不支持的 AI 提供商: {provider}", LOG_ERROR)
        return None

    if log_func:
        log_func(f"🤖 调用 AI API: {provider} 模型 {model}", LOG_INFO)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    consume_recognition_call()
    session = create_session()
    try:
        start = time.time()
        resp = session.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        check_cancelled()
        elapsed = time.time() - start
        if log_func:
            log_func(f"✅ AI 响应成功 ({elapsed:.2f}s)", LOG_SUCCESS)
        return resp.json()['choices'][0]['message']['content'].strip()
    except ProcessingCancelled:
        raise
    except Exception as e:
        note_error(e)
        if log_func:
            log_func(f"❌ AI API 调用失败: {redact(e)}", LOG_ERROR)
        return None


# ========== 系统提示词 ==========
SYSTEM_FOLDER_PARSE = """你是影视文件名解析专家。分析文件夹及视频文件，返回严格 JSON。

**TMDB 剧集结构信息（权威数据）**：
{tmdb_structure}

规则：
1. 剧集标题从文件夹名提取。若含"第二季"/"Season 2"，记录 season=2。
2. 对于每个文件，从文件名中提取集号（方括号数字、纯数字、EPxx 等）。
3. **关键**：如果文件名中的集号是绝对集号（如 1072），请根据上方 TMDB 结构信息，计算出正确的季号和季内集号。
   例如：第1季 61集，第2季 62集，则绝对集号 100 = 第2季第39集。
4. OVA/特典/SP/剧场版 → season=0。
5. 不凭文件数量认定季号；无法确定时返回 unknown，不补 season/episode=1。
6. 语言标记（.chs/.cht）仅用于建议文件名。

返回格式：
{
  "folder_title": "剧集标题",
  "media_type": "tv",
  "season": 2,
  "year": 2023,
  "files": {
    "第25集.mkv": {"media_type": "tv", "title": "剧集标题", "season": 2, "episode": 1, "episode_title": ""},
    "1072.mkv": {"media_type": "tv", "title": "剧集标题", "season": 21, "episode": 8}
  }
}
只返回 JSON，禁止任何额外文字。"""

SYSTEM_FILE_PARSE = """你是影视文件名解析专家。分析文件路径，返回严格 JSON。

规则：
1. 优先从目录名提取剧集标题和季数。
2. 文件名若只有集号（如"第28集.mkv"），结合目录名推断季/集。
3. **特辑/OVA/OAD/SP/剧场版必须设为 season=0**。
   - 文件名中包含方括号数字如 [01]、[02]、[03]，且目录名中有 "SS"、"Case"、"Sinners"、"罪与罚" 等特辑标识词 → season=0，episode=方括号内的数字。
   - 文件名中含 ".5"、".9" 等小数也视为特辑，season=0，episode 取整数部分。
4. 若有多个季目录（如 Season 1/Season 2），请提取正确的季号。
5. 如果文件名包含明确的集号标识（如 [14]、 - 14、EP14 等），请直接使用该数字作为 episode。

返回格式：
{
  "media_type": "tv",
  "title": "剧集标题",
  "search_title": "剧集标题",
  "year": 2023,
  "season": 1,
  "episode": 1,
  "episode_title": "",
  "alternative_titles": [],
  "year_guess": null,
  "corrected_season": null,
  "corrected_episode": null
}
无法确定的季/集号使用 null 或 unknown，不默认第一集。只返回 JSON。"""

SYSTEM_LONG_SERIES = """你是一个专业的影视媒体分析专家。请分析以下超长剧集文件夹的宏观结构，无需处理每个具体文件。

请根据以上信息推断该剧集的宏观属性，并返回严格 JSON 格式：
{
  "folder_title": "剧集标题",
  "media_type": "tv",
  "year": 发行年份或 null,
  "has_seasons": true或false,
  "episode_numbering": "absolute" 或 "season_based",
  "season_mapping": {} 或具体的季到集号范围映射,
  "note": "简短说明"
}

注意：
- 如果该剧集在 TMDB 上是以绝对集号排列（如《名侦探柯南》），则 episode_numbering 为 "absolute"，season_mapping 留空。
- 如果有明确的季划分（例如文件夹内有 Season 1、Season 2 子目录），则 has_seasons 为 true，并根据文件名推断每季的起始集号。
- 如果文件名中直接包含季号和集号（如 S01E01），则 episode_numbering 为 "season_based"，AI 无需提供具体映射，本地程序会自行解析。

只返回合法 JSON，不要任何额外解释。"""


# ========== 增强版 JSON 解析函数 ==========
def _parse_ai_json_response(resp, log_func=None):
    if not isinstance(resp,str):return None
    text=resp.strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I)
        text=re.sub(r'\s*```$','',text)
    try:
        def invalid_constant(value):raise ValueError(f'非有限 JSON 数字：{value}')
        def unique_object(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('重复 JSON 字段，拒绝猜测')
                result[key]=value
            return result
        value=json.loads(text,parse_constant=invalid_constant,object_pairs_hook=unique_object)
        return value if isinstance(value,dict) else None
    except (ValueError,TypeError):
        if log_func:log_func('AI 响应不是有效 JSON 对象，交给回退处理',LOG_WARNING)
        return None


def _clean_folder_name_for_ai(raw_name: str) -> str:
    """
    清洗文件夹名，移除压制组、画质等干扰信息。
    改进：保留更多原始信息，避免过度清洗导致搜索词变成技术词汇。
    """
    # 只移除明显的压制组标签（方括号内纯英文数字组合）
    cleaned = re.sub(r'\[[A-Za-z0-9\-_&! ]+\]', ' ', raw_name)
    cleaned = re.sub(r'【[^】]+】', ' ', cleaned)

    # 移除圆括号内的纯技术标签（但保留可能包含中文或年份的）
    cleaned = re.sub(r'\((?:1080p|720p|4k|2160p|HDR|HEVC|x264|x265|AAC|WEB-DL|BluRay|BDRip|Hi10p)[^)]*\)', ' ', cleaned, flags=re.I)

    # 移除独立的画质/编码关键词
    noise_keywords = [
        '1080p', '720p', '480p', '4k', '2160p', 'uhd',
        'hevc', 'x264', 'x265', 'h264', 'h265', 'avc', 'av1', 'hi10p',
        'aac', 'flac', 'dts', 'ac3', 'eac3', 'truehd', 'opus',
        'web-dl', 'webrip', 'bdrip', 'bluray', 'blu-ray', 'dvdrip', 'hdtv',
        'complete', 'fin', 'end'
    ]
    for kw in noise_keywords:
        cleaned = re.sub(rf'\b{kw}\b', '', cleaned, flags=re.I)

    # 合并多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # 如果清洗后为空或过短，返回原始名称
    if len(cleaned) < 3:
        return raw_name
    return cleaned


# ========== 业务函数 ==========

@with_recognition_budget
def parse_folder_with_ai(
    folder_path: Path,
    video_files: List[Path],
    config: Dict[str, Any],
    log_func: Optional[Callable] = None,
    tmdb_structure: str = ""
) -> Dict[str, Any]:
    files=list(video_files)
    combined={'folder_title':'','media_type':'unknown','files':{},'unparsed_files':[]}
    try:
        for offset in range(0,len(files),30):
            check_cancelled()
            batch=files[offset:offset+30]
            identifiers=[file_id(folder_path,file) for file in batch]
            prompt=SYSTEM_FOLDER_PARSE.replace('{tmdb_structure}',tmdb_structure or '未提供；不能确定时返回 unknown，不要补 E01')
            prompt+='\n只使用本批 files 的原样标识作键，不返回绝对路径。无可靠季/集号的文件不要虚构字段。'
            messages=[{'role':'system','content':prompt}, {'role':'user','content':json.dumps(
                {'folder':folder_path.name,'files':identifiers},ensure_ascii=False)}]
            raw=_parse_ai_json_response(call_ai_api_with_messages(messages,config.get('ai_parser',{}),log_func),log_func)
            result=normalize_folder(raw,folder_path,batch)
            if result:
                combined['folder_title']=combined['folder_title'] or result['folder_title']
                combined['files'].update(result['files'])
        if not combined['files']:return {}
        combined['unparsed_files']=sorted({file_id(folder_path,file) for file in files}-combined['files'].keys())
        return combined
    except ValueError:
        if log_func:log_func('AI 文件标识不属于输入批次，拒绝使用',LOG_WARNING)
        return {}


@with_recognition_budget
def parse_filename_with_ai(
    file_path: Path,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None,
    anitopy_hint: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    ai_cfg = config.get("ai_parser", {})
    filename = file_path.name
    parent_dir = file_path.parent.name
    grandparent_dir = ""
    if file_path.parent.parent != file_path.parent:
        grandparent_dir = file_path.parent.parent.name
    full_path = str(file_path)

    hint_text = ""
    if anitopy_hint:
        cleaned = anitopy_hint.get("_cleaned_filename", "")
        title = anitopy_hint.get("title", "")
        year = anitopy_hint.get("year", "")
        season = anitopy_hint.get("season")
        episode = anitopy_hint.get("episode")
        parent = anitopy_hint.get("_parent_dir", "")

        parts = []
        if cleaned and cleaned != filename:
            parts.append(f"anitopy 清洗后文件名: {cleaned}")
        if title:
            parts.append(f"anitopy 提取标题: {title}")
        if year:
            parts.append(f"anitopy 提取年份: {year}")
        if season and episode:
            parts.append(f"anitopy 提取季/集: S{season:02d}E{episode:02d}")
        if parent and parent != parent_dir:
            parts.append(f"文件父目录: {parent}")

        if parts:
            hint_text = "\n\n【参考信息 - anitopy 部分解析结果】\n" + "\n".join(parts)
            hint_text += "\n请基于以上信息修正并补充完整元数据。"

    dir_context = f"所在目录：{parent_dir}"
    if grandparent_dir:
        dir_context += f"\n祖父目录：{grandparent_dir}"

    user_prompt = f"""文件完整路径：{full_path}
文件名：{filename}
{dir_context}{hint_text}"""

    messages = [
        {"role": "system", "content": SYSTEM_FILE_PARSE},
        {"role": "user", "content": user_prompt}
    ]

    if log_func:
        log_func(f"🤖 AI 单文件解析: {filename}", LOG_INFO)

    resp = call_ai_api_with_messages(messages, ai_cfg, log_func)
    if not resp:
        return {"media_type": "unknown", "_ai_error": "AI 无响应"}

    data = _parse_ai_json_response(resp, log_func)
    if not data:
        if log_func:
            log_func(f"❌ AI 响应无法解析为 JSON", LOG_ERROR)
        return {"media_type": "unknown", "_ai_error": "JSON 解析失败"}

    result=normalize_media(data)
    if not result:
        note_error(ValueError('AI 元数据类型/标题/季集号无效'))
        return {'media_type':'unknown','_ai_error':'元数据类型/标题/季集号无效'}
    result['_from_ai']=True
    return result


def parse_long_running_series(
    folder_path: Path,
    all_files: List[Path],
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> Dict[str, Any]:
    # Explicit bounded batches replace unsafe extrapolation from a handful of names.
    return parse_folder_with_ai(folder_path,all_files,config,log_func)


def enhance_plot(
    title: str,
    original_plot: str,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
) -> str:
    if not original_plot or original_plot == "暂无简介":
        return original_plot

    ai_cfg = config.get("ai_plot_enhance", {})
    if not ai_cfg.get("enabled"):
        return original_plot

    if log_func:
        log_func(f"🤖 AI 改写简介: {title}", LOG_INFO)

    prompt_template = ai_cfg.get(
        "prompt_template",
        "你是一个专业的影视剧文案。请将以下剧情简介改写得更加生动、吸引人，语言流畅自然，可以适当增加一些悬念和感染力。请直接输出改写后的简介，不要添加额外说明。\n\n原标题：{title}\n原简介：{original_plot}\n\n优化后简介："
    )
    prompt = prompt_template.format(title=title, original_plot=original_plot)

    enhanced = call_ai_api(prompt, ai_cfg, log_func)
    return enhanced if enhanced else original_plot
