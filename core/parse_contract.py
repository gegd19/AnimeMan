"""Untrusted AI data becomes a small, typed metadata object or no result."""
from copy import deepcopy
from pathlib import Path, PurePosixPath
import re


def _integer(value, minimum=0, maximum=9999):
    if isinstance(value,str) and re.fullmatch(r'\d+',value.strip()):
        value=int(value.strip())
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('无效整数')
    return value


def _year(value):
    if value is None or value=='':return None
    if type(value) is int:value=str(value)
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}',value) or not 1800<=int(value)<=2199:
        raise ValueError('无效年份')
    return value


def normalize_media(value, *, trusted=False):
    if not isinstance(value,dict) or value.get('media_type') not in ('tv','movie'):
        return None
    title=value.get('title')
    if not isinstance(title,str) or not title.strip('. ') or title.strip().casefold()=='unknown':return None
    try:
        result={'media_type':value['media_type'],'title':title.strip()}
        for field in ['search_title','episode_title']:
            text=value.get(field,title.strip() if field=='search_title' else '')
            if not isinstance(text,str):raise ValueError('无效文本')
            result[field]=text
        aliases=value.get('alternative_titles',[])
        if not isinstance(aliases,list) or any(not isinstance(v,str) or not v.strip() for v in aliases):raise ValueError('无效别名')
        result['alternative_titles']=[v.strip() for v in aliases]
        for field in ['year','year_guess']:result[field]=_year(value.get(field))
        for field in ['season','episode','corrected_season','corrected_episode','explicit_season','total_episode']:
            item=value.get(field)
            result[field]=None if item is None else _integer(item,0 if 'season' in field else 1,99 if 'season' in field else 9999)
        if result['media_type']=='tv' and (result['season'] is None or result['episode'] is None):return None
        if result['explicit_season'] is None:result['explicit_season']=result['season']
        if trusted:
            for key in ['_parser','_anitopy_success','_from_ai','_from_folder_cache','_from_offline_ai',
                        '_from_folder_ai_batch','_cleaned_filename','_parent_dir','release_group']:
                if key in value and type(value[key]) in (str,bool):result[key]=value[key]
        return result
    except (ValueError,TypeError):
        return None


def file_id(folder, file):
    path=Path(file).absolute()
    relative=path.relative_to(Path(folder).absolute()).as_posix()
    if relative in {'','.'} or '\\' in relative or any(part in {'..','.'} for part in PurePosixPath(relative).parts):
        raise ValueError('不可信文件标识')
    return relative


def normalize_folder(value, folder, files):
    if not isinstance(value,dict) or not isinstance(value.get('files'),dict):return {}
    allowed={file_id(folder,file) for file in files}
    if any(not isinstance(name,str) or name not in allowed for name in value['files']):return {}
    defaults={key:value[key] for key in ['media_type','season','year','alternative_titles'] if key in value}
    if 'folder_title' in value:defaults['title']=value['folder_title']
    valid={}
    for name,info in value['files'].items():
        if not isinstance(info,dict):continue
        result=normalize_media(dict(defaults,**info))
        if result:valid[name]=result
    if not valid:return {}
    return {'folder_title':value.get('folder_title') if isinstance(value.get('folder_title'),str) else '',
            'media_type':value.get('media_type') if value.get('media_type') in ('tv','movie') else 'unknown',
            'files':valid,'unparsed_files':sorted(allowed-valid.keys())}


def normalize_header(value):
    """Folder metadata may name a season, but never invent individual episodes."""
    if not isinstance(value,dict):return None
    title=value.get('title') or value.get('folder_title')
    if value.get('media_type') not in ('tv','movie') or not isinstance(title,str) or not title.strip('. '):return None
    try:
        aliases=value.get('alternative_titles',[])
        if not isinstance(aliases,list) or any(not isinstance(v,str) for v in aliases):return None
        result={'title':title.strip(),'media_type':value['media_type'],'year':_year(value.get('year')),
                'alternative_titles':deepcopy(aliases),'season':None}
        if value.get('season') is not None:result['season']=_integer(value['season'],0,99)
        for field in ['episode_start','episode_count']:
            if value.get(field) is not None:result[field]=_integer(value[field],1 if field=='episode_start' else 0)
        return result
    except (ValueError,TypeError):return None
