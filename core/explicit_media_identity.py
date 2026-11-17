"""Extract explicit identity hints without leaving configured source roots."""
from pathlib import Path
import re


class IdentityEvidenceError(ValueError):
    pass


_TAG = re.compile(r'(?i)\{tmdb-([^{}]*)\}|\[tmdbid=([^\[\]]*)\]')


def source_relative_parts(src, roots):
    source=Path(src).resolve()
    eligible=[]
    for value in roots:
        root=Path(value).resolve()
        if source != root and root in source.parents:
            eligible.append(root)
    if not eligible:
        return None
    root=max(eligible,key=lambda path:len(path.parts))
    return (root.name, *source.relative_to(root).parts)


def extract_path_identity(src, roots):
    parts=source_relative_parts(src,roots)
    if parts is None:
        return None
    ids=set()
    for part in parts:
        for match in _TAG.finditer(part):
            raw=match.group(1) if match.group(1) is not None else match.group(2)
            if not re.fullmatch(r'[1-9][0-9]{0,9}',raw):
                raise IdentityEvidenceError('路径中的 TMDB ID 无效')
            ids.add(int(raw))
    if len(ids)>1:
        raise IdentityEvidenceError('路径中存在冲突的 TMDB ID')
    return next(iter(ids)) if ids else None


def explicit_media_type(src, roots):
    parts=source_relative_parts(src,roots)
    if not parts:
        return None
    stem=Path(parts[-1]).stem
    tv=bool(re.search(r'(?i)(?<![a-z0-9])s\d{1,2}e\d{1,4}(?!\d)|(?<!\d)\d{1,2}x\d{1,4}(?!\d)',stem))
    tv=tv or bool(re.search(r'第\s*[零一二两三四五六七八九十\d]+\s*季.*第\s*\d+\s*[集話话]',stem))
    movie=bool(re.search(r'(?i)\[(?:movie|film)\]|剧场版|劇場版',stem))
    parents={part.casefold() for part in parts[:-1]}
    tv=tv or bool(parents & {'tv','tv shows','series','电视剧','劇集'})
    movie=movie or bool(parents & {'movies','movie','films','电影','電影'})
    if tv and movie:
        raise IdentityEvidenceError('路径中电影与剧集类型证据冲突')
    if not tv and not movie:
        return None
    return 'tv' if tv else 'movie'


_MAX_NFO_BYTES = 1024 * 1024
_VIDEO_SUFFIXES = {'.mkv', '.mp4', '.avi', '.ts', '.m2ts', '.mov', '.wmv', '.flv'}


def _source_root(src, roots):
    source = Path(src).resolve()
    eligible = [Path(value).resolve() for value in roots
                if source != Path(value).resolve() and Path(value).resolve() in source.parents]
    return (source, max(eligible, key=lambda path: len(path.parts))) if eligible else (source, None)


def _read_nfo(path):
    import os
    import stat
    import xml.etree.ElementTree as ET
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise IdentityEvidenceError('无法读取关联 NFO') from error
    if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_NFO_BYTES:
        raise IdentityEvidenceError('关联 NFO 非普通文件或超过大小限制')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            current = os.fstat(stream.fileno())
            if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                raise IdentityEvidenceError('关联 NFO 在读取期间发生变化')
            data = stream.read(_MAX_NFO_BYTES + 1)
            after = os.fstat(stream.fileno())
            signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if signature(before) != signature(after):
                raise IdentityEvidenceError('关联 NFO 在读取期间发生变化')
    except OSError as error:
        raise IdentityEvidenceError('无法安全读取关联 NFO') from error
    if len(data) > _MAX_NFO_BYTES or b'\x00' in data:
        raise IdentityEvidenceError('关联 NFO 超限或编码不受支持')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as error:
        raise IdentityEvidenceError('关联 NFO 编码不受支持') from error
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
        raise IdentityEvidenceError('关联 NFO 含 DTD/实体声明')
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise IdentityEvidenceError('关联 NFO XML 无效') from error


def extract_nfo_identity(src, roots):
    """Read only associated NFOs; episode-level TMDB IDs remain ambiguous."""
    import os
    source, root = _source_root(src, roots)
    if root is None:
        return None
    candidates = [source.with_suffix('.nfo')]
    # A generic movie.nfo is associated only with a single regular video.
    try:
        videos = []
        with os.scandir(source.parent) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in _VIDEO_SUFFIXES:
                    videos.append(entry.name)
                    if len(videos) > 1:
                        break
    except OSError as error:
        raise IdentityEvidenceError('无法检查电影 NFO 的关联范围') from error
    if len(videos) == 1 and videos[0] == source.name:
        candidates.append(source.parent / 'movie.nfo')
    current = source.parent
    while current == root or root in current.parents:
        candidates.append(current / 'tvshow.nfo')
        if current == root:
            break
        current = current.parent
    identities = set()
    for path in dict.fromkeys(candidates):
        document = _read_nfo(path)
        if document is None:
            continue
        kind = document.tag.rsplit('}', 1)[-1].lower() if isinstance(document.tag, str) else ''
        tmdb_nodes = [node for node in document
                      if isinstance(node.tag, str) and node.tag.rsplit('}', 1)[-1].lower() == 'uniqueid'
                      and node.get('type', '').casefold() == 'tmdb']
        if not tmdb_nodes:
            continue
        if kind not in ('movie', 'tvshow'):
            raise IdentityEvidenceError('NFO 中 TMDB ID 的作用域不明，需要人工确认')
        for node in tmdb_nodes:
            raw = (node.text or '').strip()
            if not re.fullmatch(r'[1-9][0-9]{0,9}', raw):
                raise IdentityEvidenceError('NFO 中 TMDB ID 无效')
            identities.add(('movie' if kind == 'movie' else 'tv', int(raw)))
    if len(identities) > 1:
        raise IdentityEvidenceError('关联 NFO 存在冲突的 TMDB 身份')
    return next(iter(identities)) if identities else None
