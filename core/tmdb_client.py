#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMDB API 客户端封装（完整代理支持）
所有网络请求均支持可选的 HTTP/SOCKS5 代理，且不受系统环境变量代理干扰。
"""

import time
import threading
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logger import get_logger

logger = get_logger(__name__)

LOG_INFO = "info"
LOG_SUCCESS = "success"
LOG_ERROR = "error"
LOG_WARNING = "warning"


class RateLimiter:
    """TMDB 请求速率限制器"""
    def __init__(self, min_interval: float = 0.05):
        self.min_interval = min_interval
        self.last_request = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_request = time.time()


_tmdb_limiter = RateLimiter()


def create_session(proxy: Optional[str] = None) -> requests.Session:
    """
    创建带重试机制的 requests Session，支持代理。
    代理格式: http://127.0.0.1:7890 或 socks5://127.0.0.1:1080
    关键设置: trust_env=False 强制忽略系统环境变量代理。
    """
    print(f"[TMDB SESSION] 传入代理参数: {proxy}")

    session = requests.Session()
    session.trust_env = False  # 禁用环境变量代理，完全由代码控制

    if proxy:
        # 如果用户只填了 IP:端口，自动补全 http://
        if not proxy.startswith(('http://', 'https://', 'socks5://')):
            proxy = 'http://' + proxy
        session.proxies = {"http": proxy, "https": proxy}
        print(f"[TMDB SESSION] 已设置代理: {session.proxies}")
    else:
        print("[TMDB SESSION] 未设置代理，将直连 TMDB")

    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[500, 502, 503, 504, 429],
        raise_on_status=False
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    session.mount('http://', HTTPAdapter(max_retries=retries))
    return session


def search_tmdb(
    media_type: str,
    query: str,
    year: Optional[str],
    api_key: str,
    language: str = "zh-CN",
    log_func: Optional[Callable] = None,
    alt_titles: Optional[List[str]] = None,
    proxy: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    搜索 TMDB 电影或剧集（返回单个最佳匹配）
    """
    _tmdb_limiter.wait()
    url = f"https://api.themoviedb.org/3/search/{media_type}"

    search_terms = []
    if query:
        import re
        clean = re.sub(r'[！!？?\-—:;，。、~@#$%^&*()_+={}\[\]|\\:;"\'<>,./]', '', query)
        search_terms.append(query)
        if clean != query:
            search_terms.append(clean)
    if alt_titles:
        for alt in alt_titles:
            if alt and alt != query:
                search_terms.append(alt)

    seen = set()
    unique_terms = []
    for term in search_terms:
        if term and term not in seen and len(term) > 1:
            seen.add(term)
            unique_terms.append(term)

    session = create_session(proxy)

    def _do_search(q: str, y: Optional[str], lang: str = language) -> Optional[Dict]:
        params = {
            "api_key": api_key,
            "query": q,
            "language": lang
        }
        if y and y != "null" and y != "None":
            if media_type == "movie":
                params["primary_release_year"] = y
            else:
                params["first_air_date_year"] = y

        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                if log_func:
                    log_func("⚠️ TMDB 速率限制，等待 2 秒后重试", LOG_WARNING)
                time.sleep(2)
                resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if results:
                return results[0]
        except Exception as e:
            logger.warning(f"TMDB 请求失败: {e}")
            if log_func:
                log_func(f"⚠️ TMDB 请求失败: {e}", LOG_WARNING)
        return None

    years_to_try = [year] if year and year != "null" else [None]

    for term in unique_terms:
        for y in years_to_try:
            result = _do_search(term, y)
            if result:
                return result
        if None not in years_to_try:
            result = _do_search(term, None)
            if result:
                return result

    # 英文回退：尝试前3个备选标题
    if language != "en":
        for term in unique_terms[:3]:
            result = _do_search(term, None, lang="en")
            if result:
                if log_func:
                    log_func(f"🌐 TMDB 英文搜索成功: {result.get('title') or result.get('name')}", LOG_SUCCESS)
                return result

    if log_func:
        log_func(f"❌ TMDB 搜索无结果: {query}", LOG_ERROR)
    return None


