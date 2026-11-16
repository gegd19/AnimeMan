"""Conservative, deterministic TMDB candidate evidence; scores are not probabilities."""
import re
import unicodedata


def _normalize(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFKC', value).casefold().strip()
    return re.sub(r'[^\w]+', '', value)


def evaluate_candidates(candidates, media_type, titles, year=None):
    queries = {_normalize(title) for title in titles if _normalize(title)}
    results = []
    for candidate in candidates:
        ident = candidate.get('id') if isinstance(candidate, dict) else None
        evidence, reason, score = [], None, 0
        if media_type not in ('tv', 'movie') or type(ident) is not int or ident <= 0:
            reason = 'invalid_identity'
        else:
            names = {candidate.get(key) for key in ('name','title','original_name','original_title') if isinstance(candidate.get(key),str)}
            normalized = {_normalize(name) for name in names if _normalize(name)}
            if not queries.intersection(normalized):
                reason = 'title_mismatch'
            else:
                score = 100
                evidence.append('exact_title')
                date = candidate.get('release_date' if media_type == 'movie' else 'first_air_date')
                candidate_year = date[:4] if isinstance(date,str) else ''
                if year and candidate_year:
                    if candidate_year == str(year):
                        score += 20
                        evidence.append('matching_year')
                    else:
                        reason = 'year_conflict'
        results.append({'id':ident, 'media_type':media_type, 'evidence':evidence,
                        'reason':reason, 'score':score, 'item':candidate})
    eligible = sorted((entry for entry in results if entry['reason'] is None), key=lambda entry: -entry['score'])
    selected = eligible[0]['item'] if eligible and (len(eligible)==1 or eligible[0]['score']-eligible[1]['score']>=10) else None
    return {'selected':selected, 'candidates':results, 'reason':None if selected else ('ambiguous' if eligible else 'no_reliable_match')}
