import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from sc_rd.backtest import Candle
from sc_rd.lab import evaluate_lab, lab_markdown, run_lab, select
from sc_rd.research import Costs, read_dataset, summary
from sc_rd.strategy import Breakout, signal_at, simulate


ZERO = Costs(0, 0, 0, 0)


def bars():
    return [Candle('0', 100, 101, 98, 100), Candle('1', 100, 102, 99, 101),
            Candle('2', 101, 108, 100, 105), Candle('3', 109, 135, 100, 130),
            Candle('4', 130, 132, 120, 125)]


def strategy(**kwargs):
    return Breakout(**(dict(name='baseline', desk='victor', lookback=2, reward_r=2, max_holding_bars=2) | kwargs))


def run(candles, spec=None, start=0, end=None, **kwargs):
    return simulate(candles, spec or strategy(), start, end or len(candles), symbol='SYNTH',
                    risk_budget=20, costs=kwargs.pop('costs', ZERO), **kwargs)


def test_signal_uses_prior_range_not_current_high():
    signal = signal_at(bars(), 2, strategy())
    assert signal.direction == 'long'
    assert signal.stop == 98
    assert signal_at(bars(), 1, strategy()) is None


def test_touching_range_is_not_breakout():
    data = bars()
    data[2] = Candle('2', 101, 108, 100, 102)
    assert signal_at(data, 2, strategy()) is None


def test_prior_close_can_enter_first_window_open():
    result = run(bars(), start=3)['trades'][0]
    assert result['entry_index'] == 3
    assert result['signal']['index'] == 2


def test_window_cannot_consume_future_exit():
    data = bars()[:3] + [Candle('3', 105, 106, 103, 104), Candle('4', 104, 150, 103, 140)]
    result = run(data, end=4)['trades'][0]
    assert result['status'] == 'open'
    assert result['net_r'] is None
    assert result['candles_seen'] == 1


def test_signal_prefix_invariance():
    data = bars()
    for i in range(len(data)):
        assert signal_at(data, i, strategy()) == signal_at(data[:i+1], i, strategy())
    mutated = data[:3] + [Candle('future', 1, 1000, .5, 900)]
    assert signal_at(mutated, 2, strategy()) == signal_at(data, 2, strategy())


def test_next_open_gap_changes_sizing_not_signal():
    result = run(bars())['trades'][0]
    assert result['signal']['index'] == 2
    assert result['entry_index'] == 3
    assert result['plan']['entry'] == 109
    assert result['plan']['stop'] == 98
    assert result['plan']['target'] == 131
    assert result['quantity'] == pytest.approx(20/11)
    assert result['gross_r'] == 2


def test_entry_bar_extremes_cannot_change_entry_plan():
    before = run(bars())['trades'][0]
    changed = bars()
    changed[3] = Candle('3', 109, 200, 10, 190)
    after = run(changed)['trades'][0]
    assert before['plan'] == after['plan']
    assert before['quantity'] == after['quantity']
    assert after['gross_r'] == -1


def test_no_same_bar_or_final_bar_entry():
    assert run(bars()[:3])['trades'] == []
    assert all(t['entry_index'] == t['signal']['index'] + 1 for t in run(bars())['trades'])


def test_gap_through_stop_skips_entry():
    data = bars()[:3] + [Candle('3', 97, 101, 96, 100)]
    result = run(data)
    assert result['trades'] == []
    assert len(result['skipped_entries']) == 1


def test_short_signal_next_open_and_costs():
    # Reflect prices around 200 to create the equivalent short setup.
    data = [Candle(c.timestamp, 200-c.open, 200-c.low, 200-c.high, 200-c.close) for c in bars()]
    result = run(data, costs=Costs(.1, 1, 2, 1))['trades'][0]
    assert result['plan']['direction'] == 'short'
    assert result['plan']['entry'] == 91
    assert result['gross_r'] == 2
    assert result['net_r'] < 2
    assert signal_at(data, 2, strategy(direction='long')) is None


