"""Versioned parse records, with backups before replacing legacy data."""
from . import parse_identity
from .execution_mode import is_preview
from .json_store import update_json,backup_json


def update_record(path,key,entry):
    if is_preview():return None
    def mutate(current):
        previous=current.get(key)
        legacy=bool(current) and (not any(isinstance(v,dict) and v.get('_schema')==parse_identity.RULE_VERSION for v in current.values())
                or (previous is not None and (not isinstance(previous,dict) or previous.get('_schema')!=parse_identity.RULE_VERSION)))
        if legacy:backup_json(path,tag='t10')
        current[key]=entry
    return update_json(path,mutate)
