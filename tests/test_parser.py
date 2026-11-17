"""Turn the former print-only examples into regression assertions."""

import pytest
from core.parser_anitopy import parse_with_anitopy


@pytest.mark.parametrize("filename,roman,episode", [
    ("Toaru Majutsu no Index III [21].mkv", "III", 21),
    ("Sword Art Online II [05].mp4", "II", 5),
    ("Fate/Zero IV [13].mkv", "IV", 13),
])
def test_roman_title_without_explicit_season_needs_confirmation(filename, roman, episode):
    result = parse_with_anitopy(filename)
    assert result["media_type"] == "tv"
    assert result["season"] is None and result["episode"] == episode
    assert result["reason_code"] == "ambiguous_roman_season"
    assert result["title"].endswith(roman)