def test_timeout_and_boundary_open_are_distinct():
    data = bars()[:3] + [Candle('3', 105, 106, 103, 104)]
    timeout = run(data, strategy(max_holding_bars=1))['trades'][0]
    assert timeout['status'] == 'timeout'
    assert timeout['gross_r'] == pytest.approx(-1/7)
    unresolved = run(data, strategy(max_holding_bars=2))['trades'][0]
    assert unresolved['status'] == 'open'
    assert unresolved['net_r'] is None
    assert unresolved['exit_index'] is None


def test_exit_gap_can_lose_more_than_one_r():
    data = bars()[:3] + [Candle('3', 105, 106, 103, 104), Candle('4', 90, 95, 89, 92)]
    result = run(data)['trades'][0]
    assert result['status'] == 'stop'
    assert result['exit_price'] == 90
    assert result['gross_r'] == pytest.approx(-15/7)


def test_skip_ambiguity_blocks_further_entries():
    data = bars()
    data[3] = Candle('3', 109, 140, 90, 110)
    result = run(data, ambiguous_policy='skip')
    assert len(result['trades']) == 1
    assert result['trades'][0]['status'] == 'ambiguous'
    assert result['summary']['closed'] == 0


@pytest.mark.parametrize('field,value', [('lookback', 0), ('lookback', True), ('reward_r', math.nan),
    ('reward_r', math.inf), ('reward_r', 0), ('max_holding_bars', -1), ('direction', 'live'), ('desk', 'unknown'), ('name', '')])
def test_invalid_strategy(field, value):
    with pytest.raises(ValueError):
        strategy(**{field: value})


@pytest.fixture
def case(tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'examples/strategy_lab.json').read_text())
    config['dataset'] = 'bars.csv'
    (tmp_path / 'bars.csv').write_bytes((root / 'data/strategy_ohlc.csv').read_bytes())
    return config, tmp_path


def test_windows_and_nonoverlap(case):
    config, base = case
    result = evaluate_lab(config, base)
    assert [(f['train_start'], f['test_start'], f['test_end_exclusive']) for f in result['folds']] == [(0,24,36),(12,36,48),(24,48,60)]
    assert result['holdout_start'] == 60
    assert result['holdout_status'] == 'withheld'
    assert result['final_holdout'] is None
    for fold in result['folds']:
        for period in ('training', 'testing'):
            for candidate in fold[period]:
                previous_exit = -1
                for trade in candidate['trades']:
                    assert candidate['start'] <= trade['entry_index'] < candidate['end_exclusive']
                    assert trade['entry_index'] > previous_exit
                    assert trade['signal']['index'] < trade['entry_index']
                    if trade['exit_index'] is not None:
                        assert trade['exit_index'] < candidate['end_exclusive']
                        previous_exit = trade['exit_index']


def test_training_choice_does_not_see_next_test(case):
    config, base = case
    before = evaluate_lab(config, base)
    path = base / 'bars.csv'
    lines = path.read_text().splitlines()
    # Change first test candle while retaining valid prices and timestamps.
    timestamp = lines[25].split(',')[0]
    lines[25] = timestamp + ',100,500,1,400'
    path.write_text('\n'.join(lines)+'\n')
    after = evaluate_lab(config, base)
    assert before['folds'][0]['training'] == after['folds'][0]['training']
    assert before['folds'][0]['selected'] == after['folds'][0]['selected']


def test_holdout_cannot_change_development_or_final_choice(case):
    config, base = case
    before = evaluate_lab(config, base, include_holdout=True)
    path = base / 'bars.csv'
    lines = path.read_text().splitlines()
    for i in range(61, len(lines)):
        lines[i] = lines[i].split(',')[0] + ',100,500,1,400'
    path.write_text('\n'.join(lines)+'\n')
    after = evaluate_lab(config, base, include_holdout=True)
    assert before['folds'] == after['folds']
    assert before['final_training'] == after['final_training']
    assert before['final_selected'] == after['final_selected']
    assert before['run_id'] != after['run_id']


