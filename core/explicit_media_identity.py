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
    if tv==movie:
        return None
    return 'tv' if tv else 'movie'
