#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Emby/Jellyfin NFO writers: raw XML text and validated atomic publication."""
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom
from typing import Optional, Callable, Dict, Any

from . import ai_client
from .cancellation import check_cancelled
from .execution_mode import execution_scope, skip_preview_write
from .metadata_io import is_valid_nfo, write_metadata
from .json_store import path_lock
from .media_paths import episode_nfo_path, episode_stem
from .path_safety import absolute_link_path, UnsafePathError

LOG_INFO = 'info'
LOG_SUCCESS = 'success'


def _text(value):
    return '' if value is None else str(value)


def _prettify(elem):
    return minidom.parseString(tostring(elem, 'utf-8')).toprettyxml(indent='  ')


def _publish(path, root, log_func):
    changed = write_metadata(path, _prettify(root).encode('utf-8'), lambda p: is_valid_nfo(p, root.tag))
    if changed and log_func:
        log_func(0, 0, f'📄 写入 {path.name}', LOG_INFO)
    return changed


@execution_scope
@skip_preview_write
def write_movie_nfo(movie_dir: Path, title: str, tmdb_id: int, overview: str, year: str,
                    config: Dict[str, Any], log_func: Optional[Callable] = None):
    path = Path(movie_dir) / 'movie.nfo'
    with path_lock(path):
        check_cancelled()
        if is_valid_nfo(path, 'movie'):
            return False
        if config.get('ai_plot_enhance', {}).get('enabled'):
            overview = ai_client.enhance_plot(title, overview, config, log_func)
        root = Element('movie')
        SubElement(root, 'title').text = _text(title)
        SubElement(root, 'plot').text = _text(overview)
        if year and year != '0000':
            SubElement(root, 'year').text = _text(year)
        SubElement(root, 'uniqueid', type='tmdb', default='true').text = str(tmdb_id)
        return _publish(path, root, log_func)


@execution_scope
@skip_preview_write
def write_tvshow_nfo(show_dir: Path, title: str, tmdb_id: int, overview: str, year: str,
                     num_seasons: int, config: Dict[str, Any], log_func: Optional[Callable] = None):
    path = Path(show_dir) / 'tvshow.nfo'
    with path_lock(path):
        check_cancelled()
        if is_valid_nfo(path, 'tvshow'):
            return False
        if config.get('ai_plot_enhance', {}).get('enabled'):
            overview = ai_client.enhance_plot(title, overview, config, log_func)
        root = Element('tvshow')
        SubElement(root, 'title').text = _text(title)
        SubElement(root, 'plot').text = _text(overview)
        if year and year != '0000':
            SubElement(root, 'premiered').text = f'{year}-01-01'
        SubElement(root, 'uniqueid', type='tmdb', default='true').text = str(tmdb_id)
        SubElement(root, 'numseasons').text = str(num_seasons)
        return _publish(path, root, log_func)


@skip_preview_write
def write_season_nfo(season_dir: Path, season_num: int, tv_id: int, log_func: Optional[Callable] = None):
    path = Path(season_dir) / 'season.nfo'
    with path_lock(path):
        check_cancelled()
        if is_valid_nfo(path, 'season'):
            return False
        root = Element('season')
        SubElement(root, 'seasonnumber').text = str(season_num)
        SubElement(root, 'uniqueid', type='tmdb', default='true').text = f'{tv_id}/{season_num}'
        return _publish(path, root, log_func)


@execution_scope
@skip_preview_write
def write_episode_nfo(ep_dir: Path, ep_data: Dict[str, Any], show_title: str, season: int,
                      ep_num: int, tv_id: int, config: Dict[str, Any],
                      log_func: Optional[Callable] = None, *, video_path=None):
    """New callers supply the actual video path; old directory-only calls remain supported."""
    ep_dir = Path(ep_dir)
    if video_path is None:
        _, stem = episode_stem(show_title, '', season, ep_num, ep_data.get('name'), config)
        video_path = ep_dir / (stem + '.mkv')
    if absolute_link_path(video_path).parent != ep_dir.resolve():
        raise UnsafePathError('单集视频与 NFO 目录不一致')
    path = episode_nfo_path(video_path)
    with path_lock(path):
        check_cancelled()
        if is_valid_nfo(path, 'episodedetails'):
            return False
        ep_name = ep_data.get('name') or f'Episode {ep_num}'
        plot = ep_data.get('overview', '')
        if config.get('ai_plot_enhance', {}).get('enabled'):
            plot = ai_client.enhance_plot(ep_name, plot, config, log_func)
        root = Element('episodedetails')
        SubElement(root, 'title').text = _text(ep_name)
        SubElement(root, 'plot').text = _text(plot)
        SubElement(root, 'aired').text = _text(ep_data.get('air_date', ''))
        SubElement(root, 'season').text = str(season)
        SubElement(root, 'episode').text = str(ep_num)
        SubElement(root, 'rating').text = _text(ep_data.get('vote_average', '0'))
        SubElement(root, 'uniqueid', type='tmdb', default='true').text = f'{tv_id}/{season}/{ep_num}'
        return _publish(path, root, log_func)