def test_default_never_evaluates_holdout(case, monkeypatch):
    config, base = case
    import sc_rd.lab as lab
    real = lab.simulate
    ranges = []
    def checked(candles, spec, start, end, **kwargs):
        ranges.append((start, end))
        assert end <= 60
        return real(candles, spec, start, end, **kwargs)
    monkeypatch.setattr(lab, 'simulate', checked)
    evaluate_lab(config, base)
    assert ranges


def training(name, values, unresolved=False):
    rows = [{'net_r': v, 'status': 'target' if v > 0 else 'stop'} for v in values]
    if unresolved:
        rows.append({'net_r': None, 'status': 'open'})
    return {'strategy': {'name': name}, 'summary': summary(rows, 1)}


def test_selection_ties_threshold_and_unresolved():
    assert select([training('z', [1, 1]), training('a', [1, 1])], 2) == 'a'
    assert select([training('x', [100], True), training('y', [-1, -1])], 2) == 'y'
    assert select([training('x', [100], True)], 1) is None
    assert select([training('x', [1])], 2) is None


def test_abstention_and_partial_last_fold(case):
    config, base = case
    config['minimum_trades'] = 1000
    config['test_bars'] = 13
    result = evaluate_lab(config, base, include_holdout=True)
    assert result['abstained_folds'] == 3
    assert result['final_selected'] is None
    assert result['walk_forward_selected']['submitted'] == 0
    assert result['folds'][-1]['test_end_exclusive'] == 60
    assert [e['strategy']['name'] for e in result['final_holdout']] == [config['baseline']]


def test_determinism_and_opt_in_holdout(case):
    config, base = case
    before = copy.deepcopy(config)
    a = evaluate_lab(config, base)
    assert config == before
    assert evaluate_lab(config, base) == a
    revealed = evaluate_lab(config, base, include_holdout=True)
    assert revealed['run_id'] != a['run_id']
    assert revealed['folds'] == a['folds']
    assert {e['strategy']['name'] for e in revealed['final_holdout']} <= {config['baseline'], revealed['final_selected']}
    assert 'now consumed' in lab_markdown(revealed)
    assert '**withheld**' in lab_markdown(a)


@pytest.mark.parametrize('field,value', [('train_bars', 2), ('holdout_bars', 70), ('test_bars', 0),
    ('minimum_trades', True), ('baseline', 'missing'), ('risk_budget', math.inf), ('risk_budget', -1), ('schema_version', 2)])
def test_invalid_lab_config(case, field, value):
    config, base = case
    config[field] = value
    with pytest.raises(ValueError):
        evaluate_lab(config, base)


def test_reports_and_cli(case):
    config, base = case
    path = base / 'lab.json'
    path.write_text(json.dumps(config))
    output = run_lab(path, base / 'reports')
    original = (output / 'results.json').read_bytes()
    with pytest.raises(FileExistsError):
        run_lab(path, base / 'reports')
    assert (output / 'results.json').read_bytes() == original
    cli = subprocess.run([sys.executable, '-m', 'sc_rd', 'lab', str(path), '--output', str(base / 'cli')], text=True, capture_output=True)
    assert cli.returncode == 0, cli.stderr
    assert (base / 'cli' / output.name / 'results.json').read_bytes() == original
    reveal = subprocess.run([sys.executable, '-m', 'sc_rd', 'lab', str(path), '--include-holdout', '--output', str(base / 'revealed')], text=True, capture_output=True)
    assert reveal.returncode == 0, reveal.stderr
    payload = json.loads((Path(reveal.stdout.strip()) / 'results.json').read_text())
    assert payload['final_holdout'] is not None
