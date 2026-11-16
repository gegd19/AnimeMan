"""TMDB IDs are namespaced by media type; never invent an ID for unknown media."""
import re


def media_identity(media_type, tmdb_id):
    if media_type not in ('movie', 'tv'):
        return None
    if isinstance(tmdb_id, str) and re.fullmatch(r'[0-9]{1,10}', tmdb_id):
        tmdb_id = int(tmdb_id)
    if type(tmdb_id) is not int or not 1 <= tmdb_id <= 2147483647:
        return None
    return media_type, tmdb_id


def identity_key(identity):
    return f'{identity[0]}:{identity[1]}'


def poster_url(identity):
    return f'/media_poster/{identity[0]}/{identity[1]}' if identity else None
