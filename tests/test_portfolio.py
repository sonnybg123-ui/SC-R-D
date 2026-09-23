import copy
import json
import subprocess
import sys
from decimal import Decimal as D
from pathlib import Path

import pytest

from sc_rd.backtest import Candle
from sc_rd.models import TradePlan
from sc_rd.paper import Limits, PaperBroker
from sc_rd.portfolio import run_portfolio
from sc_rd.research import Costs


@pytest.fixture
def case(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'examples/portfolio.json').read_text())
    config['datasets'] = {'A':'bars.csv', 'B':'bars.csv'}
    config['costs'] = dict(fee_per_side=0,fee_bps=0,spread_bps=0,slippage_bps=0)
    config['limits'].update(max_positions=1,max_total_risk=100,max_gross_exposure=2000,max_drawdown=500)
    config['holdout_bars'] = 2
    config['experiments'] = [{'name':'shared', 'allocations':[
        {'id': 'a', 'symbol':'A', 'priority':0,'risk_budget':20,
         'strategy':{'name':'alpha','desk':'alpha','lookback':2,'reward_r':2,'max_holding_bars':2}},
        {'id': 'b', 'symbol':'B', 'priority':1,'risk_budget':20,
         'strategy':{'name':'beta','desk':'beta','lookback':2,'reward_r':2,'max_holding_bars':2}}]}]
    rows = (root / 'data/portfolio_ohlc.csv').read_text().splitlines()
    (tmp_path / 'bars.csv').write_text('\n'.join(rows[:9])+'\n')
    return config, tmp_path


def execute(case, name='run', period='development'):
    config, base = case
    path = base / f'{name}.json'
    path.write_text(json.dumps(config))
    folder = run_portfolio(path, base / name, period=period)
    return json.loads((folder/'results.json').read_text()), folder


def test_shared_priority_and_ledger_reconciliation(case):
    result, folder = execute(case)
    trial = result['experiments'][0]
    first = [o for o in trial['orders'] if o['bar_index'] == 3]
    assert [(o['allocation_id'],o['status']) for o in first] == [('a','filled'),('b','rejected')]
    assert first[0]['signal']['index'] == 2
    assert first[0]['position']['entry'] == '102.0'
    assert trial['final']['reconciled']
    assert PaperBroker(folder/trial['ledger_file']).snapshot() == trial['final']
    assert result['holdout_status'] == 'withheld'
    assert trial['end_exclusive'] == 6
    assert json.loads((folder/'manifest.json').read_text())['status'] == 'complete'


def test_priority_is_explicit_not_allocation_list_order(case):
    before, _ = execute(case, 'before')
    case[0]['experiments'][0]['allocations'].reverse()
    after, _ = execute(case, 'after')
    assert before['experiments'] == after['experiments']
    for a in case[0]['experiments'][0]['allocations']:
        a['priority'] = 1-a['priority']
    reversed_priority, _ = execute(case, 'reversed')
    first = [o for o in reversed_priority['experiments'][0]['orders'] if o['bar_index']==3]
    assert first[0]['allocation_id'] == 'b'
    assert first[0]['status'] == 'filled'


def test_same_bar_profits_cannot_fund_other_entries(case):
    config, _ = case
    config['initial_cash'] = 900
    config['limits']['max_positions'] = 2
    for a in config['experiments'][0]['allocations']:
        a['strategy']['reward_r'] = 1
    result, _ = execute(case)
    trial = result['experiments'][0]
    first = [o for o in trial['orders'] if o['bar_index']==3]
    assert first[0]['status']=='filled'
    assert first[1]['status']=='rejected'
    assert 'cash' in first[1]['reason']
    assert any(e['bar_index']==3 and D(e['trade']['net_pnl']) > 0 for e in trial['exits'])