def search_tmdb_multi(
    media_type: str,
    query: str,
    year: Optional[str],
    api_key: str,
    language: str = "zh-CN",
    log_func: Optional[Callable] = None,
    proxy: Optional[str] = None
) -> List[Dict[str, Any]]:
    """搜索 TMDB 并返回完整的结果列表（用于前端选择）"""
    _tmdb_limiter.wait()
    url = f"https://api.themoviedb.org/3/search/{media_type}"
    params = {
        "api_key": api_key,
        "query": query,
        "language": language
    }
    if year and year != "null" and year != "None":
        if media_type == "movie":
            params["primary_release_year"] = year
        else:
            params["first_air_date_year"] = year

    session = create_session(proxy)
    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(2)
            resp = session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        if log_func:
            log_func(f"⚠️ TMDB 多结果搜索失败: {e}", LOG_WARNING)
        return []


def get_tmdb_details(
    media_type: str,
    tmdb_id: int,
    api_key: str,
    language: str = "zh-CN",
    log_func: Optional[Callable] = None,
    include_alternative_titles: bool = True,
    proxy: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """获取 TMDB 电影或剧集详情，可附带备选标题"""
    _tmdb_limiter.wait()
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}"
    params = {
        "api_key": api_key,
        "language": language
    }
    if include_alternative_titles:
        params["append_to_response"] = "alternative_titles"

    session = create_session(proxy)
    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(2)
            resp = session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if log_func:
            log_func(f"❌ 获取 TMDB 详情失败: {e}", LOG_ERROR)
        return None


def get_tv_season_episodes(
    tv_id: int,
    season_num: int,
    api_key: str,
    language: str = "zh-CN",
    log_func: Optional[Callable] = None,
    proxy: Optional[str] = None
) -> List[Dict[str, Any]]:
    """获取剧集指定季的集列表"""
    _tmdb_limiter.wait()
    url = f"https://api.themoviedb.org/3/tv/{tv_id}/season/{season_num}"
    params = {"api_key": api_key, "language": language}
    session = create_session(proxy)
    try:
        resp = session.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            time.sleep(2)
            resp = session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        episodes = data.get("episodes", [])
        if season_num == 0 and not episodes:
            if log_func:
                log_func(f"⚠️ TMDB 特辑列表为空，使用占位集", LOG_WARNING)
            episodes = [{
                "episode_number": 1, "name": "特辑", "overview": "",
                "air_date": "", "still_path": None
            }]
        return episodes
    except Exception as e:
        if log_func:
            log_func(f"❌ 获取季 {season_num} 信息失败: {e}", LOG_ERROR)
        if season_num == 0:
            return [{"episode_number": 1, "name": "特辑", "overview": "", "air_date": "", "still_path": None}]
        return []


def build_image_url(base_url: str, path: str, size: str = "original") -> str:
    if not path:
        return ""
    if not base_url.endswith('/'):
        base_url += '/'
    if path.startswith('/'):
        path = path[1:]
    return f"{base_url}{size}/{path}"


def download_image(
    url: str,
    save_path: Path,
    log_func: Optional[Callable] = None,
    proxy: Optional[str] = None
) -> bool:
    """下载图片，支持代理"""
    if save_path.exists():
        return True
    save_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        session = create_session(proxy)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(resp.content)
        if log_func:
            log_func(f"✅ 图片下载完成: {save_path.name}", LOG_SUCCESS)
        return True
    except Exception as e:
        if log_func:
            log_func(f"❌ 图片下载失败 ({url}): {e}", LOG_ERROR)
        return False


def extract_all_titles(details: Dict[str, Any]) -> List[str]:
    """从详情字典中提取所有可能的标题（用于相似度匹配）"""
    titles = []
    if details.get("title"):
        titles.append(details["title"])
    if details.get("name"):
        titles.append(details["name"])
    if details.get("original_title"):
        titles.append(details["original_title"])
    if details.get("original_name"):
        titles.append(details["original_name"])
    alt_titles = details.get("alternative_titles", {})
    if isinstance(alt_titles, dict):
        results = alt_titles.get("results", [])
    else:
        results = alt_titles.get("titles", [])
    for item in results:
        t = item.get("title") or item.get("name")
        if t:
            titles.append(t)
    return list(set(titles))
