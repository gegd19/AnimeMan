"""Preserve Roman numerals that are part of the title, not season markers."""
import pytest


@pytest.mark.parametrize('filename,roman,episode',[
    ('星光 II S01E01.mkv','II',1),
    ('Project X S01E02.mkv','X',2),
    ('Alpha IV S01E03.mkv','IV',3),
])
def test_explicit_season_does_not_rewrite_title_numerals(filename,roman,episode):
    from core.parser_anitopy import parse_with_anitopy
    result=parse_with_anitopy(filename)
    assert roman in result['_cleaned_filename'].split()
    assert roman in result['title'].split()
    assert (result['season'],result['episode'])==(1,episode)


def test_fixed_sequel_case_selects_correct_identity_without_unsafe_passes():
    from tools.evaluate_recognition import evaluate,FIXTURES
    report=evaluate(FIXTURES.read_bytes())
    sequel=next(item for item in report['cases'] if item['case_id']=='C48')
    assert sequel['actual']==sequel['expected']
    assert report['metrics']['review_expected_but_auto']==0


def test_parser_policy_version_invalidates_old_cached_results(monkeypatch):
    from core import parse_identity
    old=parse_identity.policy_key({})
    monkeypatch.setattr(parse_identity,'ROMAN_TITLE_POLICY','future-test-version')
    assert parse_identity.policy_key({})!=old


def test_only_sequel_case_changes_in_fixed_b00_suite():
    import json
    from tools.evaluate_recognition import evaluate,FIXTURES
    from pathlib import Path
    before=json.loads((Path(__file__).resolve().parents[1]/'reports/recognition-r10-results.json').read_text())
    original={row['case_id']:row['scenarios']['ai_off_cold']['actual'] for row in before['cases']}
    after=evaluate(FIXTURES.read_bytes())
    for row in after['cases']:
        if row['case_id']=='C48':
            assert row['actual']==row['expected']
        else:
            assert row['actual']==original[row['case_id']],row['case_id']
