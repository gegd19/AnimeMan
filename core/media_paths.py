"""One episode filename for automatic/manual organization and NFO sidecars."""
from pathlib import Path
from .processor_utils import sanitize_filename
from .path_safety import UnsafePathError


def episode_stem(title, year, season, episode, episode_title, config):
    folder = sanitize_filename(title)
    if config.get('add_year_to_folder') and year:
        folder += f' ({year})'
    stem = f'{folder} - S{season:02d}E{episode:02d}'
    if episode_title:
        stem += ' - ' + sanitize_filename(episode_title)
    return folder, stem


def episode_video_path(src, config, title, year, season, episode, episode_title):
    folder, stem = episode_stem(title, year, season, episode, episode_title, config)
    return Path(config['tv_target_folder']) / folder / f'Season {season:02d}' / (stem + Path(src).suffix)


def episode_nfo_path(video_path):
    video_path = Path(video_path)
    if video_path.suffix.lower() == '.nfo':
        raise UnsafePathError(f'视频与 NFO 路径冲突，拒绝覆盖：{video_path}')
    return video_path.with_suffix('.nfo')
