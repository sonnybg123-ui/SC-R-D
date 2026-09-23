import json
import math
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

import pytest

from sc_rd.backtest import Candle
from sc_rd.models import TradePlan
from sc_rd.paper import Limits, PaperBroker
from sc_rd.research import Costs


T0 = '2026-01-01T09:00:00Z'
T1 = '2026-01-01T09:01:00Z'
T2 = '2026-01-01T09:02:00Z'


def plan(symbol='SYNTH', direction='long', budget=20):
    return TradePlan(symbol, direction, 100, 95 if direction == 'long' else 105,
                     110 if direction == 'long' else 90, budget, 'synthetic')


def make(tmp_path, *, cash=1000, costs=None, limits=None, name='paper.db'):
    return PaperBroker.create(tmp_path / name, initial_cash=cash, costs=costs or Costs(1, 0, 0, 0),
                              limits=limits or Limits(100, 300, 10000, 3, 500, 3600), at=T0)


@pytest.mark.parametrize('direction,exit_price', [('long', 110), ('short', 90)])
def test_cost_aware_sizing_and_round_trip(tmp_path, direction, exit_price):
    broker = make(tmp_path)
    fill = broker.open(plan(direction=direction), command_id='entry', at=T0)
    assert fill['status'] == 'filled'
    assert D(fill['position']['quantity']) == D('3.6')
    assert D(fill['position']['reserved_risk']) == 20
    assert D(fill['position']['gross_initial_risk']) == 18
    opened = broker.snapshot()
    assert D(opened['balances']['equity']) == 999
    assert D(opened['balances']['available_cash']) == 638
    result = broker.close('entry', exit_price, command_id='exit', at=T1)
    assert D(result['trade']['net_pnl']) == 34
    assert float(result['trade']['net_r']) == pytest.approx(34/18)
    final = PaperBroker(broker.path).snapshot()
    assert final['reconciled']
    assert D(final['balances']['cash']) == 1034
    assert D(final['balances']['fees_paid']) == 2
    assert final['state']['positions'] == {}
    assert final['event_count'] == 3
    assert final['closed_trade_net_r_metrics']['wins'] == 1
    assert final['closed_trade_net_r_metrics']['profit_factor'] == 'infinite'


def test_stop_loss_matches_cost_inclusive_budget(tmp_path):
    broker = make(tmp_path)
    broker.open(plan(), command_id='entry', at=T0)
    result = broker.process_bar('SYNTH', Candle(T1, 100, 102, 94, 96), command_id='stop')
    assert D(result['exits'][0]['trade']['net_pnl']) == -20
    assert D(broker.snapshot()['balances']['cash']) == 980


def test_per_trade_cap_and_explicit_oversize(tmp_path):
    broker = make(tmp_path, limits=Limits(max_trade_risk=10))
    bad = broker.open(plan(), command_id='too-large', at=T0, quantity=4)
    assert bad['status'] == 'rejected'
    assert 'per-trade' in bad['reason']
    fill = broker.open(plan(), command_id='auto', at=T0)
    assert D(fill['position']['quantity']) == D('1.6')
    assert D(fill['position']['reserved_risk']) == 10


@pytest.mark.parametrize('direction', ['long', 'short'])
def test_insufficient_cash_including_short_collateral(tmp_path, direction):
    broker = make(tmp_path, cash=100)
    result = broker.open(plan(direction=direction), command_id='entry', at=T0)
    assert result['status'] == 'rejected'
    assert 'cash' in result['reason']
    assert D(broker.snapshot()['balances']['cash']) == 100


def test_short_sale_proceeds_cannot_finance_unlimited_longs(tmp_path):
    broker = make(tmp_path, cash=500)
    assert broker.open(plan(direction='short'), command_id='short', at=T0)['status'] == 'filled'
    result = broker.open(plan('OTHER'), command_id='long', at=T0)
    assert result['status'] == 'rejected'
    snapshot = broker.snapshot()
    assert D(snapshot['balances']['short_collateral']) == 720
    assert D(snapshot['balances']['available_cash']) == 138


