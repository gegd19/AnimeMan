#!/usr/bin/env python3
from core.parser_anitopy import parse_with_anitopy

test_files = [
    "Toaru Majutsu no Index III [21].mkv",
    "Sword Art Online II [05].mp4",
    "Fate/Zero IV [13].mkv",
]

for f in test_files:
    res = parse_with_anitopy(f)
    print(f"{f:40} -> S{res['season']:02d}E{res['episode']:02d}")