def test_current_bar_future_extremes_cannot_change_admission(case):
    before, _ = execute(case,'before')
    p = case[1]/'bars.csv'
    rows = p.read_text().splitlines()
    parts = rows[4].split(',')
    rows[4] = parts[0]+','+parts[1]+',999,1,500'
    p.write_text('\n'.join(rows)+'\n')
    after, _ = execute(case,'after')
    orders_a = [o for o in before['experiments'][0]['orders'] if o['bar_index']<=3]
    orders_b = [o for o in after['experiments'][0]['orders'] if o['bar_index']<=3]
    assert orders_a == orders_b


def test_holdout_mutations_do_not_change_development(case):
    before, _ = execute(case,'before')
    p = case[1]/'bars.csv'
    rows = p.read_text().splitlines()
    for index in (7,8):
        rows[index] = rows[index].split(',')[0]+',100,999,1,500'
    p.write_text('\n'.join(rows)+'\n')
    after, _ = execute(case,'after')
    assert before['experiments'] == after['experiments']
    assert before['run_id'] != after['run_id']


def test_end_policies_preserve_or_liquidate_explicitly(case):
    config, _ = case
    config['end_policy']='keep_open'
    for a in config['experiments'][0]['allocations']:
        a['strategy'].update(reward_r=100,max_holding_bars=100)
    retained, _ = execute(case,'retain')
    trial = retained['experiments'][0]
    assert len(trial['final']['state']['positions']) == 1
    assert trial['final']['state']['closed'] == []
    config['end_policy']='liquidate'
    closed, _ = execute(case,'liquidate')
    final = closed['experiments'][0]['final']
    assert final['state']['positions'] == {}
    assert final['state']['closed'][0]['reason'] == 'replay-end'
    assert D(final['balances']['equity']) == D(trial['final']['balances']['equity'])


def test_timeouts_are_broker_exits(case):
    config, _ = case
    for a in config['experiments'][0]['allocations']:
        a['strategy'].update(reward_r=100,max_holding_bars=1)
    result, _ = execute(case)
    assert result['experiments'][0]['final']['state']['closed']
    assert all(t['reason']=='replay-timeout' for t in result['experiments'][0]['final']['state']['closed'])


def test_holdout_starts_flat_and_is_explicitly_consumed(case):
    result, _ = execute(case,period='holdout')
    trial = result['experiments'][0]
    assert trial['start_index']==6
    assert result['holdout_status']=='consumed-do-not-retune'
    assert trial['final']['state']['initial_cash']=='1000'
    assert all(o['bar_index']>=6 for o in trial['orders'])


@pytest.mark.parametrize('change',['grid','duplicate_priority','unknown_symbol','holdout','policy'])
def test_invalid_inputs_fail_before_output(case,change):
    config, base = case
    if change=='grid':
        p=base/'other.csv'
        rows=(base/'bars.csv').read_text().splitlines()
        p.write_text('\n'.join([rows[0],*rows[2:]])+'\n')
        config['datasets']['B']='other.csv'
    elif change=='duplicate_priority':
        config['experiments'][0]['allocations'][1]['priority']=0
    elif change=='unknown_symbol':
        config['experiments'][0]['allocations'][0]['symbol']='UNKNOWN'
    elif change=='holdout':
        config['holdout_bars']=7
    else:
        config['end_policy']='ignore'
    with pytest.raises(ValueError):
        execute(case)
    assert not (base/'run').exists()


def test_deterministic_results_and_no_overwrite(case):
    a, folder_a=execute(case,'one')
    b, folder_b=execute(case,'two')
    assert a==b
    assert (folder_a/'results.json').read_bytes()==(folder_b/'results.json').read_bytes()
    assert (folder_a/'report.md').read_bytes()==(folder_b/'report.md').read_bytes()
    with pytest.raises(FileExistsError):
        execute(case,'one')