@pytest.mark.parametrize('limits,reason', [(Limits(max_total_risk=30), 'portfolio risk'),
                                         (Limits(max_positions=1), 'position count'),
                                         (Limits(max_gross_exposure=500), 'gross exposure')])
def test_portfolio_limits(tmp_path, limits, reason):
    broker = make(tmp_path, limits=limits)
    broker.open(plan(), command_id='first', at=T0)
    result = broker.open(plan('SECOND'), command_id='second', at=T0)
    assert result['status'] == 'rejected'
    assert reason in result['reason']
    assert len(broker.snapshot()['state']['positions']) == 1


def test_duplicate_symbol_rejected(tmp_path):
    broker = make(tmp_path)
    broker.open(plan(), command_id='first', at=T0)
    result = broker.open(plan(direction='short'), command_id='hedge', at=T0)
    assert result['status'] == 'rejected'
    assert 'symbol' in result['reason']


def test_stale_marks_block_new_risk_until_refreshed(tmp_path):
    broker = make(tmp_path, limits=Limits(max_mark_age_seconds=30))
    broker.open(plan(), command_id='first', at=T0)
    assert 'stale' in broker.open(plan('SECOND'), command_id='stale', at=T1)['reason']
    broker.mark({'SYNTH': 100}, command_id='refresh', at=T1)
    assert broker.open(plan('SECOND'), command_id='fresh', at=T1)['status'] == 'filled'


def test_drawdown_halt_latches_but_exit_is_allowed(tmp_path):
    broker = make(tmp_path, limits=Limits(max_drawdown=30))
    broker.open(plan(), command_id='first', at=T0)
    broker.mark({'SYNTH': 110}, command_id='peak', at=T1)
    assert D(broker.snapshot()['balances']['peak_equity']) == 1035
    broker.mark({'SYNTH': 90}, command_id='loss', at=T2)
    assert broker.snapshot()['state']['halted']
    assert 'halt' in broker.open(plan('SECOND'), command_id='new', at=T2)['reason']
    assert broker.close('first', 110, command_id='exit', at=T2)['status'] == 'closed'
    assert broker.snapshot()['state']['halted']  # Recovery never erases the failure.


def test_insolvent_gap_exit_records_loss_without_blocking(tmp_path):
    broker = make(tmp_path, cash=500, limits=Limits(max_drawdown=100))
    broker.open(plan(direction='short'), command_id='short', at=T0)
    result = broker.process_bar('SYNTH', Candle(T1, 400, 420, 390, 410), command_id='gap')
    assert result['exits'][0]['trade']['reason'] == 'opening-gap-stop'
    snap = broker.snapshot()
    assert D(snap['balances']['cash']) == -582
    assert snap['state']['halted']
    assert snap['reconciled']


def test_idempotency_survives_restart_and_rejects_conflicting_reuse(tmp_path):
    broker = make(tmp_path)
    first = broker.open(plan(), command_id='entry', at=T0)
    again = PaperBroker(broker.path).open(plan(), command_id='entry', at=T0)
    assert first == again
    assert broker.snapshot()['event_count'] == 2
    with pytest.raises(ValueError, match='different request'):
        broker.open(plan('OTHER'), command_id='entry', at=T0)
    broker.close('entry', 110, command_id='exit', at=T1)
    snap = broker.snapshot()
    assert broker.close('entry', 110, command_id='exit', at=T1)['status'] == 'closed'
    assert broker.snapshot() == snap


def test_rejected_retry_is_not_reexecuted(tmp_path):
    broker = make(tmp_path, limits=Limits(max_positions=1))
    broker.open(plan(), command_id='first', at=T0)
    request = dict(command_id='rejected', at=T0)
    original = broker.open(plan('OTHER'), **request)
    broker.close('first', 110, command_id='exit', at=T1)
    assert broker.open(plan('OTHER'), **request) == original
    assert broker.snapshot()['state']['positions'] == {}


