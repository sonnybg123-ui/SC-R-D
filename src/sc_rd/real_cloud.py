"""Scheduled historical paper experiments; no AI or broker-order connection."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .market_data import acquire, verify_cache, run_verified_portfolio
from .research import canonical, digest, engine_fingerprint

STAFF = {'victor': 'Vic', 'alpha': 'Alpha', 'beta': 'Beta', 'ben': 'Ben', 'jah': 'Jah'}


def fingerprint(value):
    return digest(canonical(value).encode())


def session_request(now):
    local = now.astimezone(ZoneInfo('America/New_York'))
    day = local.date()
    if (local.hour, local.minute) < (16, 15):
        day -= timedelta(days=1)
    while day.weekday() > 4:
        day -= timedelta(days=1)
    def stamp(hour, minute):
        return datetime(day.year, day.month, day.day, hour, minute,
                        tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat()
    return dict(provider_symbol='AAPL', exchange='NASDAQ', mic_code='XNGS', currency='USD',
                instrument_type='Common Stock', timeframe='15min', adjustment_policy='none',
                start=stamp(9, 30), end=stamp(15, 45), max_age_seconds=4*86400)


def load_history(path):
    if path is None:
        return []
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    records = state['records']
    if state['schema_version'] != 1 or state['sha256'] != fingerprint(records):
        raise ValueError('history integrity failure')
    previous = None
    for record in records:
        body = {k: v for k, v in record.items() if k != 'record_sha256'}
        if record['previous_record'] != previous or record['record_sha256'] != fingerprint(body):
            raise ValueError('history chain failure')
        previous = record['record_sha256']
    return records


def run(root, output, scratch, history=None, now=None, fetcher=None):
    now = now or datetime.now(timezone.utc)
    records = load_history(history)  # Never silently reset a corrupt history.
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=False)
    queue = json.loads((Path(root)/'examples/real_queue.json').read_text())
    if queue['schema_version'] != 1 or {e['agent'] for e in queue['experiments']} != set(STAFF):
        raise ValueError('exact canonical roster required')
    if len(queue['experiments']) != 5 or queue['portfolio']['holdout_bars'] < 4:
        raise ValueError('invalid queue or holdout')
    request = session_request(now)
    results = []
    def save():
        state = {'schema_version': 1, 'sha256': fingerprint(records), 'records': records}
        (output/'state.json').write_text(canonical(state)+'\n', encoding='utf-8')
        package = {'schema_version': 1, 'reporter': 'Vic', 'mode': 'historical-internal-paper',
                   'created_at': now.isoformat(), 'request': request, 'holdout': 'withheld',
                   'validated_findings': [], 'experiments': results,
                   'history_sha256': state['sha256'], 'history_count': len(records)}
        (output/'results.json').write_text(canonical(package)+'\n', encoding='utf-8')
        handoffs = output/'handoffs'; handoffs.mkdir(exist_ok=True)
        for agent, name in STAFF.items():
            (handoffs/(agent+'.json')).write_text(canonical({'agent': name,
                'department_reporter': 'Vic', 'current': [r for r in results if r['agent']==agent],
                'history': [r for r in records if r['agent']==agent],
                'review_required': True, 'automatic_strategy_promotion': False})+'\n', encoding='utf-8')
        lines = ['# Vic — real-market paper research evidence', '',
                 'Historical experiments, not continuous forward trading. No AI service or broker orders.',
                 'Final holdout withheld. Findings are PROVISIONAL; no validated edge.',
                 'Repeated evidence IDs are replays, not additional independent observations.', '',
                 '| Bot | Status | Outcome | USD P/L | GBP P/L |', '|---|---|---|---:|---|']
        for r in results:
            lines.append(f"| {STAFF[r['agent']]} | {r['status']} | {r.get('outcome', 'none')} | {r.get('pnl_usd', 'N/A')} | unavailable: no verified FX |")
        lines += ['', 'Ben uses an explicitly labelled technical control; catalyst/fundamental evidence is NOT available.',
                  'Alpha and Beta have higher paper risk budgets, still bounded by the common risk engine.',
                  'ChatGPT agents must inspect handoffs and retain/reject hypotheses; this runner does not modify their memory.',
                  'Raw candles, price-level fills and SQLite ledgers remain ephemeral on the runner; only price-free derived evidence is published.',
                  'Download state.json to retain history beyond GitHub artifact retention. Never sum repeated evidence IDs.',
                  '', f"History records: {len(records)}. History SHA-256: `{state['sha256']}`."]
        (output/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    def append(record):
        body = dict(record, previous_record=records[-1]['record_sha256'] if records else None)
        records.append(dict(body, record_sha256=fingerprint(body)))
    for experiment in queue['experiments']:
        results.append({'agent': experiment['agent'], 'status': 'queued', 'finding': None,
                        'hypothesis': experiment['hypothesis'], 'version': experiment['version']})
    save()
    try:
        kwargs = {'now': now.isoformat()}
        if fetcher is not None: kwargs['fetcher'] = fetcher
        cache = acquire(request, scratch/'cache', **kwargs)
        manifest = verify_cache(cache, now=now.isoformat())
        engine = engine_fingerprint()
        for experiment, record in zip(queue['experiments'], results):
            for old in records:
                if (old['agent']==experiment['agent'] and old.get('version')==experiment['version']
                    and 'identity' in old and old['identity']['experiment']!=experiment):
                    raise ValueError('changed hypothesis requires a new version')
            identity = {'experiment': experiment, 'portfolio': queue['portfolio'], 'engine': engine,
                        'dataset_sha256': manifest['dataset_sha256'], 'request': request}
            evidence_id = fingerprint(identity)
            record.update(evidence_id=evidence_id, identity=identity,
                          data_classification='REAL', quality_status='VERIFIED', provenance=manifest)
            prior = next((r for r in records if r.get('evidence_id') == evidence_id and r['status']=='executed'), None)
            if prior:
                record.update(status='reused', finding='PROVISIONAL', outcome=prior['outcome'],
                              pnl_usd=prior['pnl_usd'], prior_record=prior['record_sha256'])
                save(); continue
            config = dict(queue['portfolio'], datasets={'AAPL': str(cache/'candles.csv')},
                          experiments=[{'name': experiment['agent'], 'allocations': [{
                              'id': experiment['agent'], 'symbol': 'AAPL', 'priority': 0,
                              'risk_budget': experiment['risk_budget'], 'strategy': experiment['strategy']}]}])
            config_path = scratch/(experiment['agent']+'.json')
            config_path.write_text(canonical(config), encoding='utf-8')
            child = run_verified_portfolio(cache, config_path, scratch/experiment['agent'], now=now.isoformat())
            result = json.loads((child/'results.json').read_text())
            trial = result['experiments'][0]
            if result['holdout_status'] != 'withheld' or not trial['final']['reconciled']:
                raise ValueError('holdout or reconciliation failure')
            pnl = trial['final']['balances']['realized_net_pnl']
            # Deliberately whitelist derived evidence: no source prices or raw ledger state.
            record.update(status='executed', finding='PROVISIONAL', pnl_usd=pnl, pnl_gbp=None,
                          fx_status='UNAVAILABLE_NO_VERIFIED_FX',
                          outcome='loss' if float(pnl)<0 else 'gain' if float(pnl)>0 else 'flat',
                          metrics=trial['attribution'][0]['summary'], order_counts=trial['order_counts'],
                          rejection_reasons=trial['rejection_reasons'], reconciled=True,
                          ledger_sha256=digest((child/trial['ledger_file']).read_bytes()),
                          result_sha256=digest((child/'results.json').read_bytes()),
                          paper_run_id=result['run_id'],
                          ledger_head=trial['final']['ledger_head'],
                          fills=[{k: t.get(k) for k in ('position_id', 'symbol', 'direction', 'setup',
                                  'opened_at', 'closed_at', 'reason', 'net_pnl', 'net_r', 'entry_fee', 'exit_fee')}
                                 for t in trial['final']['state']['closed']],
                          lessons=['Single-session development result only; no proof of edge.',
                                   'Retain losing and rejected hypotheses; review before creating a new version.'])
            append(record); save()
    except Exception as exc:
        # Only class name is safe: exceptions may contain provider bodies or credentials.
        for record in results:
            if record['status']=='queued':
                record.update(status='rejected', failure_type=type(exc).__name__, finding=None)
                append(record)
        save()
        return False
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--history', type=Path)
    args = parser.parse_args()
    raise SystemExit(0 if run(**vars(args)) else 1)
