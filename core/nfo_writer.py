#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NFO 文件生成器
生成符合 Emby/Jellyfin 规范的 movie.nfo, tvshow.nfo, season.nfo, episode.nfo
- 代理支持：图片下载时传递 proxy 参数
"""

from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from xml.sax.saxutils import escape as _xml_escape
from typing import Optional, Callable, Dict, Any

from . import ai_client

LOG_INFO = "info"
LOG_SUCCESS = "success"


def _xml_escape_str(s: Optional[str]) -> str:
    if s is None:
        return ""
    return _xml_escape(str(s))


def _prettify(elem: Element) -> str:
    rough = tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ")


def write_movie_nfo(
    movie_dir: Path,
    title: str,
    tmdb_id: int,
    overview: str,
    year: str,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
):
    """写入电影 NFO"""
    movie_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = movie_dir / "movie.nfo"
    if nfo_path.exists():
        return

    # AI 润色
    if config.get("ai_plot_enhance", {}).get("enabled"):
        overview = ai_client.enhance_plot(title, overview, config, log_func)

    root = Element("movie")
    SubElement(root, "title").text = _xml_escape_str(title)
    SubElement(root, "plot").text = _xml_escape_str(overview)
    if year and year != "0000":
        SubElement(root, "year").text = _xml_escape_str(str(year))
    SubElement(root, "uniqueid", type="tmdb", default="true").text = str(tmdb_id)

    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(_prettify(root))

    if log_func:
        log_func(0, 0, f"📄 写入 movie.nfo", LOG_INFO)


def write_tvshow_nfo(
    show_dir: Path,
    title: str,
    tmdb_id: int,
    overview: str,
    year: str,
    num_seasons: int,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
):
    """写入电视剧 NFO"""
    show_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = show_dir / "tvshow.nfo"
    if nfo_path.exists():
        return

    if config.get("ai_plot_enhance", {}).get("enabled"):
        overview = ai_client.enhance_plot(title, overview, config, log_func)

    root = Element("tvshow")
    SubElement(root, "title").text = _xml_escape_str(title)
    SubElement(root, "plot").text = _xml_escape_str(overview)
    if year and year != "0000":
        SubElement(root, "premiered").text = f"{year}-01-01"
    SubElement(root, "uniqueid", type="tmdb", default="true").text = str(tmdb_id)
    SubElement(root, "numseasons").text = str(num_seasons)

    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(_prettify(root))

    if log_func:
        log_func(0, 0, f"📄 写入 tvshow.nfo", LOG_INFO)


def write_season_nfo(
    season_dir: Path,
    season_num: int,
    tv_id: int,
    log_func: Optional[Callable] = None
):
    """写入季 NFO"""
    season_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = season_dir / "season.nfo"
    if nfo_path.exists():
        return

    root = Element("season")
    SubElement(root, "seasonnumber").text = str(season_num)
    SubElement(root, "uniqueid", type="tmdb", default="true").text = f"{tv_id}/{season_num}"

    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(_prettify(root))

    if log_func:
        log_func(0, 0, f"📄 写入 season.nfo (S{season_num:02d})", LOG_INFO)


def write_episode_nfo(
    ep_dir: Path,
    ep_data: Dict[str, Any],
    show_title: str,
    season: int,
    ep_num: int,
    tv_id: int,
    config: Dict[str, Any],
    log_func: Optional[Callable] = None
):
    """写入单集 NFO"""
    import re
    ep_dir.mkdir(parents=True, exist_ok=True)

    ep_name = ep_data.get("name") or f"Episode {ep_num}"
    safe_title = re.sub(r'[\\/*?:"<>|]', '_', show_title)
    safe_ep_name = re.sub(r'[\\/*?:"<>|]', '_', ep_name)
    nfo_path = ep_dir / f"{safe_title} - S{season:02d}E{ep_num:02d} - {safe_ep_name}.nfo"
    if nfo_path.exists():
        return

    plot = ep_data.get("overview", "")
    if config.get("ai_plot_enhance", {}).get("enabled"):
        plot = ai_client.enhance_plot(ep_name, plot, config, log_func)

    root = Element("episodedetails")
    SubElement(root, "title").text = _xml_escape_str(ep_name)
    SubElement(root, "plot").text = _xml_escape_str(plot)
    SubElement(root, "aired").text = _xml_escape_str(ep_data.get("air_date", ""))
    SubElement(root, "season").text = str(season)
    SubElement(root, "episode").text = str(ep_num)
    SubElement(root, "rating").text = str(ep_data.get("vote_average", "0"))
    SubElement(root, "uniqueid", type="tmdb", default="true").text = f"{tv_id}/{season}/{ep_num}"

    with open(nfo_path, 'w', encoding='utf-8') as f:
        f.write(_prettify(root))

    if log_func:
        log_func(0, 0, f"📄 写入 episode.nfo: S{season:02d}E{ep_num:02d}", LOG_INFO)
