"""Parse Python without creating bytecode or importing application side effects."""
import ast
from pathlib import Path

root=Path(__file__).resolve().parents[1]
paths=[*root.glob('*.py')]
for folder in ('core','web','tests','tools'):
    paths.extend((root/folder).rglob('*.py'))
for path in paths:
    ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
print(f'Python syntax: {len(paths)} files PASS')