def test_failed_database_append_rolls_back_all_accounting(tmp_path):
    broker = make(tmp_path)
    original = broker.snapshot()
    with sqlite3.connect(broker.path) as db:
        db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON events WHEN NEW.command_id='fail' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(ValueError, match='transaction failed'):
        broker.open(plan(), command_id='fail', at=T0)
    assert PaperBroker(broker.path).snapshot() == original


def test_concurrent_admission_cannot_overrun_portfolio_risk(tmp_path):
    broker = make(tmp_path, limits=Limits(max_total_risk=20))
    def enter(symbol):
        return PaperBroker(broker.path).open(plan(symbol), command_id=symbol, at=T0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(enter, ['ONE', 'TWO']))
    assert sorted(r['status'] for r in results) == ['filled', 'rejected']
    snap = broker.snapshot()
    assert D(snap['balances']['reserved_risk']) == 20
    assert snap['event_count'] == 3


def test_concurrent_identical_command_fills_once(tmp_path):
    broker = make(tmp_path)
    def enter(_):
        return PaperBroker(broker.path).open(plan(), command_id='same', at=T0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(enter, range(2)))
    assert results[0] == results[1]
    assert broker.snapshot()['event_count'] == 2


def test_ledger_blocks_updates_and_detects_tampering(tmp_path):
    broker = make(tmp_path)
    with sqlite3.connect(broker.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match='append-only'):
            db.execute("UPDATE events SET result_json='{}' WHERE seq=1")
        db.execute('DROP TRIGGER no_update')
        db.execute("UPDATE events SET result_json='{}' WHERE seq=1")
    with pytest.raises(ValueError, match='verification failed'):
        broker.snapshot()


def test_no_overwrite_no_implicit_initialization(tmp_path):
    missing = tmp_path / 'missing.db'
    with pytest.raises(FileNotFoundError):
        PaperBroker(missing)
    assert not missing.exists()
    broker = make(tmp_path)
    original = broker.snapshot()
    with pytest.raises(FileExistsError):
        make(tmp_path, cash=2000)
    assert broker.snapshot() == original


def test_invalid_and_backwards_commands_do_not_change_ledger(tmp_path):
    broker = make(tmp_path)
    original = broker.snapshot()
    with pytest.raises(ValueError):
        broker.mark({'SYNTH': math.nan}, command_id='bad', at=T1)
    with pytest.raises(ValueError, match='backwards'):
        broker.open(plan(), command_id='old', at='2025-01-01T09:00:00Z')
    with pytest.raises(ValueError, match='timezone'):
        broker.open(plan(), command_id='naive', at='2026-01-01T09:00:00')
    with pytest.raises(ValueError, match='multiple'):
        broker.open(plan(), command_id='precision', at=T0, quantity=1.1234567)
    assert broker.snapshot() == original


@pytest.mark.parametrize('value', [0, -1, math.nan, math.inf, True])
def test_invalid_initial_cash_creates_no_file(tmp_path, value):
    with pytest.raises(ValueError):
        make(tmp_path, cash=value)
    assert not (tmp_path / 'paper.db').exists()


def test_round_trip_costs_cannot_exceed_budget_at_stop(tmp_path):
    broker = make(tmp_path, costs=Costs(.3, 5, 4, 2))
    opened = broker.open(plan(), command_id='entry', at=T0)
    risk = D(opened['position']['reserved_risk'])
    assert risk <= 20
    closed = broker.close('entry', 95, command_id='exit', at=T1)
    assert D(closed['trade']['net_pnl']) == -risk


def test_fees_can_make_trade_unaffordable(tmp_path):
    broker = make(tmp_path, costs=Costs(11, 0, 0, 0))
    result = broker.open(plan(), command_id='entry', at=T0)
    assert result['status'] == 'rejected'
    assert D(broker.snapshot()['balances']['cash']) == 1000


