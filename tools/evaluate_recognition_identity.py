#!/usr/bin/env python3
"""Compare immutable B00 results with a separate synthetic identity-evidence suite."""
import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.evaluate_recognition_final import evaluate,FIXTURES,BASELINE

EVIDENCE=ROOT/'tests/fixtures/recognition_identity_evidence_cases.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='new JSON path; existing files are never overwritten')
    parser.add_argument('--source-revision',help='recognition code revision under evaluation')
    args=parser.parse_args()
    if args.output and os.path.lexists(args.output):parser.error('output already exists; refusing to overwrite')
    with redirect_stdout(io.StringIO()):
        full=evaluate(FIXTURES.read_bytes(),json.loads(BASELINE.read_text(encoding='utf8')),EVIDENCE.read_bytes())
    report={'source_revision':args.source_revision,'fixed_fixture_version':full['fixture_version'],
            'fixed_fixture_sha256':full['fixture_sha256'],'fixed_scenarios':full['scenarios'],
            'fixed_acceptance':full['acceptance'],'evidence_suite':full['extension'],'method':full['method'],
            'interpretation':'The fixed B00 ground truth and acceptance remain unchanged. '
                             'The separate synthetic suite tests review without identity evidence and automatic matching with explicitly supplied evidence.'}
    output=json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    if args.output:
        with Path(args.output).open('x',encoding='utf8') as stream:stream.write(output)
    else:print(output,end='')


if __name__=='__main__':main()
