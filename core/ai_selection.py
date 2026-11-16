"""Strictly decode an AI candidate suggestion, then require independent evidence."""
import json
from .candidate_evaluator import evaluate_candidates


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def accepted_suggestion(response, candidates, media_type, titles, year=None):
    if not isinstance(response, str):
        return None
    try:
        data = json.loads(response, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid constant')))
    except (ValueError, TypeError, RecursionError):
        return None
    if (not isinstance(data, dict) or set(data) != {'selected_id', 'media_type', 'reason'}
            or data['media_type'] != media_type or not isinstance(data['reason'], str)):
        return None
    selected_id = data['selected_id']
    if type(selected_id) is not int or selected_id <= 0:
        return None
    matching = [item for item in candidates if type(item.get('id')) is int and item['id'] == selected_id]
    if len(matching) != 1:
        return None
    decision = evaluate_candidates(candidates, media_type, titles, year)
    chosen = decision['selected']
    return matching[0] if chosen is not None and chosen.get('id') == selected_id else None
