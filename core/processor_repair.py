#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair metadata beside cached library videos; never infer a replacement video path."""
from pathlib import Path

from . import tmdb_client, nfo_writer
from .cancellation import check_cancelled
from .execution_mode import execution_scope, is_preview
from .json_store import CacheCorruptionError
from .media_paths import episode_nfo_path
from .metadata_io import is_valid_nfo, is_valid_image
from .path_safety import UnsafePathError, validate_cached_target, validate_target_path
from .processor_utils import wrap_progress_callback


@execution_scope
def repair_missing_metadata(config, cache_dict, log_func=None):
    log = wrap_progress_callback(log_func)
    summary = {'repaired':0, 'planned':0, 'skipped':0, 'failed':0, 'errors':[]}
    groups = {}
    handled = set()
    episode_lists = {}
    details_cache = {}

    def report(path, message):
        summary['failed'] += 1
        summary['errors'].append({'path':str(path), 'message':message})
        if log:
            log(f'❌ 修复未完成 {path}: {message}', 'error')

    def guard(src, video, path, media_type):
        path = validate_target_path(src, path, config, media_type)
        if path.exists():
            for original in (src, video):
                if original.exists() and path.samefile(original):
                    raise UnsafePathError(f'元数据与源文件/视频为同一文件，拒绝替换：{path}')
        return path

    def apply(src, video, path, kind, validator, writer):
        check_cancelled()
        try:
            path = guard(src, video, path, kind)
            if path in handled:
                return
            handled.add(path)
            if validator(path):
                summary['skipped'] += 1
            elif is_preview(config):
                summary['planned'] += 1
                if log:
                    log(f'🔍 [模拟修复] 补全: {path}', 'info')
            elif writer():
                summary['repaired'] += 1
            elif validator(path):
                summary['skipped'] += 1
            else:
                report(path, '写入/下载未成功，原文件保留')
        except CacheCorruptionError:
            raise
        except (OSError, ValueError) as exc:
            report(path, str(exc))

    # Validate all cached video boundaries before sending any metadata request.
    for source, entry in cache_dict.items():
        check_cancelled()
        if not isinstance(entry, dict) or entry.get('media_type') not in {'movie','tv'} or not entry.get('tmdb_id'):
            summary['skipped'] += 1
            continue
        src = Path(source)
        try:
            video = validate_cached_target(src, entry, config)
            if not video.is_file():
                summary['skipped'] += 1
                continue
            kind = entry['media_type']
            directory = video.parent if kind == 'movie' else video.parent.parent
            primary = directory / ('movie.nfo' if kind == 'movie' else 'tvshow.nfo')
            guard(src, video, primary, kind)
            groups.setdefault((kind, entry['tmdb_id'], directory), []).append((src, video, entry))
        except (OSError, ValueError) as exc:
            report(source, str(exc))

    api_key = config['tmdb_api']['api_key']
    language = config['tmdb_api'].get('language', 'zh-CN')
    proxy = config['tmdb_api'].get('proxy')
    base_url = config['image_base_url']
    for (kind, tmdb_id, directory), items in groups.items():
        check_cancelled()
        src, video, entry = items[0]
        key = (kind, tmdb_id)
        if key not in details_cache:
            details_cache[key] = tmdb_client.get_tmdb_details(kind, tmdb_id, api_key, language,
                log_func=log, include_alternative_titles=True, proxy=proxy)
        details = details_cache[key]
        if not details:
            report(directory, 'TMDB 详情不可用，未猜测元数据')
            continue
        title = entry.get('title') or details.get('title' if kind == 'movie' else 'name') or ''
        year = entry.get('year') or (details.get('release_date' if kind == 'movie' else 'first_air_date') or '')[:4]
        if kind == 'movie':
            apply(src, video, directory/'movie.nfo', kind, lambda p:is_valid_nfo(p,'movie'),
                  lambda:nfo_writer.write_movie_nfo(directory,title,tmdb_id,details.get('overview',''),year,config,log))
        else:
            seasons = [season for season in details.get('seasons',[]) if season.get('season_number',0)>0]
            apply(src, video, directory/'tvshow.nfo', kind, lambda p:is_valid_nfo(p,'tvshow'),
                  lambda:nfo_writer.write_tvshow_nfo(directory,title,tmdb_id,details.get('overview',''),year,len(seasons),config,log))
        if config.get('download_images'):
            for field, name in [('poster_path','poster.jpg'),('backdrop_path','fanart.jpg')]:
                if details.get(field):
                    apply(src, video, directory/name, kind, is_valid_image,
                          lambda:tmdb_client.download_image(tmdb_client.build_image_url(base_url,details[field]),
                                                          directory/name,log,proxy=proxy))
        if kind != 'tv':
            continue
        for src, video, entry in items:
            check_cancelled()
            season, episode = entry.get('season'), entry.get('episode')
            if type(season) is not int or season < 0 or type(episode) is not int or episode < 1:
                report(video, '缓存缺少有效季/集号，未推断 S01E01')
                continue
            apply(src, video, video.parent/'season.nfo', kind, lambda p:is_valid_nfo(p,'season'),
                  lambda:nfo_writer.write_season_nfo(video.parent,season,tmdb_id,log))
            season_key = (tmdb_id, season)
            if season_key not in episode_lists:
                episode_lists[season_key] = tmdb_client.get_tv_season_episodes(tmdb_id,season,api_key,language,log,proxy=proxy)
            data = next((ep for ep in episode_lists[season_key] if ep.get('episode_number') == episode), None)
            if data is None:
                report(video, f'TMDB 缺少 S{season:02d}E{episode:02d}，未创建占位 NFO')
                continue
            try:
                path = episode_nfo_path(video)
            except UnsafePathError as exc:
                report(video, str(exc))
                continue
            apply(src, video, path, kind, lambda p:is_valid_nfo(p,'episodedetails'),
                  lambda:nfo_writer.write_episode_nfo(video.parent,data,title,season,episode,tmdb_id,config,log,video_path=video))
    if log:
        log(f'修复结束：写入 {summary["repaired"]}，计划 {summary["planned"]}，失败 {summary["failed"]}',
            'warning' if summary['failed'] else 'info')
    return summary
