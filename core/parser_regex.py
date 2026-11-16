#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Conservative filename fallback: complete tokens, no invented first episode."""
import re
from pathlib import Path
from .parser_helpers import clean_parent_dir_name


def chinese_number(value):
    if value.isdigit():
        return int(value)
    digits = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if value in digits:
        return digits[value]
    if value.count('十') == 1:
        tens, units = value.split('十')
        if (not tens or tens in digits) and (not units or units in digits):
            return (digits[tens] if tens else 1)*10 + (digits[units] if units else 0)
    return None


def explicit_season_number(text):
    match = re.search(r'第\s*([零一二两三四五六七八九十\d]+)\s*季',text)
    if match:
        return chinese_number(match[1])
    match = re.search(r'(?<![A-Za-z0-9])(?:Season\s*|S)(\d{1,2})(?!\d)',text,re.I)
    return int(match[1]) if match else None


def parse_with_regex(filename, parent_dir=''):
    name = Path(filename).stem
    name = re.sub(r'^\[(?!\d+\])[^\]]+\]\s*','',name)
    year_match = re.search(r'\b(?:19|20)\d{2}\b',name)
    year = year_match[0] if year_match else None
    explicit = explicit_season_number(name)
    if explicit is None:
        explicit = explicit_season_number(parent_dir)
    season, episode = explicit, None
    matched = None
    for pattern in [r'(?<![A-Za-z0-9])S(\d{1,2})E(\d{1,4})(?!\d)',
                    r'(?<!\d)(\d{1,2})x(\d{1,4})(?!\d)']:
        matched = re.search(pattern,name,re.I)
        if matched:
            season,episode = int(matched[1]),int(matched[2])
            break
    if episode is None:
        matched = re.search(r'第\s*(\d{1,4})\s*[集話话](?!\d)|\[(\d{1,4})\]|(?<!\w)(?:EP?|#)\s*(\d{1,4})(?!\d)',name,re.I)
        if matched:
            episode = int(next(v for v in matched.groups() if v is not None))
            if str(episode) == year:
                episode = None
    special = re.search(r'(?<![A-Za-z0-9])(?:OVA|OAD|SP|SPECIAL)(?![A-Za-z0-9])|特典|特别篇|番外',name,re.I)
    if special:
        season = 0
        if episode is None:
            marker = re.search(r'(?:OVA|OAD|SP|SPECIAL|特典|特别篇|番外)\s*(\d{1,4})(?!\d)',name,re.I)
            if marker:
                episode = int(marker[1])
    if episode is not None and episode < 1:
        episode = None
    if episode is not None and season is None:
        season = 1
    title = name
    if matched and episode is not None:
        title = title[:matched.start()] + ' ' + title[matched.end():]
    title = re.sub(r'第\s*[零一二两三四五六七八九十\d]+\s*季|(?<!\w)(?:Season\s*|S)\d{1,2}(?!\d)',' ',title,flags=re.I)
    title = re.sub(r'\b(?:1080p|720p|2160p|4K|HDR|HEVC|x264|x265|AAC|WEB-DL|BluRay|BDRip)\b','',title,flags=re.I)
    title = re.sub(r'[\[\]()【】_,.\-]',' ',title)
    title = re.sub(r'\s+',' ',title).strip()
    if len(title)<2 or title.isdigit():
        title = clean_parent_dir_name(parent_dir) or 'Unknown'
    return {'media_type':'tv' if episode is not None else 'unknown', 'title':title,'search_title':title,
            'year':year,'season':season,'episode':episode,'episode_title':'','alternative_titles':[],
            'year_guess':None,'corrected_season':None,'corrected_episode':None,'_parser':'regex',
            'explicit_season':explicit if explicit is not None else season,'total_episode':None}
