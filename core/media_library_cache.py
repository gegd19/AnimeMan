"""Media-library JSON storage and its authoritative versioned projection."""
from .json_store import read_json, write_json
from .execution_mode import skip_preview_write
from .runtime_paths import cache_file
from . import derived_cache

MEDIA_LIBRARY_CACHE_FILE = 'media_library_cache.json'


def generate_media_library_cache(config=None):
    return derived_cache.generate_library(config)


@skip_preview_write
def save_media_library_cache(cache_data):
    write_json(cache_file(MEDIA_LIBRARY_CACHE_FILE), cache_data)


def load_media_library_cache():
    return read_json(cache_file(MEDIA_LIBRARY_CACHE_FILE))


def update_media_library_cache(config=None):
    return derived_cache.get('library', config, force=True)


def get_media_library_cache(config=None):
    return derived_cache.get('library', config)
