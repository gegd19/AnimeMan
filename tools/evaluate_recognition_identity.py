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

POLICY='identity-evidence-approved-v1'
EVIDENCE_SHA256='c37d135ba24dc5213e655373009401c44303888538e54411c772a1315b3c5e9f'
REVIEW_IDS=('C46','C49')


def adjudicate(full):
    """Apply the user-approved evidence condition without changing B00 metrics."""
    cases={row['case_id']:row for row in full['cases']}
    extension=full['extension']
    evidence={row['case_id']:row for row in extension.get('cases',[])}
    fixture_ok=(extension.get('fixture_version')=='identity-evidence-v1'
                and extension.get('fixture_sha256')==EVIDENCE_SHA256
                and len(evidence)==6)
    results={}
    for scenario,metrics in full['scenarios'].items():
        review_failures=[ident for ident in REVIEW_IDS if ident not in cases
                         or cases[ident]['scenarios'][scenario]['actual'] is not None]
        ordinary=[row for row in cases.values() if row['case_id'] not in REVIEW_IDS and row['expected'] is not None]
        ordinary_failed=[row['case_id'] for row in ordinary
                         if row['scenarios'][scenario]['actual']!=row['expected']]
        evidence_failures=[]
        for ident in REVIEW_IDS:
            original=cases.get(ident)
            for suffix,kind in (('N','none'),('T','tmdb'),('M','manual')):
                evidence_id='I'+ident[1:]+suffix
                item=evidence.get(evidence_id)
                truth=original['expected'] if original else None
                expected=None if suffix=='N' else truth
                if (not item or truth is None or item.get('ground_truth')!=truth or item.get('evidence_kind')!=kind
                        or item.get('expected')!=expected or item['scenarios'][scenario]['actual']!=expected):
                    evidence_failures.append(evidence_id)
        evidence_gate=extension.get('acceptance',{}).get(scenario,{}).get('passed') is True
        passed=(fixture_ok and not review_failures and not ordinary_failed and not evidence_failures and evidence_gate
                and metrics['unsafe_auto']==0 and metrics['runtime_errors']==0)
        results[scenario]={'passed':bool(passed),'evidence_required_review':list(REVIEW_IDS),
                           'review_failures':review_failures,'other_eligible_total':len(ordinary),
                           'other_eligible_correct':len(ordinary)-len(ordinary_failed),
                           'other_eligible_failed':ordinary_failed,'evidence_failures':evidence_failures,
                           'evidence_fixture_verified':fixture_ok,'unsafe_auto':metrics['unsafe_auto'],
                           'runtime_errors':metrics['runtime_errors']}
    return results


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
            'acceptance_policy':POLICY,'approved_acceptance':adjudicate(full),
            'interpretation':'The fixed B00 ground truth and acceptance remain unchanged. '
                             'The separate synthetic suite tests review without identity evidence and automatic matching with explicitly supplied evidence.'}
    output=json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n'
    if args.output:
        with Path(args.output).open('x',encoding='utf8') as stream:stream.write(output)
    else:print(output,end='')


if __name__=='__main__':main()
