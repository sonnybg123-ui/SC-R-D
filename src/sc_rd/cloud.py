"""Fixed, offline cloud research workload; no broker/network client or secret inputs."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .lab import run_lab
from .research import canonical, digest, engine_fingerprint
from .walkforward import load_inputs, run_walkforward

STAFF = ['Vic', 'Alpha', 'Beta', 'Ben', 'Jah']


def run_cloud(root: Path, output: Path) -> Path:
    # Each invocation owns a new directory. Never reuse/overwrite previous evidence.
    output.mkdir(parents=True, exist_ok=False)
    records = [{'id': name, 'status': 'queued', 'history': ['queued'], 'finding': None}
               for name in ('strategy-lab', 'portfolio-walkforward')]
    result = {'data_classification': 'SYNTHETIC', 'evidence_status': 'TEST_ONLY', 'evidence_eligible': False, 'schema_version': 1, 'mode': 'paper-research-only', 'staff': STAFF,
              'holdout_status': 'withheld', 'status': 'running', 'experiments': records,
              'engine_sha256': engine_fingerprint(), 'validated_findings': [],
              'validation_policy': 'Synthetic results cannot establish a validated market finding.'}
    def save():
        (output/'results.json').write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')
        lines = ['# SC Trading R&D cloud research', '', 'Paper only. No broker or live-money execution.',
                 '', f"Run status: **{result['status']}**. Final holdout: **withheld**.",
                 'Department: Vic, Alpha, Beta, Ben and Jah. Ledger is software infrastructure.', '',
                 '| Experiment | Execution status | Finding |', '|---|---|---|']
        lines += [f"| {r['id']} | {r['status']} | {r['finding'] or 'none'} |" for r in records]
        lines += ['', 'Queued = awaiting checks/execution; executed = completed and checked; rejected = not accepted due to a failed gate or execution error.',
                  'TEST_ONLY = synthetic software checks, never research evidence. Provisional findings require VERIFIED REAL data. Validated finding = separately reviewed evidence under a frozen real-data validation protocol; none are produced here.',
                  'Rejected paper orders inside a completed experiment are risk-engine decisions, not rejected experiments.',
                  'Every window resets synthetic cash; this is historical research, not a persistent hourly trading account.',
                  'Full JSON, data declarations, strategy versions, child reports and reconciled SQLite ledgers accompany this report.', '']
        (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    save()
    try:
        config, portfolio, data, grid, cutoff, method, identity, quality = load_inputs(root/'examples/walkforward.json')
        if any(v['declaration']['kind'] != 'synthetic' for v in quality['datasets'].values()):
            raise ValueError('cloud runner currently accepts synthetic fixtures only')
        lab_path = root/'examples/cloud_lab.json'
        lab = json.loads(lab_path.read_text(encoding='utf-8'))
        # Enforce the same validated bytes and reserved final period for both engines.
        lab_data = (lab_path.parent/lab['dataset']).resolve()
        if lab_data != (root/'data/portfolio_ohlc.csv').resolve():
            raise ValueError('cloud lab must use the approved synthetic fixture')
        if digest(lab_data.read_bytes()) not in identity['datasets'].values() or lab['holdout_bars'] != len(grid)-cutoff:
            raise ValueError('lab data or holdout differs from the validated portfolio')
        result['data_quality'] = quality
        result['portfolio_method'] = method
        result['lab_method'] = lab
        result['strategy_versions'] = {digest(canonical({'strategy': a['strategy'], 'engine': identity['engine']}).encode()): a['strategy']
                                       for e in portfolio['experiments'] for a in e['allocations']}
        result['experiment_fingerprint'] = digest(canonical({'portfolio': identity, 'walkforward': config,
                                                             'lab': lab, 'quality': quality['manifest_sha256']}).encode())
        save()
        for record, operation in zip(records, (
            lambda: run_lab(lab_path, output/'lab', include_holdout=False),
            lambda: run_walkforward(root/'examples/walkforward.json', output/'portfolio', include_holdout=False),
        )):
            child = operation()
            payload = json.loads((child/'results.json').read_text(encoding='utf-8'))
            if payload['final_holdout'] is not None:
                raise ValueError('holdout protection failed')
            if record['id'] == 'portfolio-walkforward':
                trials = payload['final_training'] + [t for f in payload['folds'] for k in ('training','testing') for t in f[k]]
                if not all(t['final']['reconciled'] for t in trials):
                    raise ValueError('ledger reconciliation failed')
            record.update(status='executed', finding='TEST_ONLY', result_path=child.relative_to(output).as_posix(), fingerprint=payload['run_id'])
            record['history'].append('executed')
            save()
        result['status'] = 'complete'
        save()
    except Exception as exc:
        result['status'] = 'failed'
        # Exception values can contain file contents; do not publish arbitrary error text.
        result['failure_type'] = type(exc).__name__
        for record in records:
            if record['status'] == 'queued':
                record.update(status='rejected', finding=None)
                record['history'].append('rejected')
        save()
        raise
    return output


def configure(subs):
    p = subs.add_parser('cloud', help='run the fixed synthetic cloud research workload')
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--output', type=Path, required=True)
    p.set_defaults(func=lambda a: print(run_cloud(a.root.resolve(), a.output)))
    p = subs.add_parser('walkforward', help='data-gated portfolio walk-forward research')
    p.add_argument('config', type=Path)
    p.add_argument('--output', type=Path, default=Path('reports'))
    p.add_argument('--include-holdout', action='store_true')
    p.set_defaults(func=lambda a: print(run_walkforward(a.config, a.output, include_holdout=a.include_holdout)))
    p = subs.add_parser('data-check', help='verify declared data provenance, hashes and coverage')
    p.add_argument('config', type=Path)
    p.set_defaults(func=lambda a: print(json.dumps(load_inputs(a.config)[-1], indent=2)))