def test_failed_run_has_no_success_marker(case,monkeypatch):
    import sc_rd.portfolio as module
    def broken(*args,**kwargs):
        raise ValueError('injected replay failure')
    monkeypatch.setattr(module,'replay_experiment',broken)
    with pytest.raises(ValueError,match='injected'):
        execute(case)
    folder = next((case[1]/'run').iterdir())
    assert json.loads((folder/'manifest.json').read_text())['status']=='failed'
    assert not (folder/'results.json').exists()


def test_atomic_bars_avoid_symbol_order_drawdown(tmp_path):
    broker=PaperBroker.create(tmp_path/'atomic.db',initial_cash=1000,costs=Costs(0,0,0,0),limits=Limits(max_drawdown=5),at='2026-01-01T00:00:00Z')
    for symbol in ('A','B'):
        broker.open(TradePlan(symbol,'long',100,50,200,50,'test'),quantity=1,command_id=symbol,at='2026-01-01T00:00:00Z')
    result=broker.process_bars({'A':Candle('2026-01-01T00:01:00Z',100,101,89,90),
                                'B':Candle('2026-01-01T00:01:00Z',100,111,99,110)},command_id='batch')
    assert result['status']=='processed'
    snapshot=broker.snapshot()
    assert not snapshot['state']['halted']
    assert D(snapshot['balances']['equity'])==1000
    assert D(snapshot['balances']['drawdown'])==0


def test_duplicate_batch_rejects_all_symbols(tmp_path):
    at='2026-01-01T00:00:00Z'
    broker=PaperBroker.create(tmp_path/'atomic.db',initial_cash=1000,costs=Costs(0,0,0,0),limits=Limits(),at=at)
    candle=Candle(at,100,101,99,100)
    broker.process_bar('B',candle,command_id='old')
    result=broker.process_bars({'A':candle,'B':candle},command_id='batch')
    assert result['status']=='rejected'
    assert 'A' not in broker.snapshot()['state']['last_bars']


def test_cli(case):
    config,base=case
    path=base/'config.json'
    path.write_text(json.dumps(config))
    proc=subprocess.run([sys.executable,'-m','sc_rd','portfolio',str(path),'--output',str(base/'cli')],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    result=json.loads((Path(proc.stdout.strip())/'results.json').read_text())
    assert result['holdout_status']=='withheld'


@pytest.mark.parametrize('opening,expected_price,expected_equity,reason',[
    (120,107,1040,'replay-opening-target'),
    (90,90,904,'replay-opening-gap-stop')])
def test_opening_gap_exits_precede_entries_without_phantom_equity(case,opening,expected_price,expected_equity,reason):
    config,base=case
    config['holdout_bars']=3
    config['end_policy']='keep_open'
    p=base/'bars.csv'
    rows=p.read_text().splitlines()
    stamp=rows[5].split(',')[0]
    rows[5]=f'{stamp},{opening},{opening+1},{opening-1},{opening}'
    p.write_text('\n'.join(rows)+'\n')
    result,_=execute(case)
    trial=result['experiments'][0]
    gap=next(e for e in trial['exits'] if e['phase']=='gap')
    assert gap['trade']['reason']==reason
    assert D(gap['trade']['exit_price'])==expected_price
    opening_point=next(p for p in trial['equity_curve'] if p['bar_index']==4 and p['phase']=='open')
    assert D(opening_point['balances']['equity'])==expected_equity
    assert D(opening_point['balances']['peak_equity'])<=1040


def test_batch_timestamps_must_match_without_side_effects(tmp_path):
    at='2026-01-01T00:00:00Z'
    broker=PaperBroker.create(tmp_path/'atomic.db',initial_cash=1000,costs=Costs(0,0,0,0),limits=Limits(),at=at)
    before=broker.snapshot()
    with pytest.raises(ValueError,match='same timestamp'):
        broker.process_bars({'A':Candle(at,100,101,99,100),'B':Candle('2026-01-01T00:01:00Z',100,101,99,100)},command_id='batch')
    assert broker.snapshot()==before