def test_candle_ambiguity_and_duplicate_processing(tmp_path):
    broker = make(tmp_path)
    broker.open(plan(), command_id='entry', at=T0)
    candle = Candle(T0, 100, 111, 94, 101)
    result = broker.process_bar('SYNTH', candle, command_id='bar')
    assert result['exits'][0]['trade']['reason'] == 'ambiguous-conservative-stop'
    snap = broker.snapshot()
    assert broker.process_bar('SYNTH', candle, command_id='bar') == result
    assert broker.snapshot() == snap
    assert broker.process_bar('SYNTH', candle, command_id='other-bar')['status'] == 'rejected'
    assert broker.open(plan(), command_id='too-late', at=T0)['status'] == 'rejected'


def test_no_future_bar_or_mark_needed_for_entry(tmp_path):
    broker = make(tmp_path)
    assert broker.open(plan(), command_id='entry', at=T0)['status'] == 'filled'
    snap = broker.snapshot()
    assert snap['state']['last_bars'] == {}
    assert D(snap['state']['marks']['SYNTH']['price']) == 100


def test_paper_cli_demo_audit_and_rejection(tmp_path):
    path = tmp_path / 'demo.db'
    proc = subprocess.run([sys.executable, '-m', 'sc_rd', 'paper', 'demo', str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    demo = json.loads(proc.stdout)
    assert demo['event_count'] == 7
    assert demo['reconciled']
    assert demo['state']['positions'] == {}
    audit = subprocess.run([sys.executable, '-m', 'sc_rd', 'paper', 'audit', str(path)], capture_output=True, text=True)
    assert audit.returncode == 0, audit.stderr
    assert json.loads(audit.stdout)['ledger_head'] == demo['ledger_head']
    retry = subprocess.run([sys.executable, '-m', 'sc_rd', 'paper', 'demo', str(path)], capture_output=True, text=True)
    assert retry.returncode == 2
    assert PaperBroker(path).snapshot()['ledger_head'] == demo['ledger_head']


def test_rehashed_false_snapshot_still_fails_replay(tmp_path):
    from sc_rd.research import canonical, digest
    broker = make(tmp_path)
    with sqlite3.connect(broker.path) as db:
        row = db.execute('SELECT * FROM events WHERE seq=1').fetchone()
        seq, command_id, request, result, stored, parent, _ = row
        changed = json.loads(stored)
        changed['cash'] = '9999'
        stored = canonical(changed)
        body = {'seq': seq, 'id': command_id, 'request': request, 'result': result, 'state': stored, 'previous': parent}
        db.execute('DROP TRIGGER no_update')
        db.execute('UPDATE events SET state_json=?, event_hash=? WHERE seq=1', (stored, digest(canonical(body).encode())))
    with pytest.raises(ValueError, match='replay differs'):
        broker.snapshot()


def test_partial_mark_failure_rolls_back_entire_event(tmp_path):
    broker = make(tmp_path)
    broker.open(plan(), command_id='entry', at=T0)
    before = broker.snapshot()
    with pytest.raises(ValueError):
        broker.mark({'SYNTH': 110, 'OTHER': -1}, command_id='bad-mark', at=T1)
    assert broker.snapshot() == before


def test_marks_do_not_change_cash_and_report_exposure_breach(tmp_path):
    broker = make(tmp_path, limits=Limits(max_gross_exposure=400))
    broker.open(plan(), command_id='entry', at=T0)
    cash = broker.snapshot()['balances']['cash']
    broker.mark({'SYNTH': 200}, command_id='mark', at=T1)
    snap = broker.snapshot()
    assert snap['balances']['cash'] == cash
    assert D(snap['balances']['equity']) == 1359
    assert 'marked gross exposure exceeds limit' in snap['risk_flags']


def test_unheld_mark_does_not_create_pnl(tmp_path):
    broker = make(tmp_path)
    broker.mark({'UNHELD': 999}, command_id='mark', at=T1)
    snap = broker.snapshot()
    assert D(snap['balances']['equity']) == 1000
    assert D(snap['balances']['unrealized_gross_pnl']) == 0


def test_api_ignores_callers_decimal_context(tmp_path):
    from decimal import localcontext
    broker = make(tmp_path)
    with localcontext() as context:
        context.prec = 5
        fill = broker.open(plan(), command_id='entry', at=T0)
        broker.close('entry', 110, command_id='exit', at=T1)
        assert broker.snapshot()['reconciled']
    assert D(fill['position']['reserved_risk']) == 20
    assert D(PaperBroker(broker.path).snapshot()['balances']['cash']) == 1034


def test_empty_or_invalid_database_fails_closed(tmp_path):
    path = tmp_path / 'broken.db'
    path.write_text('not a database')
    with pytest.raises(ValueError, match='paper ledger'):
        PaperBroker(path).snapshot()


@pytest.mark.parametrize('changes', [{'max_positions': True}, {'max_trade_risk': 0},
                                    {'max_total_risk': math.nan}, {'max_mark_age_seconds': 0}])
def test_invalid_limits(changes):
    with pytest.raises(ValueError):
        Limits(**changes)


def test_closing_already_closed_position_never_charges_twice(tmp_path):
    broker = make(tmp_path)
    broker.open(plan(), command_id='entry', at=T0)
    broker.close('entry', 110, command_id='exit', at=T1)
    before = broker.snapshot()['balances']
    assert broker.close('entry', 110, command_id='new-exit-id', at=T1)['status'] == 'rejected'
    assert broker.snapshot()['balances'] == before


def test_entry_cost_cannot_cross_drawdown_gate(tmp_path):
    broker = make(tmp_path, limits=Limits(max_drawdown=.5))
    result = broker.open(plan(), command_id='entry', at=T0)
    assert result['status'] == 'rejected'
    assert 'entry costs' in result['reason']
    assert D(broker.snapshot()['balances']['cash']) == 1000


def test_invalid_mark_shape_is_clear_error(tmp_path):
    broker = make(tmp_path)
    with pytest.raises(ValueError, match='mapping'):
        broker.mark([1, 2], command_id='bad-shape', at=T0)
    assert broker.snapshot()['event_count'] == 1


def test_cli_individual_lifecycle_and_rejection_status(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / 'cli.db'
    def cli(*args):
        return subprocess.run([sys.executable, '-m', 'sc_rd', 'paper', *map(str, args)], capture_output=True, text=True)
    init = cli('init', database, '--cash', '1000', '--config', root / 'examples/paper_config.json', '--at', T0)
    assert init.returncode == 0, init.stderr
    rejected = cli('open', database, root / 'examples/paper_plan.json', '--quantity', '100', '--id', 'too-big', '--at', T0)
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)['status'] == 'rejected'
    opened = cli('open', database, root / 'examples/paper_plan.json', '--id', 'entry', '--at', T0)
    assert opened.returncode == 0, opened.stderr
    marks = tmp_path / 'marks.json'
    marks.write_text('{"SYNTH":102}')
    marked = cli('mark', database, marks, '--id', 'mark', '--at', T1)
    assert marked.returncode == 0, marked.stderr
    candle = tmp_path / 'bar.json'
    candle.write_text(json.dumps({'timestamp':T2,'open':102,'high':111,'low':101,'close':110}))
    exited = cli('bar', database, 'SYNTH', candle, '--id', 'exit')
    assert exited.returncode == 0, exited.stderr
    assert json.loads(exited.stdout)['exits'][0]['status'] == 'closed'
    again = cli('close', database, 'entry', '--price', '110', '--id', 'duplicate-exit', '--at', T2)
    assert again.returncode == 2
    assert PaperBroker(database).snapshot()['reconciled']
