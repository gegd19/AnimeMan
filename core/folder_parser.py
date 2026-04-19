#!/ New module: core/folder_parser.py
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from . import ai_client, cache_manager
from .cache_manager import ai_parse_cache_lock

FOLDER_CACHE_FILE = "folder_ai_cache.json"

def load_folder_cache() -> Dict[str, Any]:
    path = Path(FOLDER_CACHE_FILE)
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_folder_cache(cache: Dict[str, Any]):
    with ai_parse_cache_lock:
        temp = FOLDER_CACHE_FILE + ".tmp"
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        Path(temp).replace(FOLDER_CACHE_FILE)

def parse_folder_with_ai(folder_path: Path, config: Dict[str, Any], log_func: Optional[Callable]=None) -> Optional[Dict[str, Any]]:
    """使用AI批量分析文件夹，返回标准化元数据（用于文件夹内所有视频）"""
    ai_cfg = config.get("ai_parser", {})
    if not ai_cfg.get("enabled"):
        return None

    # 收集文件夹内视频文件列表
    video_exts = [e.lower() for e in config["video_extensions"]]
    video_files = []
    for f in folder_path.iterdir():
        if f.is_file() and f.suffix.lower() in video_exts:
            video_files.append(f.name)
    if not video_files:
        return None

    prompt = f"""分析以下文件夹及内部视频文件，提取准确的媒体元数据。
文件夹路径: {folder_path}
文件夹名称: {folder_path.name}
包含视频文件: {', '.join(video_files[:10])}{'...' if len(video_files)>10 else ''}

请综合文件夹名和所有视频文件名，推断出：
- media_type: "movie" 或 "tv"
- title: 系列主标题
- search_title: 用于TMDB搜索的标准化标题
- year: 发行年份(可能为null)
- season: 季号(整数，特辑为0)
- episode_count: 视频文件数量
- episode_start: 起始集号(推测第一个视频的集号，若无法确定则为1)
- is_total_episode_numbering: 布尔值，文件名中的集号是否为从第一季开始累计的总集数(例如第二季文件夹内文件名为第26集)
- alternative_titles: 别名列表
- notes: 任何有助于匹配的额外信息

返回严格JSON格式，不要额外解释。"""
    if log_func:
        log_func(f"🤖 AI 批量分析文件夹: {folder_path.name}", LOG_INFO)
    resp = ai_client.call_ai_api(prompt, ai_cfg, log_func)
    if not resp:
        return None
    try:
        start = resp.find('{')
        end = resp.rfind('}')
        json_str = resp[start:end+1] if start!=-1 else resp
        data = json.loads(json_str)
        data['_timestamp'] = time.time()
        data['_folder'] = str(folder_path)
        return data
    except:
        return None

def get_folder_meta(folder_path: Path, config: Dict, log_func=None) -> Optional[Dict]:
    """获取文件夹元数据（优先缓存，否则调用AI并缓存）"""
    cache = load_folder_cache()
    key = str(folder_path.resolve())
    if key in cache:
        return cache[key]
    if config.get("ai_parser", {}).get("enabled"):
        meta = parse_folder_with_ai(folder_path, config, log_func)
        if meta:
            cache[key] = meta
            save_folder_cache(cache)
            return meta
    return None
