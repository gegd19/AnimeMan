"""Conservative duration evidence in minutes; no conclusion without both values."""
import math


def compare_duration(local, reference):
    def valid(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    if not valid(local) or not valid(reference):
        return {'status': 'unknown'}
    difference = abs(local - reference)
    tolerance = max(10.0, reference * 0.25)
    return {'status': 'supported' if difference <= tolerance else 'conflict',
            'difference': difference, 'tolerance': tolerance}
