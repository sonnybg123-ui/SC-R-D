import math
from pathlib import Path
import subprocess
import sys
from dataclasses import replace

import pytest

from sc_rd.backtest import Candle, load_ohlc_csv, resolve_plan
from sc_rd.desks import DESKS
from sc_rd.experiment import Experiment, save_experiment
from sc_rd.journal import append_trade, load_trades, summarize
from sc_rd.metrics import performance_metrics
from sc_rd.models import PaperTrade, TradePlan
from sc_rd.risk import cash_risk, pnl, position_size, realized_r


def plan(direction='long'):
    return TradePlan('SYNTH', direction, 100, 95 if direction == 'long' else 105,
                     110 if direction == 'long' else 90, 23, 'synthetic')


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf, 0, -1])
@pytest.mark.parametrize('field', ['entry', 'stop', 'target', 'risk_budget'])
def test_invalid_plan_numbers(field, value):
    with pytest.raises(ValueError):
        replace(plan(), **{field: value})


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf, 0, -1])
def test_invalid_trade_and_risk_numbers(value):
    with pytest.raises(ValueError):
        PaperTrade(plan(), value, 1)
    with pytest.raises(ValueError):
        PaperTrade(plan(), 100, value)
    with pytest.raises(ValueError):
        cash_risk(plan(), value)


@pytest.mark.parametrize('field', ['open', 'high', 'low', 'close'])
@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_invalid_candle_numbers(field, value):
    with pytest.raises(ValueError):
        replace(Candle('t', 100, 110, 90, 100), **{field: value})


@pytest.mark.parametrize('value', [math.nan, math.inf, -math.inf])
def test_invalid_metrics(value):
    with pytest.raises(ValueError):
        performance_metrics([1, value])


def test_whole_fractional_and_zero_size():
    p = plan()
    assert position_size(p) == pytest.approx(4.6)
    assert position_size(p, fractional=False) == 4
    assert cash_risk(p, 4) <= p.risk_budget
    assert position_size(replace(p, risk_budget=1), fractional=False) == 0


@pytest.mark.parametrize('direction,price', [('long', 90), ('short', 110)])
def test_gap_stop_exceeds_one_r(direction, price):
    outcome = resolve_plan(plan(direction), [Candle('t', price, price+15, price-15, price)])
    assert outcome.status == 'stop'
    assert outcome.exit_price == price
    assert outcome.realized_r == -2


@pytest.mark.parametrize('direction,price', [('long', 115), ('short', 85)])
def test_gap_target_precedes_later_stop(direction, price):
    outcome = resolve_plan(plan(direction), [Candle('t', price, 120, 80, 100)])
    assert outcome.status == 'target'
    assert outcome.realized_r == 2


@pytest.mark.parametrize('direction', ['long', 'short'])
@pytest.mark.parametrize('policy,expected', [('conservative', -1), ('optimistic', 2), ('skip', None)])
def test_ambiguity_policies(direction, policy, expected):
    outcome = resolve_plan(plan(direction), [Candle('t', 100, 111, 89, 100)], ambiguous_policy=policy)
    assert outcome.realized_r == expected


def test_open_and_invalid_policy():
    assert resolve_plan(plan(), []).candles_seen == 0
    assert resolve_plan(plan(), [Candle('t', 100, 101, 99, 100)]).status == 'open'
    with pytest.raises(ValueError):
        resolve_plan(plan(), [], ambiguous_policy='unknown')


def test_csv_validation(tmp_path):
    path = tmp_path / 'bad.csv'
    path.write_text('timestamp,open\nt,100\n')
    with pytest.raises(ValueError, match='missing'):
        load_ohlc_csv(path)


def test_paper_research_pipeline(tmp_path):
    assert set(DESKS) == {'victor', 'alpha', 'beta', 'ben', 'jah'}
    candles = load_ohlc_csv(Path(__file__).resolve().parents[1] / 'data/example_ohlc.csv')
    journal = tmp_path / 'journal.jsonl'
    for desk in DESKS.values():
        p = plan()
        outcome = resolve_plan(p, candles)
        trade = PaperTrade(p, outcome.exit_price, position_size(p, fractional=False), desk=desk.name)
        assert pnl(trade) == 40
        assert realized_r(trade) == outcome.realized_r == 2
        append_trade(journal, trade)
    trades = load_trades(journal)
    assert len(trades) == 5
    assert {t.desk for t in trades} == {d.name for d in DESKS.values()}
    assert summarize(trades).average_r == 2
    assert performance_metrics(realized_r(t) for t in trades).max_drawdown_r == 0
    experiment = Experiment('synthetic', 'verify pipeline', 'fixed', 'example_ohlc.csv', {'policy': 'conservative'})
    path = tmp_path / 'experiment.json'
    save_experiment(path, experiment)
    assert experiment.experiment_id in path.read_text()
    output = subprocess.run([sys.executable, '-m', 'sc_rd', 'stats', str(journal)], capture_output=True, text=True, check=True)
    assert 'average_r=2.0' in output.stdout


def test_empty_and_corrupt_journal(tmp_path):
    path = tmp_path / 'journal.jsonl'
    assert load_trades(path) == []
    assert summarize([]).trades == 0
    assert performance_metrics([]).profit_factor is None
    path.write_text('{broken}\n')
    with pytest.raises(ValueError):
        load_trades(path)
