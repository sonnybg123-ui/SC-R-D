import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest
from sc_rd.real_cloud import run, session_request, load_history

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-09-24T21:00:00+00:00')


def provider(request):
    start = datetime.fromisoformat(request['start'])
    return {'status': 'ok', 'meta': dict(symbol='AAPL', exchange='NASDAQ', mic_code='XNGS',
            currency='USD', type='Common Stock', interval='15min'),
            'values': [dict(datetime=(start+timedelta(minutes=15*i)).isoformat(),
                            open=str(100+i), high=str(102+i), low=str(99+i), close=str(101+i))
                       for i in range(26)]}


def test_completed_session_and_dst():
    assert session_request(NOW)['start']=='2026-09-24T13:30:00+00:00'
    assert session_request(datetime.fromisoformat('2026-09-28T12:00:00+00:00'))['start']=='2026-09-25T13:30:00+00:00'
    assert session_request(datetime.fromisoformat('2026-12-01T22:00:00+00:00'))['start']=='2026-12-01T14:30:00+00:00'
    assert session_request(NOW)['mic_code']=='XNGS'


def test_five_bots_reconcile_preserve_history_and_deduplicate(tmp_path):
    out=tmp_path/'out'
    assert run(ROOT,out,tmp_path/'scratch',now=NOW,fetcher=provider)
    records=load_history(out/'state.json')
    assert len(records)==5 and all(r['reconciled'] for r in records)
    assert {r['agent'] for r in records}=={'victor','alpha','beta','ben','jah'}
    assert all(r['finding']=='PROVISIONAL' and r['pnl_gbp'] is None for r in records)
    assert all(r['provenance']['row_count']==26 for r in records)
    assert all('final_holdout' not in r for r in records)
    assert run(ROOT,tmp_path/'out2',tmp_path/'scratch2',out/'state.json',NOW+timedelta(minutes=1),provider)
    assert load_history(tmp_path/'out2/state.json')==records
    result=json.loads((tmp_path/'out2/results.json').read_text())
    assert all(r['status']=='reused' for r in result['experiments'])
    published=''.join(p.read_text() for p in out.rglob('*.json'))
    assert '"open": "100"' not in published and '"entry_price"' not in published
    assert len(list((out/'handoffs').glob('*.json')))==5


def test_wrong_mic_fails_closed_and_rejection_is_retained(tmp_path):
    def wrong(request):
        result=provider(request); result['meta']['mic_code']='XNAS'; return result
    assert not run(ROOT,tmp_path/'out',tmp_path/'scratch',now=NOW,fetcher=wrong)
    records=load_history(tmp_path/'out/state.json')
    assert len(records)==5 and all(r['status']=='rejected' for r in records)
    assert not run(ROOT,tmp_path/'out2',tmp_path/'scratch2',tmp_path/'out/state.json',NOW,wrong)
    assert len(load_history(tmp_path/'out2/state.json'))==10


def test_history_tamper_never_resets(tmp_path):
    assert run(ROOT,tmp_path/'out',tmp_path/'scratch',now=NOW,fetcher=provider)
    state=json.loads((tmp_path/'out/state.json').read_text()); state['records'][0]['pnl_usd']='99999'
    (tmp_path/'bad.json').write_text(json.dumps(state))
    with pytest.raises(ValueError,match='history integrity'):
        run(ROOT,tmp_path/'out2',tmp_path/'scratch2',tmp_path/'bad.json',NOW,provider)
    assert not (tmp_path/'out2').exists()


def test_secret_in_provider_error_not_published(tmp_path):
    def broken(request): raise RuntimeError('SECRET_SENTINEL')
    assert not run(ROOT,tmp_path/'out',tmp_path/'scratch',now=NOW,fetcher=broken)
    assert 'SECRET_SENTINEL' not in ''.join(p.read_text() for p in (tmp_path/'out').rglob('*') if p.is_file())
