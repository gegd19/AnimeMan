"""Turn the former print-only examples into regression assertions."""

import pytest
from core.parser_anitopy import parse_with_anitopy


@pytest.mark.parametrize("filename,season,episode", [
    ("Toaru Majutsu no Index III [21].mkv", 3, 21),
    ("Sword Art Online II [05].mp4", 2, 5),
    ("Fate/Zero IV [13].mkv", 4, 13),
])
def test_roman_season_examples(filename, season, episode):
    result = parse_with_anitopy(filename)
    assert result["media_type"] == "tv"
    assert (result["season"], result["episode"]) == (season, episode)
