"""Verify direct pins, tested constraints, and installed lock versions agree."""
from importlib.metadata import version
from pathlib import Path
import re

root=Path(__file__).resolve().parents[1]
def pins(filename):
    result={}
    for line in (root/filename).read_text().splitlines():
        match=re.fullmatch(r'([\w.-]+)==([^\s\\]+)(?: \\)?',line)
        if match:result[match[1].lower().replace('_','-')]=match[2]
    return result
constraints=pins('constraints.txt')
for name in ('requirements.lock','requirements-dev.lock'):
    locked=pins(name)
    assert locked and all(constraints[key]==value for key,value in locked.items())
    for key,value in locked.items():assert version(key)==value,(key,value,version(key))
for name in ('requirements.txt','requirements-dev.txt'):
    assert all(pins('requirements-dev.lock')[key]==value for key,value in pins(name).items())
print('Dependency pins and installed locks PASS')
